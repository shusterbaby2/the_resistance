"""WebHumanController: browser responses map to legal AgentOutputs."""

from conftest import ScriptableController, make_engine

from resistance.agents.base import Action
from resistance.cli import WebHumanController
from resistance.state import Role
from resistance.views import build_seat_view


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.request = None
        self.hand = None

    def request_action(self, request):
        self.request = request
        return self.response

    def set_hand(self, raised):
        self.hand = raised


def _view(seat=0):
    engine = make_engine(lambda i: ScriptableController())
    engine._assign_roles()
    return engine.state, build_seat_view(engine.state, seat, [], None)


def test_discuss_request_and_response():
    session = FakeSession({"speech": "  Vex is dirty.  "})
    _, view = _view()
    out = WebHumanController(session).act(view, Action.DISCUSS)
    assert out.speech == "Vex is dirty."
    assert session.hand is False  # taking the floor lowers a raised hand
    assert session.request["action"] == "discuss"
    assert session.request["teamSize"] == view.team_size
    assert len(session.request["players"]) == 5


def test_vote_maps_approve_flag():
    _, view = _view()
    assert WebHumanController(FakeSession({"approve": False})).act(
        view, Action.VOTE).vote is False
    assert WebHumanController(FakeSession({})).act(
        view, Action.VOTE).vote is True  # missing answer defaults to approve


def test_propose_valid_and_invalid_team():
    _, view = _view()
    out = WebHumanController(FakeSession({"team": [1, 0], "speech": "us two"}))\
        .act(view, Action.PROPOSE)
    assert out.team == [0, 1]
    assert out.speech == "us two"
    # Wrong size degrades to None -> engine's invalid-team correction.
    out = WebHumanController(FakeSession({"team": [0, 0, 99]}))\
        .act(view, Action.PROPOSE)
    assert out.team is None


def test_reconsider_submit_float_and_bad_team_fallback():
    _, view = _view()
    out = WebHumanController(FakeSession({"submit": True})).act(
        view, Action.RECONSIDER)
    assert out.submit is True
    out = WebHumanController(FakeSession({"submit": False, "team": [2, 3]}))\
        .act(view, Action.RECONSIDER)
    assert out.submit is False and out.team == [2, 3]
    # Floating with a broken team falls back to submitting.
    out = WebHumanController(FakeSession({"submit": False, "team": ["x"]}))\
        .act(view, Action.RECONSIDER)
    assert out.submit is True


def test_mission_card_only_counts_for_spies():
    state, _ = _view()
    spy = state.spies()[0]
    res = next(p.seat for p in state.players if p.role == Role.RESISTANCE)
    spy_view = build_seat_view(state, spy, [], None)
    res_view = build_seat_view(state, res, [], None)
    ctl = WebHumanController(FakeSession({"playSuccess": False}))
    assert ctl.act(spy_view, Action.MISSION).mission_success is False
    assert ctl.act(res_view, Action.MISSION).mission_success is True
    assert ctl._request(spy_view, Action.MISSION)["isSpy"] is True


def test_debrief_fields_map_through():
    _, view = _view()
    out = WebHumanController(FakeSession({
        "strategy": "s", "best_move": "b", "mistake": "", "confusion": "c",
    })).act(view, Action.DEBRIEF)
    assert (out.strategy, out.best_move, out.mistake, out.confusion) == \
        ("s", "b", "", "c")
