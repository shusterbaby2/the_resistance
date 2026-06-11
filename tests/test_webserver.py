import json
import urllib.request

from resistance.webserver import live_url, start_server


def test_serves_files_uncached(tmp_path):
    log = tmp_path / "logs" / "game.jsonl"
    log.parent.mkdir()
    log.write_text(json.dumps({"t": 0, "type": "game_start"}) + "\n")
    server = start_server(tmp_path)
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
    server = start_server(tmp_path)
    try:
        from pathlib import Path

        url = live_url(server, Path("logs/x.jsonl"), blind=True)
        assert "resistance-replayer.html?live=/logs/x.jsonl" in url
        assert "blind=1" in url and "hideroles=1" in url
        assert "blind" not in live_url(server, Path("logs/x.jsonl"))
    finally:
        server.shutdown()
