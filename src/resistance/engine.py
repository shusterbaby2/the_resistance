"""The game state machine.

Drives assignment → proposal → discussion → vote → mission → win/loss,
emitting one schema-v1 event per beat (see resistance_ui/resistance-event-schema.md).
The engine never renders; renderers never run game logic. Controllers (LLM,
scripted, human) are the only I/O boundary and every seat is treated identically.

Discussion is round-robin (the phase-1 do-first). The bidding orchestrator
replaces `_run_discussion` in phase 2 without touching the rest of the spine.
"""

import random
import re
from dataclasses import dataclass
from typing import Callable

from . import rules
from .agents.base import Action, AgentOutput, Controller
from .beliefs import Beliefs
from .events import Event, EventType
from .state import GameState, MissionRecord, PlayerState, Role, VoteRecord
from .views import TranscriptEntry, build_seat_view

EventListener = Callable[[Event], None]

WINNER_LABEL = {Role.RESISTANCE: "resistance", Role.SPY: "spies"}


@dataclass
class SeatConfig:
    name: str
    controller: Controller
    is_human: bool = False


class GameEngine:
    def __init__(
        self,
        seats: list[SeatConfig],
        seed: int,
        listeners: list[EventListener] | None = None,
        discussion_rounds: int = 1,
    ):
        if len(seats) != rules.N_PLAYERS:
            raise ValueError(f"exactly {rules.N_PLAYERS} seats required")
        self.seats = seats
        self.ids = self._make_ids(seats)
        self.seed = seed
        self.rng = random.Random(seed)
        self.listeners = list(listeners or [])
        self.discussion_rounds = discussion_rounds
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

    def _act(self, seat: int, action: Action) -> AgentOutput:
        # Status beat so renderers can show who is deliberating (and silences
        # are attributable to thinking, not bugs). Mission turns omit the agent:
        # who is deciding what card must stay anonymous.
        turn_fields = {} if action == Action.MISSION else {"agent": self._id(seat)}
        self.emit(EventType.TURN_START, round_=self.state.round_num,
                  action=action.value, **turn_fields)
        view = build_seat_view(self.state, seat, self.transcript,
                               self.beliefs.get(seat))
        out = self.seats[seat].controller.act(view, action)
        for record in out.meta.get("llm_calls", []):
            self.emit(EventType.LLM_CALL, round_=self.state.round_num,
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
            self.emit(EventType.THOUGHT, round_=self.state.round_num, **fields)
        return out

    def _say(self, seat: int, text: str) -> None:
        text = text.strip()
        if not text:
            return
        entry = TranscriptEntry(seat=seat, name=self.state.player(seat).name,
                                text=text)
        self.transcript.append(entry)
        self.emit(EventType.SPEECH, round_=self.state.round_num,
                  agent=self._id(seat), text=text)

    # ------------------------------------------------------------- phases

    def _propose(self) -> list[int]:
        leader = self.state.leader_seat
        out = self._act(leader, Action.PROPOSE)
        team = self._validated_team(leader, out.team)
        self.state.current_team = team
        self.emit(EventType.PROPOSAL, round_=self.state.round_num,
                  leader=self._id(leader), attempt=self.state.attempt,
                  team=[self._id(s) for s in team])
        self._say(leader, out.speech)
        return team

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

    def _run_discussion(self) -> None:
        leader = self.state.leader_seat
        order = [(leader + i) % rules.N_PLAYERS for i in range(1, rules.N_PLAYERS + 1)]
        for _ in range(self.discussion_rounds):
            for seat in order:
                out = self._act(seat, Action.DISCUSS)
                self._say(seat, out.speech)

    def _run_vote(self) -> bool:
        votes: dict[int, bool] = {}
        for seat in range(rules.N_PLAYERS):
            out = self._act(seat, Action.VOTE)
            votes[seat] = out.vote if out.vote is not None else True
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
        fails = 0
        cards = []
        for seat in team:
            if self.state.player(seat).role == Role.SPY:
                out = self._act(seat, Action.MISSION)
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
                  roles={self._id(p.seat): p.role.value for p in self.state.players})

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
                self._propose()
                self._run_discussion()
                approved = self._run_vote()
                self._rotate_leader()
                if approved:
                    break
                self.state.current_team = None
                self.state.attempt += 1
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
        return self.state
