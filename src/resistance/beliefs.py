"""Per-agent beliefs: suspicion of every other player, with reasons.

Each agent's beliefs are private to that agent — never shared between agents
(CLAUDE.md do-not #3) — and persisted by the engine so agents update lazily
when activated rather than re-deriving trust from the transcript.
"""

from pydantic import BaseModel, Field


class SeatBelief(BaseModel):
    seat: int
    suspicion: float  # 0.0 = certain resistance, 1.0 = certain spy
    reason: str = ""


class Beliefs(BaseModel):
    entries: list[SeatBelief] = Field(default_factory=list)

    def suspicion_of(self, seat: int) -> float | None:
        for entry in self.entries:
            if entry.seat == seat:
                return entry.suspicion
        return None
