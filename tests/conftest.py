import pytest

from resistance.agents.base import Action, AgentOutput, Controller
from resistance.engine import GameEngine, SeatConfig
from resistance.state import Role


class ScriptableController(Controller):
    """Test controller with overridable behavior per action."""

    def __init__(self, vote=True, spy_plays_success=False, team_picker=None):
        self.vote = vote
        self.spy_plays_success = spy_plays_success
        self.team_picker = team_picker

    def act(self, view, action):
        if action == Action.PROPOSE:
            if self.team_picker:
                team = self.team_picker(view)
            else:
                team = sorted(p.seat for p in view.players)[: view.team_size]
            return AgentOutput(team=team, speech="team up", reasoning="test")
        if action == Action.RECONSIDER:
            return AgentOutput(submit=True, reasoning="test")
        if action == Action.DISCUSS:
            return AgentOutput(reasoning="test")
        if action == Action.VOTE:
            vote = self.vote(view) if callable(self.vote) else self.vote
            return AgentOutput(vote=vote, reasoning="test")
        if action == Action.MISSION:
            if view.role == Role.SPY:
                return AgentOutput(mission_success=self.spy_plays_success)
            return AgentOutput(mission_success=True)
        if action == Action.DEBRIEF:
            return AgentOutput(
                strategy="test strategy",
                best_move="test move",
                mistake="test mistake",
                confusion="test confusion",
            )
        raise ValueError(action)


def make_engine(controller_factory, seed=42, listeners=None):
    seats = [SeatConfig(name=f"P{i}", controller=controller_factory(i))
             for i in range(5)]
    return GameEngine(seats, seed=seed, listeners=listeners or [])


@pytest.fixture
def collect():
    events = []
    return events
