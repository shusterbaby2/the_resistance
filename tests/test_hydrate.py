from pathlib import Path

from conftest import ScriptableController, make_engine

from resistance.eventlog import JsonlEventLog, load_events
from resistance.events import EventType
from resistance.hydrate import (
    HydrateError,
    events_through_game_end,
    hydrate_for_debrief,
    run_debrief_from_log,
)


def _finished_log_without_debrief(tmp_path: Path) -> Path:
    path = tmp_path / "game.jsonl"
    log = JsonlEventLog(path)
    engine = make_engine(lambda i: ScriptableController(spy_plays_success=True),
                         listeners=[log])
    engine.run()
    log.close()
    events = load_events(path)
    core, end_idx = events_through_game_end(events)
    trimmed = core  # game_end only, strip debriefs
    path.write_text(
        "\n".join(__import__("json").dumps(e, ensure_ascii=False) for e in trimmed)
        + "\n",
        encoding="utf-8",
    )
    return path


def test_hydrate_rebuilds_finished_state(tmp_path):
    path = _finished_log_without_debrief(tmp_path)
    events = load_events(path)
    state, transcript, beliefs, ids, next_seq = hydrate_for_debrief(events)
    assert state.winner is not None
    assert len(state.missions) == 3
    assert len(ids) == 5
    assert next_seq == len(events) - 1 + 1  # after game_end line


def test_debrief_from_log_appends_events(tmp_path):
    path = _finished_log_without_debrief(tmp_path)
    from resistance.agents.scripted import RandomController
    from resistance.engine import SeatConfig

    events = load_events(path)
    seats = [
        SeatConfig(name=p["name"], controller=RandomController(i, 7))
        for i, p in enumerate(sorted(events[0]["players"], key=lambda x: x["seat"]))
    ]
    new = run_debrief_from_log(path, seats)
    assert sum(1 for e in new if e["type"] == EventType.DEBRIEF) == 5
    assert sum(1 for e in new if e["type"] == EventType.TURN_START) == 5


def test_hydrate_requires_game_end(tmp_path):
  path = tmp_path / "partial.jsonl"
  path.write_text('{"t":0,"type":"game_start","players":[],"roles":{}}\n')
  with __import__("pytest").raises(HydrateError):
      hydrate_for_debrief(load_events(path))
