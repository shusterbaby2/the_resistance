"""Per-seat filtered views of the game.

This module is the knowledge boundary: everything an agent (or the human's UI)
is allowed to know passes through `build_seat_view`. Spies learn each other's
seats; nobody learns anyone else's reasoning or beliefs.
"""

from pydantic import BaseModel, Field

from .beliefs import Beliefs
from .state import GameState, MissionRecord, Role, VoteRecord


class PlayerPublic(BaseModel):
    seat: int
    name: str
    is_you: bool = False


class TranscriptEntry(BaseModel):
    seat: int
    name: str
    text: str


class SeatView(BaseModel):
    seat: int
    name: str
    role: Role
    fellow_spies: list[int] = Field(default_factory=list)  # empty for resistance
    players: list[PlayerPublic]
    round_num: int
    leader_seat: int
    attempt: int
    suggestion_num: int  # which floated team this attempt is on
    team_size: int
    current_team: list[int] | None  # the currently suggested (not yet voted) team
    missions: list[MissionRecord]
    votes: list[VoteRecord]
    transcript: list[TranscriptEntry]
    beliefs: Beliefs | None = None  # this seat's own persisted beliefs
    game_over: bool = False
    winner: Role | None = None
    win_reason: str | None = None
    revealed_roles: dict[int, Role] = Field(default_factory=dict)


def build_seat_view(
    state: GameState,
    seat: int,
    transcript: list[TranscriptEntry],
    beliefs: Beliefs | None,
    *,
    debrief: bool = False,
) -> SeatView:
    me = state.player(seat)
    fellow_spies = (
        [s for s in state.spies() if s != seat] if me.role == Role.SPY else []
    )
    return SeatView(
        seat=seat,
        name=me.name,
        role=me.role,
        fellow_spies=fellow_spies,
        players=[
            PlayerPublic(seat=p.seat, name=p.name, is_you=(p.seat == seat))
            for p in state.players
        ],
        round_num=state.round_num,
        leader_seat=state.leader_seat,
        attempt=state.attempt,
        suggestion_num=state.suggestion,
        team_size=state.team_size(),
        current_team=list(state.current_team) if state.current_team else None,
        missions=list(state.missions),
        votes=list(state.votes),
        transcript=list(transcript),
        beliefs=beliefs,
        game_over=debrief,
        winner=state.winner if debrief else None,
        win_reason=state.win_reason if debrief else None,
        revealed_roles=(
            {p.seat: p.role for p in state.players} if debrief else {}
        ),
    )
