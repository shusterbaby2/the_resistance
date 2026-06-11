from conftest import ScriptableController, make_engine

from resistance.agents.scripted import RandomController
from resistance.engine import GameEngine, SeatConfig
from resistance.events import EventType
from resistance.state import Role


def test_spies_always_fail_means_spy_win():
    engine = make_engine(lambda i: ScriptableController(spy_plays_success=False))
    state = engine.run()
    assert state.winner == Role.SPY
    assert state.fails() == 3


def test_clean_teams_mean_resistance_win():
    # Spies cooperate (always play success) -> three successes.
    engine = make_engine(lambda i: ScriptableController(spy_plays_success=True))
    state = engine.run()
    assert state.winner == Role.RESISTANCE
    assert state.successes() == 3


def test_five_rejections_hand_spies_the_game():
    engine = make_engine(lambda i: ScriptableController(vote=False))
    events = []
    engine.listeners.append(events.append)
    state = engine.run()
    assert state.winner == Role.SPY
    vote_events = [e for e in events if e["type"] == EventType.TEAM_VOTE]
    assert len(vote_events) == 5
    assert [e["attempt"] for e in vote_events] == [1, 2, 3, 4, 5]
    end = events[-1]
    assert end["type"] == EventType.GAME_END
    assert end["winner"] == "spies"
    assert end["reason"] == "five_rejections"


def test_leader_rotates_after_every_proposal():
    events = []
    engine = make_engine(lambda i: ScriptableController(vote=False))
    engine.listeners.append(events.append)
    engine.run()
    seat_of = {}
    for e in events:
        if e["type"] == EventType.GAME_START:
            seat_of = {p["id"]: p["seat"] for p in e["players"]}
    leaders = [seat_of[e["leader"]] for e in events
               if e["type"] == EventType.PROPOSAL]
    for a, b in zip(leaders, leaders[1:]):
        assert b == (a + 1) % 5


def test_resistance_cards_are_always_success():
    events = []
    engine = make_engine(lambda i: ScriptableController(spy_plays_success=False))
    engine.listeners.append(events.append)
    state = engine.run()
    role_of = {engine.ids[p.seat]: p.role for p in state.players}
    for e in events:
        if e["type"] == EventType.MISSION:
            for card in e["cards"]:
                if role_of[card["player"]] == Role.RESISTANCE:
                    assert card["card"] == "success"


def test_invalid_team_is_corrected_by_engine():
    def bad_team(view):
        return [0, 0, 99]  # wrong size after dedupe + out-of-range seat

    events = []
    engine = make_engine(
        lambda i: ScriptableController(team_picker=bad_team, spy_plays_success=True))
    engine.listeners.append(events.append)
    state = engine.run()
    assert state.winner is not None
    assert any(e["type"] == EventType.ENGINE_NOTE for e in events)
    for e in events:
        if e["type"] == EventType.PROPOSAL:
            assert len(e["team"]) == len(set(e["team"]))


def test_scripted_game_is_deterministic():
    def run(seed):
        events = []
        seats = [SeatConfig(name=f"Bot{i}", controller=RandomController(i, seed))
                 for i in range(5)]
        GameEngine(seats, seed=seed, listeners=[events.append]).run()
        return events

    assert run(7) == run(7)
    # Different seeds should diverge (sanity check that rng is actually used).
    assert run(7) != run(8)


def test_full_scripted_game_terminates_with_winner():
    for seed in range(20):
        seats = [SeatConfig(name=f"Bot{i}", controller=RandomController(i, seed))
                 for i in range(5)]
        state = GameEngine(seats, seed=seed).run()
        assert state.winner in (Role.SPY, Role.RESISTANCE)
