"""Event stream — the contract between the engine and every renderer.

The authoritative schema is `resistance_ui/resistance-event-schema.md` (v1).
Events are plain JSON-able dicts with a `t` sequence index, a `type`, and a
`round` on in-round events. One game = one append-only .jsonl file; renderers
fold events[0..playhead] into state and never mutate.

Engine-only extras (`llm_call`, `engine_note`) are additional event types that
schema-v1 renderers skip in their fold; they exist for replay/analysis.
"""

from typing import Any

Event = dict[str, Any]


class EventType:
    # schema v1
    GAME_START = "game_start"
    ROUND_START = "round_start"
    TURN_START = "turn_start"  # status: a seat began deciding; powers "X is thinking…"
    SUGGESTION = "suggestion"  # leader floats a team for discussion (not yet voted)
    PROPOSAL = "proposal"
    THOUGHT = "thought"  # interior: private reasoning + beliefs; hidden in Blind mode
    SPEECH = "speech"  # public: what a human at the table hears
    TEAM_VOTE = "team_vote"
    MISSION = "mission"
    ROUND_END = "round_end"
    GAME_END = "game_end"
    DEBRIEF = "debrief"  # post-game: each seat's public reflection
    # engine extras (ignored by schema-v1 renderers)
    LLM_CALL = "llm_call"  # raw model record per agent turn
    ENGINE_NOTE = "engine_note"  # e.g. invalid action corrected
