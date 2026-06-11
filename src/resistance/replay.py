"""Replay a recorded game from its event log — no model calls.

The log contains everything (public speech, private thoughts, beliefs, cards,
raw LLM records), so a recorded game can be re-rendered and audited offline.
The web replayer (resistance_ui/resistance-replayer.html) loads the same file.
"""

from pathlib import Path

from .events import Event
from .eventlog import load_events


def replay(path: str | Path, renderer) -> list[Event]:
    events = load_events(path)
    for event in events:
        renderer(event)
    return events
