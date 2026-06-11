"""Blind vs omniscient rendering: hiding is the renderer's job."""

from conftest import ScriptableController, make_engine

from resistance.cli import ConsoleRenderer


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
