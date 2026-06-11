"""Tiny local HTTP server for the live web view.

Serves the project directory (replayer page + logs/) so the browser can poll
the growing .jsonl while a game runs. No game logic, no state — the replayer
remains a pure consumer of the event log; this just makes the file reachable.
"""

import functools
import http.server
import threading
from pathlib import Path


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:  # keep game output clean
        pass

    def end_headers(self) -> None:
        # The live view re-fetches the log; never let the browser cache it.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def start_server(root: str | Path, port: int = 0) -> http.server.ThreadingHTTPServer:
    """Serve `root` on localhost in a daemon thread. Returns the server;
    the bound port is server.server_address[1]."""
    handler = functools.partial(_QuietHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def live_url(server: http.server.ThreadingHTTPServer, log_path: Path,
             blind: bool = False) -> str:
    port = server.server_address[1]
    params = f"?live=/{log_path.as_posix()}"
    if blind:
        params += "&blind=1&hideroles=1"
    return (f"http://127.0.0.1:{port}/resistance_ui/"
            f"resistance-replayer.html{params}")
