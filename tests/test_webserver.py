import json
import urllib.request

from resistance.webserver import LiveSession, live_url, start_server


def test_serves_files_uncached(tmp_path):
    log = tmp_path / "logs" / "game.jsonl"
    log.parent.mkdir()
    log.write_text(json.dumps({"t": 0, "type": "game_start"}) + "\n")
    server, _ = start_server(tmp_path)
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/logs/game.jsonl") as r:
            assert r.status == 200
            assert r.headers["Cache-Control"] == "no-store"
            first = r.read().decode()
        # The live view depends on seeing appended events on re-fetch.
        log.write_text(first + json.dumps({"t": 1, "type": "round_start"}) + "\n")
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/logs/game.jsonl") as r:
            assert len(r.read().decode().splitlines()) == 2
    finally:
        server.shutdown()


def test_live_url_shape(tmp_path):
    server, _ = start_server(tmp_path)
    try:
        from pathlib import Path

        url = live_url(server, Path("logs/x.jsonl"), blind=True)
        assert "resistance-replayer.html?live=/logs/x.jsonl" in url
        assert "blind=1" in url and "hideroles=1" in url
        assert "blind" not in live_url(server, Path("logs/x.jsonl"))
    finally:
        server.shutdown()


def test_live_lobby_and_start(tmp_path):
    lobby = {"seed": 42, "command": "watch", "seats": [{"seat": 0, "preset": 0}]}
    server, session = start_server(tmp_path, lobby=lobby)
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/live/lobby") as r:
            assert json.loads(r.read().decode()) == lobby
        assert not session._start_event.is_set()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/live/start",
            data=json.dumps({"presets": [1, 2, 3, 4, 0]}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as r:
            assert json.loads(r.read().decode()) == {"ok": True}
        assert session.wait_for_start() == {"presets": [1, 2, 3, 4, 0]}
    finally:
        server.shutdown()


def test_live_session_wait_unblocks():
    session = LiveSession(lobby={})
    session.signal_start({"presets": [0, 1, 2, 3, 4]})
    assert session.wait_for_start() == {"presets": [0, 1, 2, 3, 4]}
