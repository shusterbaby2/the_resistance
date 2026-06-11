"""Knowledge-boundary tests.

The agent-facing boundary lives in views.py (what each agent may know).
The event log intentionally contains everything; hiding is a renderer concern
(Blind mode), tested in test_renderer.py.
"""

from conftest import ScriptableController, make_engine

from resistance.events import EventType
from resistance.state import Role
from resistance.views import build_seat_view


def _finished_engine():
    engine = make_engine(lambda i: ScriptableController(spy_plays_success=True))
    events = []
    engine.listeners.append(events.append)
    engine.run()
    return engine, events


def test_spies_see_each_other_resistance_sees_nothing():
    engine, _ = _finished_engine()
    state = engine.state
    spies = set(state.spies())
    for p in state.players:
        view = build_seat_view(state, p.seat, engine.transcript, None)
        if p.role == Role.SPY:
            assert set(view.fellow_spies) == spies - {p.seat}
        else:
            assert view.fellow_spies == []


def test_view_never_contains_other_roles():
    engine, _ = _finished_engine()
    state = engine.state
    for p in state.players:
        view = build_seat_view(state, p.seat, engine.transcript, None)
        dumped = view.model_dump_json()
        for other in state.players:
            if other.seat == p.seat:
                continue
            assert f'"seat":{other.seat},"role"' not in dumped.replace(" ", "")


def test_thoughts_belong_to_the_acting_agent_only():
    engine, events = _finished_engine()
    ids = set(engine.ids)
    for e in events:
        if e["type"] == EventType.THOUGHT:
            assert e["agent"] in ids
            # An agent's beliefs never include itself, and are its own only.
            for target in e.get("beliefs", {}):
                assert target != e["agent"]
                assert target in ids


def test_beliefs_are_per_seat_and_unshared():
    engine = make_engine(lambda i: ScriptableController(spy_plays_success=True))
    engine.run()
    state = engine.state
    for seat in range(5):
        view = build_seat_view(state, seat, engine.transcript,
                               engine.beliefs.get(seat))
        if view.beliefs is not None:
            assert all(b.seat != seat for b in view.beliefs.entries)
