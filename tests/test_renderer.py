"""Blind vs omniscient rendering: hiding is the renderer's job."""

import time

from conftest import ScriptableController, make_engine

from resistance.agents.base import Action
from resistance.cli import ConsoleRenderer, HumanController, PacedRenderer
from resistance.views import build_seat_view


def _events():
    engine = make_engine(lambda i: ScriptableController(spy_plays_success=False))
    events = []
    engine.listeners.append(events.append)
    engine.run()
    return events


def _render(events, **kwargs):
    renderer = ConsoleRenderer(color=False, **kwargs)
    for e in events:
        renderer(e)


def test_blind_view_hides_thoughts_roles_and_cards(capsys):
    events = _events()
    _render(events, human=False, reveal=False)
    out = capsys.readouterr().out
    body = out.rsplit("===", 2)[0]  # everything before the game-end reveal
    assert "thinks:" not in body
    assert "[card]" not in body
    assert "[role]" not in body
    assert "SPY" not in body and "RESISTANCE" not in body.replace(
        "THE RESISTANCE", "")


def test_omniscient_view_shows_interior(capsys):
    events = _events()
    _render(events, human=False, reveal=True)
    out = capsys.readouterr().out
    assert "thinks:" in out
    assert "[card]" in out
    assert "[role]" in out


def test_human_view_shows_own_role_only(capsys):
    events = _events()
    # Mark seat 0 as the human in the game_start event.
    events[0]["players"][0]["isHuman"] = True
    _render(events, human=True, reveal=False)
    out = capsys.readouterr().out
    assert ">>> Your secret role:" in out
    assert "thinks:" not in out.rsplit("===", 2)[0]


def test_game_end_reveals_roles_in_all_modes(capsys):
    events = _events()
    _render(events, human=False, reveal=False)
    out = capsys.readouterr().out
    assert "Roles:" in out


class _Recorder:
    reveal = False

    def __init__(self):
        self.seen = []
        self.times = []

    def __call__(self, e):
        self.seen.append(e)
        self.times.append(time.monotonic())


def test_paced_renderer_draws_everything_in_order():
    events = _events()
    recorder = _Recorder()
    pacer = PacedRenderer(recorder, scale=0.0)
    for e in events:
        pacer(e)
    pacer.close()
    assert recorder.seen == events


def test_paced_renderer_gap_policy():
    renderer = ConsoleRenderer(color=False, reveal=False)
    pacer = PacedRenderer(renderer, scale=0.0)
    try:
        # Long speeches are capped, status beats draw immediately.
        assert pacer._gap({"type": "speech", "text": "x" * 1000}) == 3.5
        assert pacer._gap({"type": "turn_start", "action": "vote"}) == 0.0
        assert pacer._gap({"type": "llm_call"}) == 0.0
        # Thoughts pace only when they are actually drawn (reveal mode).
        assert pacer._gap({"type": "thought", "text": "hidden"}) == 0.0
        renderer.reveal = True
        assert pacer._gap({"type": "thought", "text": "hidden"}) > 0.0
    finally:
        pacer.close()


def test_paced_renderer_enforces_minimum_gap_between_beats():
    recorder = _Recorder()
    pacer = PacedRenderer(recorder, scale=0.25)  # speech base 0.4s -> 0.1s gap
    pacer({"type": "speech", "text": ""})
    pacer({"type": "speech", "text": ""})
    pacer.close()
    assert recorder.times[1] - recorder.times[0] >= 0.05


def test_human_controller_syncs_display_before_prompting(monkeypatch):
    calls = []
    controller = HumanController(sync=lambda: calls.append("sync"))
    monkeypatch.setattr("builtins.input",
                        lambda prompt="": calls.append("input") or "")
    engine = make_engine(lambda i: ScriptableController())
    engine._assign_roles()
    view = build_seat_view(engine.state, 0, [], None)
    out = controller.act(view, Action.DISCUSS)
    assert out.speech == ""
    assert calls and calls[0] == "sync"  # display catches up before the prompt
