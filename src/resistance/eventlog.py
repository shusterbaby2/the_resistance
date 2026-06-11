"""JSONL event log — the durable artifact of every game.

One JSON object per line, in emission order, per the v1 schema
(resistance_ui/resistance-event-schema.md). This exact file is what the web
replayer loads.
"""

import json
from pathlib import Path

from .events import Event


class JsonlEventLog:
    """Engine listener that appends every event to disk."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("w", encoding="utf-8")

    def __call__(self, event: Event) -> None:
        self._file.write(json.dumps(event, ensure_ascii=False) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()


def load_events(path: str | Path) -> list[Event]:
    events = []
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events
