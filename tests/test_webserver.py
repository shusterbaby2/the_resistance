import json
import threading
import time
import urllib.request

from resistance.webserver import LiveSession, live_url, start_server


def _get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}") as r:
        return json.loads(r.read().decode())


def _post(port, path, payload):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode())


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


def test_hand_endpoint_sets_and_clears_session_flag(tmp_path):
    server, session = start_server(tmp_path, lobby={})
    try:
        port = server.server_address[1]
        assert _get(port, "/api/live/hand") == {"raised": False}
        assert _post(port, "/api/live/hand", {"raised": True}) == \
            {"ok": True, "raised": True}
        assert session.hand_raised() is True
        session.set_hand(False)  # the controller lowers it on the discuss slot
        assert _get(port, "/api/live/hand") == {"raised": False}
    finally:
        server.shutdown()


def test_action_channel_roundtrip(tmp_path):
    server, session = start_server(tmp_path, lobby={})
    try:
        port = server.server_address[1]
        assert _get(port, "/api/live/action") == {}  # nothing pending

        result = {}

        def controller():
            result["resp"] = session.request_action({"action": "vote", "seat": 0})

        thread = threading.Thread(target=controller)
        thread.start()
        pending = {}
        for _ in range(200):  # wait for the request to publish
            pending = _get(port, "/api/live/action")
            if pending:
                break
            time.sleep(0.01)
        assert pending["action"] == "vote"
        assert pending["id"] == 1

        # A stale/wrong id never unblocks the controller.
        assert _post(port, "/api/live/action", {"id": 999, "approve": True}) == {"ok": False}
        assert thread.is_alive()

        assert _post(port, "/api/live/action",
                     {"id": pending["id"], "approve": False}) == {"ok": True}
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert result["resp"]["approve"] is False
        assert _get(port, "/api/live/action") == {}  # cleared after answering
    finally:
        server.shutdown()
