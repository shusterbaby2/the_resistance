from conftest import ScriptableController, make_engine

from resistance import rules
from resistance.agents.base import Action, AgentOutput, Controller
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


class AlternatingReconsiderController(Controller):
    """Floats two suggestions, then submits on the third."""

    def __init__(self, seat: int):
        self.seat = seat
        self.reconsiders = 0

    def act(self, view, action):
        if action == Action.PROPOSE:
            team = sorted(p.seat for p in view.players)[: view.team_size]
            return AgentOutput(team=team, reasoning="test")
        if action == Action.RECONSIDER:
            self.reconsiders += 1
            if self.reconsiders == 1:
                others = [p.seat for p in view.players if p.seat != view.seat]
                return AgentOutput(
                    submit=False,
                    team=sorted([view.seat] + others[: view.team_size - 1]),
                    reasoning="test",
                )
            return AgentOutput(submit=True, reasoning="test")
        if action == Action.DISCUSS:
            return AgentOutput(reasoning="test")
        if action == Action.VOTE:
            return AgentOutput(vote=True, reasoning="test")
        if action == Action.MISSION:
            return AgentOutput(mission_success=True, reasoning="test")
        raise ValueError(action)


def test_suggestion_loop_emits_before_proposal():
    events = []
    engine = make_engine(lambda i: AlternatingReconsiderController(i), seed=1)
    engine.listeners.append(events.append)
    engine.run()
    suggestions = [e for e in events if e["type"] == EventType.SUGGESTION]
    proposals = [e for e in events if e["type"] == EventType.PROPOSAL]
    assert suggestions
    first_vote = next(i for i, e in enumerate(events) if e["type"] == EventType.TEAM_VOTE)
    first_proposal = next(i for i, e in enumerate(events) if e["type"] == EventType.PROPOSAL)
    first_suggestion = next(i for i, e in enumerate(events) if e["type"] == EventType.SUGGESTION)
    assert first_suggestion < first_proposal < first_vote
    assert suggestions[0]["suggestion"] == 1
    assert any(e["suggestion"] == 2 for e in suggestions)


def test_third_suggestion_auto_submits_without_reconsider():
    class AlwaysAlternateController(Controller):
        def act(self, view, action):
            if action == Action.PROPOSE:
                return AgentOutput(team=[0, 1], reasoning="test")
            if action == Action.RECONSIDER:
                return AgentOutput(
                    submit=False,
                    team=[0, 2],
                    reasoning="test",
                )
            if action == Action.DISCUSS:
                return AgentOutput(reasoning="test")
            if action == Action.VOTE:
                return AgentOutput(vote=True, reasoning="test")
            if action == Action.MISSION:
                return AgentOutput(mission_success=True, reasoning="test")
            raise ValueError(action)

    events = []
    engine = make_engine(lambda i: AlwaysAlternateController(), seed=2)
    engine.listeners.append(events.append)
    engine.run()
    first_vote_idx = next(i for i, e in enumerate(events) if e["type"] == EventType.TEAM_VOTE)
    slice_ = events[:first_vote_idx]
    suggestions = [e for e in slice_ if e["type"] == EventType.SUGGESTION]
    reconsiders = [e for e in slice_ if e["type"] == EventType.TURN_START
                   and e.get("action") == Action.RECONSIDER.value]
    assert len(suggestions) == rules.MAX_SUGGESTIONS
    assert len(reconsiders) == rules.MAX_SUGGESTIONS - 1
    proposal = next(e for e in slice_ if e["type"] == EventType.PROPOSAL)
    assert proposal["team"] == suggestions[-1]["team"]


def test_full_scripted_game_terminates_with_winner():
    for seed in range(20):
        seats = [SeatConfig(name=f"Bot{i}", controller=RandomController(i, seed))
                 for i in range(5)]
        state = GameEngine(seats, seed=seed).run()
        assert state.winner in (Role.SPY, Role.RESISTANCE)
