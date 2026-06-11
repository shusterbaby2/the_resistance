"""LLM agent wiring tests with a fake client — no API calls."""

from resistance.agents.base import Action
from resistance.agents.llm_agent import (
    DebriefOut, DiscussOut, LLMController, MissionOut, ProposeOut, ReconsiderOut,
    VoteOut, BeliefEntry,
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

    def complete(self, *, system, user, schema, thinking=False):
        self.calls.append({"system": system, "user": user, "schema": schema,
                           "thinking": thinking})
        beliefs = [BeliefEntry(seat=s, suspicion=0.5, reason="hmm") for s in range(5)]
        if schema is ProposeOut:
            team = [99] if self.bad_first_team and len(self.calls) == 1 else [0, 1]
            out = ProposeOut(reasoning="r", speech="s", team=team, beliefs=beliefs)
        elif schema is DiscussOut:
            out = DiscussOut(reasoning="r", speech="I trust nobody.", beliefs=beliefs)
        elif schema is VoteOut:
            out = VoteOut(reasoning="r", approve=True, beliefs=beliefs)
        elif schema is ReconsiderOut:
            out = ReconsiderOut(reasoning="r", speech="s", submit=True, beliefs=beliefs)
        elif schema is MissionOut:
            out = MissionOut(reasoning="r", play_success=True)
        elif schema is DebriefOut:
            out = DebriefOut(
                reasoning="r",
                strategy="played tight",
                best_move="held a reject",
                mistake="",
                confusion="the vote math",
            )
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


def test_thinking_only_on_high_stakes_actions():
    # Discussion/votes/debrief carry chain-of-thought in the `reasoning` field;
    # extended thinking is requested only for team choices and mission cards.
    client = FakeClient()
    engine = _engine_with_fake_agents(client)
    engine.run()
    schemas_seen = {c["schema"] for c in client.calls}
    assert {ProposeOut, DiscussOut, VoteOut} <= schemas_seen
    for call in client.calls:
        expected = call["schema"] in (ProposeOut, ReconsiderOut, MissionOut)
        assert call["thinking"] is expected, call["schema"]


def test_parse_error_retries_then_succeeds():
    client = FakeClient()

    def flaky_complete(*, system, user, schema, thinking=False):
        if len(client.calls) == 0:
            client.calls.append({"system": system, "user": user, "schema": schema})
            raise ValueError(
                "Invalid JSON: EOF while parsing a string at line 1 column 682"
            )
        return FakeClient.complete(client, system=system, user=user, schema=schema,
                                   thinking=thinking)

    client.complete = flaky_complete  # type: ignore[method-assign]
    engine = _engine_with_fake_agents(client)
    engine._assign_roles()
    out = engine._act(1, Action.DISCUSS)
    assert out.speech
    assert len(client.calls) == 2
    assert "CORRECTION NEEDED" in client.calls[1]["user"]


def test_parse_error_falls_back_to_scripted_agent():
    class BrokenClient:
        model = "broken"

        def complete(self, *, system, user, schema, thinking=False):
            raise ValueError(
                "Invalid JSON: EOF while parsing a string at line 1 column 682"
            )

    engine = _engine_with_fake_agents(BrokenClient())
    engine._assign_roles()
    out = engine._act(1, Action.DISCUSS)
    assert out.meta.get("fallback") == "unparseable_output"
    assert len(out.meta["llm_calls"]) == 2
    assert all("error" in r for r in out.meta["llm_calls"])


def test_invalid_team_triggers_retry_with_correction():
    client = FakeClient(bad_first_team=True)
    engine = _engine_with_fake_agents(client)
    engine._assign_roles()
    out = engine._act(0, Action.PROPOSE)
    team = engine._validated_team(0, out.team)
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
