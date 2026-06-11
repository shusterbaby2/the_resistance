"""Rebuild engine state from a recorded event log.

Used to run the post-game debrief phase against a finished game without
re-playing missions or re-calling models for earlier turns.
"""

from __future__ import annotations

from .beliefs import Beliefs, SeatBelief
from .events import Event, EventType
from .state import GameState, MissionRecord, PlayerState, Role, VoteRecord
from .views import TranscriptEntry

WINNER_BY_LABEL = {"resistance": Role.RESISTANCE, "spies": Role.SPY}


class HydrateError(ValueError):
    pass


def events_through_game_end(events: list[Event]) -> tuple[list[Event], int]:
    """Return events up to and including game_end, and that event's index."""
    try:
        end_idx = next(i for i, e in enumerate(events) if e["type"] == EventType.GAME_END)
    except StopIteration as exc:
        raise HydrateError("log has no game_end event — game is not finished") from exc
    return events[: end_idx + 1], end_idx


def hydrate_for_debrief(events: list[Event]) -> tuple[
    GameState, list[TranscriptEntry], dict[int, Beliefs], list[str], int
]:
    """Fold a finished game log into state the debrief phase can use."""
    core, end_idx = events_through_game_end(events)
    start = core[0]
    if start["type"] != EventType.GAME_START:
        raise HydrateError("log must begin with game_start")

    ids = [p["id"] for p in sorted(start["players"], key=lambda p: p["seat"])]
    id_to_seat = {p["id"]: p["seat"] for p in start["players"]}
    roles = start.get("roles", {})

    players = [
        PlayerState(
            seat=p["seat"],
            name=p["name"],
            role=Role(roles[p["id"]]),
            is_human=bool(p.get("isHuman")),
        )
        for p in start["players"]
    ]

    transcript: list[TranscriptEntry] = []
    beliefs: dict[int, Beliefs] = {}
    votes: list[VoteRecord] = []
    missions: list[MissionRecord] = []
    last_leader_seat = 0
    last_round = 1
    last_attempt = 1
    last_proposal_team: list[int] | None = None
    last_proposal_leader_seat: int | None = None
    winner: Role | None = None
    win_reason: str | None = None

    for e in core:
        t = e["type"]
        if t == EventType.ROUND_START:
            last_round = e["round"]
            last_attempt = e["attempt"]
            last_leader_seat = id_to_seat[e["leader"]]
        elif t == EventType.SPEECH:
            seat = id_to_seat[e["agent"]]
            transcript.append(TranscriptEntry(
                seat=seat, name=players[seat].name, text=e["text"],
            ))
        elif t == EventType.THOUGHT and e.get("beliefs"):
            seat = id_to_seat[e["agent"]]
            beliefs[seat] = Beliefs(entries=[
                SeatBelief(
                    seat=id_to_seat[tid],
                    suspicion=max(0.0, min(1.0, float(val))),
                    reason="from log",
                )
                for tid, val in e["beliefs"].items()
                if tid in id_to_seat and id_to_seat[tid] != seat
            ])
        elif t == EventType.PROPOSAL:
            last_proposal_team = [id_to_seat[p] for p in e["team"]]
            last_proposal_leader_seat = id_to_seat[e["leader"]]
        elif t == EventType.TEAM_VOTE:
            votes.append(VoteRecord(
                round_num=e["round"],
                attempt=e["attempt"],
                leader=last_proposal_leader_seat if last_proposal_leader_seat is not None
                       else last_leader_seat,
                team=list(last_proposal_team or []),
                votes={
                    id_to_seat[v["player"]]: v["vote"] == "approve"
                    for v in e["votes"]
                },
                approved=e["outcome"] == "approved",
            ))
        elif t == EventType.MISSION:
            missions.append(MissionRecord(
                round_num=e["round"],
                team=[id_to_seat[p] for p in e["team"]],
                fails=e["fails"],
                succeeded=e["outcome"] == "success",
            ))
        elif t == EventType.GAME_END:
            winner = WINNER_BY_LABEL[e["winner"]]
            win_reason = e["reason"]

    state = GameState(
        seed=int(start.get("seed", 0)),
        players=players,
        round_num=last_round,
        leader_seat=last_leader_seat,
        attempt=last_attempt,
        votes=votes,
        missions=missions,
        winner=winner,
        win_reason=win_reason,
    )
    next_seq = end_idx + 1
    return state, transcript, beliefs, ids, next_seq


def attach_debrief_state(
    engine,
    *,
    state: GameState,
    transcript: list[TranscriptEntry],
    beliefs: dict[int, Beliefs],
    ids: list[str],
    next_seq: int,
) -> None:
    engine.state = state
    engine.transcript = transcript
    engine.beliefs = beliefs
    engine.ids = ids
    engine._seq = next_seq


def run_debrief_from_log(
    path,
    seats,
    listeners=None,
) -> list[Event]:
    from .eventlog import load_events
    from .engine import GameEngine

    events = load_events(path)
    state, transcript, beliefs, ids, next_seq = hydrate_for_debrief(events)
    engine = GameEngine(seats, seed=state.seed, listeners=list(listeners or []))
    attach_debrief_state(
        engine,
        state=state,
        transcript=transcript,
        beliefs=beliefs,
        ids=ids,
        next_seq=next_seq,
    )
    emitted: list[Event] = []
    engine.listeners.append(emitted.append)
    engine.run_debrief_phase()
    return emitted
