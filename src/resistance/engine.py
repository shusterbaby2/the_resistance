"""The game state machine.

Drives assignment → suggestion loop → vote → mission → win/loss,
emitting one schema-v1 event per beat (see resistance_ui/resistance-event-schema.md).

Per attempt the leader may float up to MAX_SUGGESTIONS teams for discussion;
after each float everyone discusses (staying quiet is fine). The leader then
submits for a vote or suggests an alternate team. The third suggestion auto-
submits after discussion.
The engine never renders; renderers never run game logic. Controllers (LLM,
scripted, human) are the only I/O boundary and every seat is treated identically.

Table talk uses a mechanical speaking-bid orchestrator: only the bid winner
gets a DISCUSS controller call per slot.

Decisions the rules make simultaneous — votes, mission cards, debriefs — run
their controller calls concurrently (one thread per seat); event emission stays
on the engine thread in seat order so the log is deterministic.
"""

import random
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable

from . import rules
from .agents.base import Action, AgentOutput, Controller
from .beliefs import Beliefs
from .bidding import (
    DEFAULT_MAX_TURNS,
    RAISED_HAND_BID,
    SPEAK_FLOOR,
    DiscussionTracker,
    compute_bids,
    pick_speaker,
    table_wants_to_talk,
)
from .events import Event, EventType
from .personality import NEUTRAL, Personality
from .state import GameState, MissionRecord, PlayerState, Role, VoteRecord
from .views import TranscriptEntry, build_seat_view

EventListener = Callable[[Event], None]

WINNER_LABEL = {Role.RESISTANCE: "resistance", Role.SPY: "spies"}


@dataclass
class SeatConfig:
    name: str
    controller: Controller
    is_human: bool = False
    personality: Personality | None = None
    # Optional "raised hand" probe: when it returns True, this seat outbids
    # the table for the next discussion slot. Mechanical, like every other
    # bid modifier — no LLM is consulted to decide who speaks.
    wants_floor: Callable[[], bool] | None = None


class GameEngine:
    def __init__(
        self,
        seats: list[SeatConfig],
        seed: int,
        listeners: list[EventListener] | None = None,
        discussion_speak_floor: float = SPEAK_FLOOR,
        discussion_max_turns: int = DEFAULT_MAX_TURNS,
    ):
        if len(seats) != rules.N_PLAYERS:
            raise ValueError(f"exactly {rules.N_PLAYERS} seats required")
        self.seats = seats
        self.ids = self._make_ids(seats)
        self.seed = seed
        self.rng = random.Random(seed)
        self.listeners = list(listeners or [])
        self.discussion_speak_floor = discussion_speak_floor
        self.discussion_max_turns = discussion_max_turns
        self._personas = {
            i: self._resolve_personality(cfg) for i, cfg in enumerate(seats)
        }
        self.state: GameState | None = None
        self.transcript: list[TranscriptEntry] = []
        self.beliefs: dict[int, Beliefs] = {}
        self._seq = 0

    @staticmethod
    def _make_ids(seats: list[SeatConfig]) -> list[str]:
        ids: list[str] = []
        for i, cfg in enumerate(seats):
            base = re.sub(r"[^a-z0-9]+", "_", cfg.name.lower()).strip("_") or f"p{i}"
            ids.append(base if base not in ids else f"{base}{i}")
        return ids

    def _id(self, seat: int) -> str:
        return self.ids[seat]

    @staticmethod
    def _resolve_personality(cfg: SeatConfig) -> Personality:
        if cfg.personality is not None:
            return cfg.personality
        persona = getattr(cfg.controller, "persona", None)
        if persona is not None:
            return persona
        return NEUTRAL

    # ------------------------------------------------------------- events

    def emit(self, type_: str, round_: int | None = None, **fields) -> None:
        event: Event = {"t": self._seq, "type": type_}
        if round_ is not None:
            event["round"] = round_
        event.update(fields)
        self._seq += 1
        for listener in self.listeners:
            listener(event)

    # ------------------------------------------------------------- setup

    def _assign_roles(self) -> None:
        spy_seats = set(self.rng.sample(range(rules.N_PLAYERS), rules.N_SPIES))
        players = [
            PlayerState(
                seat=i,
                name=cfg.name,
                role=Role.SPY if i in spy_seats else Role.RESISTANCE,
                is_human=cfg.is_human,
            )
            for i, cfg in enumerate(self.seats)
        ]
        self.state = GameState(
            seed=self.seed,
            players=players,
            leader_seat=self.rng.randrange(rules.N_PLAYERS),
        )
        self.emit(
            EventType.GAME_START,
            players=[
                {"id": self._id(p.seat), "name": p.name, "seat": p.seat,
                 "isHuman": p.is_human}
                for p in players
            ],
            roles={self._id(p.seat): p.role.value for p in players},
            missionPlan=[
                {"round": r, "size": rules.team_size(r), "failsToFail": 1}
                for r in range(1, rules.N_ROUNDS + 1)
            ],
            missionsToWin=rules.MISSIONS_TO_WIN,
            seed=self.seed,
        )

    # ------------------------------------------------------------- acting

    def _emit_turn_start(self, seat: int, action: Action,
                         round_: int | None) -> None:
        # Status beat so renderers can show who is deliberating (and silences
        # are attributable to thinking, not bugs). Mission turns omit the agent:
        # who is deciding what card must stay anonymous.
        turn_fields = {} if action == Action.MISSION else {"agent": self._id(seat)}
        self.emit(EventType.TURN_START, round_=round_,
                  action=action.value, **turn_fields)

    def _apply_output(self, seat: int, action: Action, out: AgentOutput,
                      round_: int | None) -> None:
        for record in out.meta.get("llm_calls", []):
            self.emit(EventType.LLM_CALL, round_=round_,
                      agent=self._id(seat), action=action.value, **record)
        if out.beliefs is not None:
            self.beliefs[seat] = out.beliefs
        if out.reasoning or out.beliefs is not None:
            fields: dict = {"agent": self._id(seat), "text": out.reasoning}
            if out.beliefs is not None:
                fields["beliefs"] = {
                    self._id(b.seat): b.suspicion for b in out.beliefs.entries
                }
            # Thought always precedes the matching speech (schema note).
            self.emit(EventType.THOUGHT, round_=round_, **fields)

    def _act(self, seat: int, action: Action) -> AgentOutput:
        round_ = self.state.round_num
        self._emit_turn_start(seat, action, round_)
        view = build_seat_view(self.state, seat, self.transcript,
                               self.beliefs.get(seat))
        out = self.seats[seat].controller.act(view, action)
        self._apply_output(seat, action, out, round_)
        return out

    def _act_simultaneous(self, seats: list[int], action: Action, *,
                          debrief: bool = False) -> dict[int, AgentOutput]:
        """Decisions the rules make simultaneous (votes, mission cards,
        debriefs): every controller acts concurrently on the same pre-decision
        view. Controllers share nothing, so threads are safe; all events are
        emitted from this thread in seat order, so the log stays deterministic."""
        round_ = None if debrief else self.state.round_num
        views = {}
        for seat in seats:
            self._emit_turn_start(seat, action, round_)
            views[seat] = build_seat_view(self.state, seat, self.transcript,
                                          self.beliefs.get(seat), debrief=debrief)
        with ThreadPoolExecutor(max_workers=len(seats)) as pool:
            futures = {
                seat: pool.submit(self.seats[seat].controller.act,
                                  views[seat], action)
                for seat in seats
            }
            outs = {seat: futures[seat].result() for seat in seats}
        for seat in seats:
            self._apply_output(seat, action, outs[seat], round_)
        return outs

    def _say(self, seat: int, text: str, *, bid: float | None = None) -> None:
        text = text.strip()
        if not text:
            return
        entry = TranscriptEntry(seat=seat, name=self.state.player(seat).name,
                                text=text)
        self.transcript.append(entry)
        fields: dict = {"agent": self._id(seat), "text": text}
        if bid is not None:
            fields["bid"] = round(bid, 2)
        self.emit(EventType.SPEECH, round_=self.state.round_num, **fields)

    # ------------------------------------------------------------- phases

    def _emit_suggestion(self, leader: int, team: list[int]) -> None:
        self.state.current_team = team
        self.emit(
            EventType.SUGGESTION,
            round_=self.state.round_num,
            leader=self._id(leader),
            attempt=self.state.attempt,
            suggestion=self.state.suggestion,
            team=[self._id(s) for s in team],
        )

    def _emit_proposal(self, leader: int) -> None:
        self.emit(
            EventType.PROPOSAL,
            round_=self.state.round_num,
            leader=self._id(leader),
            attempt=self.state.attempt,
            team=[self._id(s) for s in self.state.current_team],
        )

    def _validated_team(self, leader: int, team: list[int] | None) -> list[int]:
        size = self.state.team_size()
        valid_seats = set(range(rules.N_PLAYERS))
        if team is not None:
            cleaned = sorted(set(team) & valid_seats)
            if len(cleaned) == size:
                return cleaned
        # Engine-side last resort: leader plus deterministic random fill.
        others = [s for s in range(rules.N_PLAYERS) if s != leader]
        fixed = sorted([leader] + self.rng.sample(others, size - 1))
        self.emit(EventType.ENGINE_NOTE, round_=self.state.round_num,
                  agent=self._id(leader), note="invalid_team_corrected",
                  got=team, corrected_to=[self._id(s) for s in fixed])
        return fixed

    def _run_suggestion_phase(self) -> None:
        """Leader floats teams for discussion, then locks one in for the vote."""
        leader = self.state.leader_seat
        self.state.suggestion = 1

        out = self._act(leader, Action.PROPOSE)
        team = self._validated_team(leader, out.team)
        self._emit_suggestion(leader, team)
        self._say(leader, out.speech)
        self._run_discussion()

        while self.state.suggestion < rules.MAX_SUGGESTIONS:
            out = self._act(leader, Action.RECONSIDER)
            if out.submit is not False:
                self._say(leader, out.speech)
                self._emit_proposal(leader)
                return
            team = self._validated_team(leader, out.team)
            self.state.suggestion += 1
            self._emit_suggestion(leader, team)
            self._say(leader, out.speech)
            self._run_discussion()

        # Third suggestion: auto-submit after discussion.
        self._emit_proposal(leader)

    def _run_discussion(self) -> None:
        """Run bid rounds until the table goes quiet, then the leader RECONSIDERs."""
        tracker = DiscussionTracker(transcript_start=len(self.transcript))
        seats = range(rules.N_PLAYERS)
        turns = 0
        while turns < self.discussion_max_turns:
            bids = compute_bids(
                self.rng, self._personas, self.state, self.transcript, tracker,
            )
            for seat, cfg in enumerate(self.seats):
                if cfg.wants_floor is not None and cfg.wants_floor():
                    bids[seat] = max(bids[seat], RAISED_HAND_BID)
            if not table_wants_to_talk(bids, self.discussion_speak_floor):
                break
            winner, bid, _ = pick_speaker(
                self.rng, self._personas, self.state, self.transcript, tracker,
                bids=bids,
            )
            out = self._act(winner, Action.DISCUSS)
            if out.speech.strip():
                tracker.note_spoke(winner)
                tracker.note_utterance()
            else:
                tracker.note_pass(winner)
            self._say(winner, out.speech, bid=bid)
            tracker.note_slot(seats)
            turns += 1

    def _run_vote(self) -> bool:
        outs = self._act_simultaneous(list(range(rules.N_PLAYERS)), Action.VOTE)
        votes = {
            seat: out.vote if out.vote is not None else True
            for seat, out in outs.items()
        }
        approved = sum(votes.values()) >= rules.VOTES_TO_APPROVE
        self.state.votes.append(VoteRecord(
            round_num=self.state.round_num,
            attempt=self.state.attempt,
            leader=self.state.leader_seat,
            team=list(self.state.current_team),
            votes=votes,
            approved=approved,
        ))
        self.emit(EventType.TEAM_VOTE, round_=self.state.round_num,
                  attempt=self.state.attempt,
                  votes=[
                      {"player": self._id(s),
                       "vote": "approve" if votes[s] else "reject"}
                      for s in sorted(votes)
                  ],
                  outcome="approved" if approved else "rejected")
        return approved

    def _run_mission(self) -> None:
        team = list(self.state.current_team)
        spies = [s for s in team if self.state.player(s).role == Role.SPY]
        outs = self._act_simultaneous(spies, Action.MISSION) if spies else {}
        fails = 0
        cards = []
        for seat in team:
            if seat in outs:
                out = outs[seat]
                success = out.mission_success if out.mission_success is not None else True
            else:
                # Resistance has no choice; the engine plays success for them.
                success = True
            cards.append({"player": self._id(seat),
                          "card": "success" if success else "fail"})
            fails += 0 if success else 1
        succeeded = fails == 0
        self.state.missions.append(MissionRecord(
            round_num=self.state.round_num, team=team,
            fails=fails, succeeded=succeeded,
        ))
        self.state.current_team = None
        outcome = "success" if succeeded else "fail"
        self.emit(EventType.MISSION, round_=self.state.round_num,
                  team=[self._id(s) for s in team], fails=fails,
                  outcome=outcome, cards=cards)
        self.emit(EventType.ROUND_END, round_=self.state.round_num,
                  outcome=outcome, score=self._score())

    def _score(self) -> dict:
        return {"resistance": self.state.successes(), "spies": self.state.fails()}

    def _rotate_leader(self) -> None:
        self.state.leader_seat = (self.state.leader_seat + 1) % rules.N_PLAYERS

    def _finish(self, winner: Role, reason: str) -> None:
        self.state.winner = winner
        self.state.win_reason = reason
        self.emit(EventType.GAME_END, winner=WINNER_LABEL[winner],
                  score=self._score(), reason=reason,
                  roles={self._id(p.seat): p.role.value for p in self.state.players},
                  debrief=True)

    def run_debrief_phase(self) -> None:
        """Post-game reflections. Requires a finished game already in state."""
        if self.state is None or self.state.winner is None:
            raise RuntimeError("cannot debrief before the game has a winner")
        self._run_debrief()

    def _run_debrief(self) -> None:
        seats = list(range(rules.N_PLAYERS))
        outs = self._act_simultaneous(seats, Action.DEBRIEF, debrief=True)
        for seat in seats:
            out = outs[seat]
            self.emit(
                EventType.DEBRIEF,
                agent=self._id(seat),
                strategy=out.strategy,
                best_move=out.best_move,
                mistake=out.mistake,
                confusion=out.confusion,
            )

    # ------------------------------------------------------------- run

    def run(self) -> GameState:
        self._assign_roles()
        while self.state.winner is None:
            self.state.attempt = 1
            self.emit(EventType.ROUND_START, round_=self.state.round_num,
                      leader=self._id(self.state.leader_seat),
                      missionSize=self.state.team_size(),
                      attempt=self.state.attempt)
            approved = False
            while self.state.attempt <= rules.MAX_PROPOSALS_PER_ROUND:
                self.state.suggestion = 1
                self._run_suggestion_phase()
                approved = self._run_vote()
                self._rotate_leader()
                if approved:
                    break
                self.state.current_team = None
                self.state.attempt += 1
                self.state.suggestion = 1
            if not approved:
                self._finish(Role.SPY, "five_rejections")
                break
            self._run_mission()
            if self.state.successes() >= rules.MISSIONS_TO_WIN:
                self._finish(Role.RESISTANCE, "three_missions")
            elif self.state.fails() >= rules.MISSIONS_TO_WIN:
                self._finish(Role.SPY, "three_missions")
            else:
                self.state.round_num += 1
        self._run_debrief()
        return self.state
