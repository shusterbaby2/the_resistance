from conftest import ScriptableController, make_engine

from resistance.eventlog import JsonlEventLog, load_events
from resistance.replay import replay


def test_log_round_trips_and_replays(tmp_path):
    path = tmp_path / "game.jsonl"
    log = JsonlEventLog(path)
    engine = make_engine(lambda i: ScriptableController(spy_plays_success=True),
                         listeners=[log])
    live = []
    engine.listeners.append(live.append)
    engine.run()
    log.close()

    loaded = load_events(path)
    assert loaded == live

    rendered = []
    replay(path, rendered.append)
    assert rendered == live
    assert rendered[0]["type"] == "game_start"
    assert rendered[-1]["type"] == "debrief"
