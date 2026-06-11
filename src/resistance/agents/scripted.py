"""Deterministic scripted agents for tests and offline play (no API key).

Uses the same PRESETS personas as LLM agents so offline/watch mode still
feels like a table of characters, not debug bots.
"""

import random

from .. import rules
from ..beliefs import Beliefs, SeatBelief
from ..personality import PRESETS, Personality
from ..state import Role
from ..views import SeatView
from .base import Action, AgentOutput, Controller


def _player_name(view: SeatView, seat: int) -> str:
    for p in view.players:
        if p.seat == seat:
            return p.name
    return f"seat {seat}"


def _team_label(view: SeatView, team: list[int] | None) -> str:
    if not team:
        return "nobody"
    return " · ".join(_player_name(view, s) for s in team)


class RandomController(Controller):
    """Plays legally and deterministically for a given seed. No real strategy."""

    def __init__(self, seat: int, seed: int, persona: Personality | None = None):
        self.seat = seat
        self.persona = persona or PRESETS[seat % len(PRESETS)]
        self.rng = random.Random(f"{seed}:{seat}:{self.persona.name}")

    def _random_team(self, view: SeatView) -> list[int]:
        others = [p.seat for p in view.players if p.seat != view.seat]
        return sorted([view.seat] + self.rng.sample(others, view.team_size - 1))

    def _speaks_up(self) -> bool:
        # talkativeness 3 ≈ speaks ~35% of turns; 9 ≈ ~85%.
        threshold = 0.15 + self.persona.talkativeness * 0.08
        return self.rng.random() < threshold

    def _leader_name(self, view: SeatView) -> str:
        return _player_name(view, view.leader_seat)

    def _suspect_pick(self, view: SeatView) -> tuple[int, str]:
        others = [p for p in view.players if p.seat != view.seat]
        target = self.rng.choice(others)
        reasons = [
            f"voted wrong on attempt {view.attempt}",
            "still unproven after last mission",
            "talking a lot, proving nothing",
            "too agreeable when the math was ugly",
            "hasn't been on a clean mission yet",
        ]
        return target.seat, self.rng.choice(reasons)

    def _beliefs(self, view: SeatView) -> Beliefs:
        others = [p for p in view.players if p.seat != view.seat]
        suspect, reason = self._suspect_pick(view)
        return Beliefs(
            entries=[
                SeatBelief(
                    seat=p.seat,
                    suspicion=round(
                        self.rng.uniform(0.45, 0.85)
                        if p.seat == suspect
                        else self.rng.uniform(0.1, 0.4),
                        2,
                    ),
                    reason=reason if p.seat == suspect else "nothing damning yet",
                )
                for p in others
            ]
        )

    def _propose_copy(self, view: SeatView, team: list[int]) -> tuple[str, str]:
        leader = self._leader_name(view)
        team_s = _team_label(view, team)
        n = self.persona.name
        if n == "Marlow":
            reasoning = (
                f"I'm leading — put {team_s} on the mission and let the cards "
                f"settle who's full of it."
            )
            speech = f"{team_s}. Clean read, no drama — vote it."
        elif n == "Vex":
            reasoning = (
                f"Small sample, but {team_s} is the lowest-variance line I see "
                f"for round {view.round_num}."
            )
            speech = f"I'll run {team_s}. If it fails, the pool is two wide."
        elif n == "Juno":
            reasoning = (
                f"Okay, leader brain: {team_s} feels like the honest try — "
                f"I want table buy-in before we lock it."
            )
            speech = (
                f"Floating {team_s} — tell me what scares you before I commit."
            )
        elif n == "Castor":
            reasoning = (
                f"Consensus play: {team_s} gives us information without "
                f"burning another rejection."
            )
            speech = (
                f"I'd like to try {team_s} and see how the room reacts."
            )
        else:  # Sable
            reasoning = (
                f"Let's poke the table with {team_s} and watch who squirms."
            )
            speech = f"How about {team_s}? Someone's going to hate it."
        return reasoning, speech

    def _discuss_copy(self, view: SeatView) -> tuple[str, str]:
        leader = self._leader_name(view)
        team_s = _team_label(view, view.current_team)
        n = self.persona.name
        fails = sum(1 for m in view.missions if not m.succeeded)
        on_own_pick = view.seat == view.leader_seat
        if n == "Marlow":
            reasoning = (
                f"{leader} wants {team_s}. One fail on the board — I'm not "
                f"handing out trust coupons."
            )
            speech = (
                f"Still testing {team_s}." if on_own_pick
                else f"{leader}, defend {team_s} or I'm voting no."
            )
        elif n == "Vex":
            reasoning = (
                f"Only {len(view.missions)} mission(s) logged. {team_s} is "
                f"testable; the talk around it matters less than the vote."
            )
            speech = (
                f"The line is {team_s}. Fine — but the next fail narrows fast."
            )
        elif n == "Juno":
            reasoning = (
                f"I keep turning {team_s} over in my head — someone at this "
                f"table is smiling too much."
            )
            speech = (
                f"Hearing you out on {team_s} — change my mind."
                if on_own_pick
                else f"I'm not sold on {team_s} yet, but convince me, {leader}."
            )
        elif n == "Castor":
            reasoning = (
                f"Score is {fails} fail(s). {team_s} might be workable if "
                f"we don't burn attempt {view.attempt}."
            )
            speech = (
                f"Could live with {team_s} if the room's aligned."
            )
        else:  # Sable
            reasoning = (
                f"{leader} floated {team_s} like it's obvious. That's usually "
                f"when someone's hiding."
            )
            speech = (
                f"Cozy pick, {leader}. What's wrong with testing someone new?"
            )
        return reasoning, speech

    def _reconsider_copy(self, view: SeatView, *, submit: bool,
                         team: list[int] | None) -> tuple[str, str]:
        n = self.persona.name
        if submit:
            team_s = _team_label(view, view.current_team)
            if n == "Castor":
                return (
                    f"Room's had its say — time to put {team_s} to a vote.",
                    f"Locking {team_s}. Let's vote.",
                )
            return (
                f"Heard enough. {team_s} goes to the table.",
                self.rng.choice([
                    f"Submitting {team_s}.",
                    f"Let's vote on {team_s}.",
                    "",
                ]),
            )
        team_s = _team_label(view, team)
        return (
            f"Pushback on { _team_label(view, view.current_team) } — "
            f"trying {team_s} instead.",
            f"Alternate: {team_s}. React to this one.",
        )

    def act(self, view: SeatView, action: Action) -> AgentOutput:
        beliefs = self._beliefs(view)
        if action == Action.PROPOSE:
            team = self._random_team(view)
            reasoning, speech = self._propose_copy(view, team)
            return AgentOutput(
                reasoning=reasoning, speech=speech, team=team, beliefs=beliefs,
            )
        if action == Action.RECONSIDER:
            if view.suggestion_num >= rules.MAX_SUGGESTIONS or self.rng.random() < 0.55:
                reasoning, speech = self._reconsider_copy(view, submit=True, team=None)
                return AgentOutput(
                    reasoning=reasoning, speech=speech, submit=True, beliefs=beliefs,
                )
            team = self._random_team(view)
            reasoning, speech = self._reconsider_copy(
                view, submit=False, team=team,
            )
            return AgentOutput(
                reasoning=reasoning, speech=speech, submit=False,
                team=team, beliefs=beliefs,
            )
        if action == Action.DISCUSS:
            if not self._speaks_up():
                return AgentOutput(
                    reasoning="Nothing worth adding — let them talk.",
                    beliefs=beliefs,
                )
            reasoning, speech = self._discuss_copy(view)
            return AgentOutput(
                reasoning=reasoning, speech=speech, beliefs=beliefs,
            )
        if action == Action.VOTE:
            on_team = view.seat in (view.current_team or [])
            approve = on_team or self.rng.random() < 0.55
            team_s = _team_label(view, view.current_team)
            if approve:
                tag = "I'm on it" if on_team else "worth the information"
                reasoning = f"Approving {team_s} — {tag}."
            else:
                reasoning = (
                    f"Rejecting {team_s} — attempt {view.attempt} isn't free."
                )
            return AgentOutput(reasoning=reasoning, vote=approve, beliefs=beliefs)
        if action == Action.MISSION:
            if view.role == Role.SPY:
                fail = self.rng.random() > 0.65
                if fail:
                    reasoning = (
                        "Fail now while the blame pool is wide enough to swim in."
                    )
                else:
                    reasoning = (
                        "Bank trust with a success — spend it when the team is bigger."
                    )
                return AgentOutput(
                    reasoning=reasoning, mission_success=not fail,
                )
            return AgentOutput(
                reasoning="Resistance plays success. Always.",
                mission_success=True,
            )
        raise ValueError(f"unknown action {action}")
