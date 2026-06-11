"""Structured game state — the ground truth.

Agents reason over this data, never by re-deriving the game from the transcript
(see CLAUDE.md do-not #2).
"""

from enum import Enum

from pydantic import BaseModel, Field

from . import rules


class Role(str, Enum):
    RESISTANCE = "resistance"
    SPY = "spy"


class PlayerState(BaseModel):
    seat: int
    name: str
    role: Role
    is_human: bool = False


class VoteRecord(BaseModel):
    round_num: int
    attempt: int
    leader: int
    team: list[int]
    votes: dict[int, bool]  # seat -> approve
    approved: bool


class MissionRecord(BaseModel):
    round_num: int
    team: list[int]
    fails: int
    succeeded: bool


class GameState(BaseModel):
    seed: int
    players: list[PlayerState]
    round_num: int = 1
    leader_seat: int = 0
    attempt: int = 1
    suggestion: int = 1  # which floated team this attempt is on (1..MAX_SUGGESTIONS)
    current_team: list[int] | None = None
    votes: list[VoteRecord] = Field(default_factory=list)
    missions: list[MissionRecord] = Field(default_factory=list)
    winner: Role | None = None
    win_reason: str | None = None

    def player(self, seat: int) -> PlayerState:
        return self.players[seat]

    def spies(self) -> list[int]:
        return [p.seat for p in self.players if p.role == Role.SPY]

    def successes(self) -> int:
        return sum(1 for m in self.missions if m.succeeded)

    def fails(self) -> int:
        return sum(1 for m in self.missions if not m.succeeded)

    def team_size(self) -> int:
        return rules.team_size(self.round_num)
