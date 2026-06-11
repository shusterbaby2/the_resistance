"""Tiny local HTTP server for the live web view.

Serves the project directory (replayer page + logs/) so the browser can poll
the growing .jsonl while a game runs. A small control API lets the browser
lobby gate game start and pass seat configuration back to the CLI.
"""

import functools
import http.server
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class LiveSession:
    """Shared between the CLI (waits) and the browser (signals start)."""

    lobby: dict[str, Any]
    _start_event: threading.Event = field(default_factory=threading.Event)
    start_payload: dict[str, Any] | None = None

    def wait_for_start(self) -> dict[str, Any]:
        self._start_event.wait()
        return self.start_payload or {}

    def signal_start(self, payload: dict[str, Any] | None = None) -> None:
        self.start_payload = payload or {}
        self._start_event.set()


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
  session: LiveSession | None = None

  def log_message(self, *args) -> None:  # keep game output clean
      pass

  def end_headers(self) -> None:
      # The live view re-fetches the log; never let the browser cache it.
      self.send_header("Cache-Control", "no-store")
      super().end_headers()

  def do_GET(self) -> None:
      if self.path.split("?", 1)[0] == "/api/live/lobby":
          self._json_response(self.session.lobby if self.session else {})
          return
      super().do_GET()

  def do_POST(self) -> None:
      if self.path.split("?", 1)[0] == "/api/live/start":
          if self.session is None:
              self.send_error(503, "no live session")
              return
          length = int(self.headers.get("Content-Length", 0))
          body = self.rfile.read(length) if length else b"{}"
          try:
              payload = json.loads(body.decode("utf-8") or "{}")
          except json.JSONDecodeError:
              self.send_error(400, "invalid JSON")
              return
          if not isinstance(payload, dict):
              self.send_error(400, "payload must be a JSON object")
              return
          self.session.signal_start(payload)
          self._json_response({"ok": True})
          return
      self.send_error(404)

  def _json_response(self, data: Any, status: int = 200) -> None:
      body = json.dumps(data).encode("utf-8")
      self.send_response(status)
      self.send_header("Content-Type", "application/json")
      self.send_header("Content-Length", str(len(body)))
      self.end_headers()
      self.wfile.write(body)


def _handler_class(directory: str, session: LiveSession | None) -> type[_QuietHandler]:
    class Handler(_QuietHandler):
        pass

    Handler.session = session
    return functools.partial(Handler, directory=directory)  # type: ignore[return-value]


def start_server(
    root: str | Path,
    port: int = 0,
    *,
    lobby: dict[str, Any] | None = None,
) -> tuple[http.server.ThreadingHTTPServer, LiveSession | None]:
    """Serve `root` on localhost in a daemon thread.

    When `lobby` is provided, the server also exposes /api/live/lobby and
    /api/live/start for the browser lobby. Returns (server, session).
    """
    session = LiveSession(lobby=lobby) if lobby is not None else None
    handler = _handler_class(str(root), session)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, session


def live_url(server: http.server.ThreadingHTTPServer, log_path: Path,
             blind: bool = False) -> str:
    port = server.server_address[1]
    params = f"?live=/{log_path.as_posix()}"
    if blind:
        params += "&blind=1&hideroles=1"
    return (f"http://127.0.0.1:{port}/resistance_ui/"
            f"resistance-replayer.html{params}")
