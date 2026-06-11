"""LLM agent wiring tests with a fake client — no API calls."""

from resistance.agents.llm_agent import (
    DiscussOut, LLMController, MissionOut, ProposeOut, VoteOut, BeliefEntry,
)
from resistance.engine import GameEngine, SeatConfig
from resistance.events import EventType
from resistance.personality import PRESETS
from resistance.state import Role
from resistance.views import build_seat_view


class FakeClient:
    """Returns valid (or first-time invalid) outputs and records every call."""

    model = "fake"

    def __init__(self, bad_first_team=False):
        self.calls = []
        self.bad_first_team = bad_first_team

    def complete(self, *, system, user, schema):
        self.calls.append({"system": system, "user": user, "schema": schema})
        beliefs = [BeliefEntry(seat=s, suspicion=0.5, reason="hmm") for s in range(5)]
        if schema is ProposeOut:
            team = [99] if self.bad_first_team and len(self.calls) == 1 else [0, 1]
            out = ProposeOut(reasoning="r", speech="s", team=team, beliefs=beliefs)
        elif schema is DiscussOut:
            out = DiscussOut(reasoning="r", speech="I trust nobody.", beliefs=beliefs)
        elif schema is VoteOut:
            out = VoteOut(reasoning="r", approve=True, beliefs=beliefs)
        elif schema is MissionOut:
            out = MissionOut(reasoning="r", play_success=True)
        else:
            raise AssertionError(schema)
        return out, {"model": self.model, "output": out.model_dump()}


def _engine_with_fake_agents(client):
    seats = [
        SeatConfig(name=PRESETS[i].name,
                   controller=LLMController(i, PRESETS[i], client))
        for i in range(5)
    ]
    return GameEngine(seats, seed=3)


def test_full_game_with_fake_llm_agents():
    client = FakeClient()
    engine = _engine_with_fake_agents(client)
    events = []
    engine.listeners.append(events.append)
    state = engine.run()
    assert state.winner == Role.RESISTANCE  # spies always play success here
    assert any(e["type"] == EventType.LLM_CALL for e in events)
    assert any(e["type"] == EventType.SPEECH for e in events)
    # Thought events carry the agent's beliefs, excluding itself.
    thoughts = [e for e in events if e["type"] == EventType.THOUGHT]
    assert thoughts
    for e in thoughts:
        assert e["agent"] not in e.get("beliefs", {})


def test_invalid_team_triggers_retry_with_correction():
    client = FakeClient(bad_first_team=True)
    engine = _engine_with_fake_agents(client)
    engine._assign_roles()
    team = engine._propose()
    assert sorted(team) == [0, 1]
    propose_calls = [c for c in client.calls if c["schema"] is ProposeOut]
    assert len(propose_calls) == 2
    assert "CORRECTION NEEDED" in propose_calls[1]["user"]


def test_system_prompt_role_briefs():
    client = FakeClient()
    engine = _engine_with_fake_agents(client)
    engine._assign_roles()
    spies = engine.state.spies()
    for seat in range(5):
        controller = engine.seats[seat].controller
        view = build_seat_view(engine.state, seat, [], None)
        system = controller._system_prompt(view)
        if seat in spies:
            assert "You are a SPY" in system
            partner = next(s for s in spies if s != seat)
            assert engine.state.player(partner).name in system
        else:
            assert "You are RESISTANCE" in system
            # Resistance system prompts must not name the spies.
            assert "fellow spy" not in system.lower()
