"""Deterministic scripted agents for tests and offline play (no API key)."""

import random

from ..beliefs import Beliefs, SeatBelief
from ..state import Role
from ..views import SeatView
from .base import Action, AgentOutput, Controller

_CHATTER = [
    "I'm watching the vote pattern, not the talk.",
    "That team looks fine to me.",
    "Someone at this table is lying through their teeth.",
    "I'll go along with it, for now.",
    "Why that team and not the obvious one?",
    "No objections from me.",
]


class RandomController(Controller):
    """Plays legally and deterministically for a given seed. No real strategy."""

    def __init__(self, seat: int, seed: int):
        self.seat = seat
        self.rng = random.Random(f"{seed}:{seat}")

    def act(self, view: SeatView, action: Action) -> AgentOutput:
        if action == Action.PROPOSE:
            others = [p.seat for p in view.players if p.seat != view.seat]
            team = [view.seat] + self.rng.sample(others, view.team_size - 1)
            return AgentOutput(
                reasoning="scripted: self plus random fill",
                speech=f"I'm taking {len(team)} of us. Trust me.",
                team=sorted(team),
                beliefs=self._beliefs(view),
            )
        if action == Action.DISCUSS:
            if self.rng.random() < 0.5:
                return AgentOutput(reasoning="scripted: staying quiet")
            return AgentOutput(
                reasoning="scripted: canned chatter",
                speech=self.rng.choice(_CHATTER),
                beliefs=self._beliefs(view),
            )
        if action == Action.VOTE:
            approve = view.seat in (view.current_team or []) or self.rng.random() < 0.6
            return AgentOutput(reasoning="scripted: coin-flip vote", vote=approve)
        if action == Action.MISSION:
            if view.role == Role.SPY:
                return AgentOutput(
                    reasoning="scripted: spy sabotage roll",
                    mission_success=self.rng.random() > 0.7,
                )
            return AgentOutput(reasoning="scripted: resistance", mission_success=True)
        raise ValueError(f"unknown action {action}")

    def _beliefs(self, view: SeatView) -> Beliefs:
        return Beliefs(
            entries=[
                SeatBelief(seat=p.seat, suspicion=round(self.rng.random(), 2),
                           reason="scripted noise")
                for p in view.players
                if p.seat != view.seat
            ]
        )
