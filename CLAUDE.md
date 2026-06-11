# The Resistance — AI Edition

One human plays 5-player Resistance against LLM agents that bluff, deduce, and lie.
See `AI Resistance PRD.md` for the product spec. This file is the architecture contract —
every change must respect it.

## Locked decisions

- **5 players, base rules only.** 3 Resistance / 2 Spies, team sizes [2,3,2,3,3], majority
  vote, 5 rejected proposals in a round = spy win, any fail card fails a mission (no
  two-fails variant), 3 mission successes = resistance win / 3 fails = spy win.
  Do not build the variant table for other player counts.
- **The human is just another seat.** Random role assignment — the human is a spy ~40% of
  the time. The engine never special-cases the human except at the I/O boundary
  (`Controller` implementations). AI resistance must be able to win against a human spy.
- **Observability is a stream, not screens.** The game is a state machine that emits one
  structured event per beat (private reasoning, public speech, beliefs, raw LLM outputs).
  UIs are disposable renderers over the event log; the log is not.
  **The renderer contract is `resistance_ui/resistance-event-schema.md` (v1)** — the
  engine emits that schema natively, `tests/test_schema.py` enforces it, and both the
  terminal renderer and `resistance_ui/resistance-replayer.html` consume the same .jsonl.
  Change the schema doc + tests before changing emitted events.
- **Text first, voice later.** Agent speech is plain text a TTS layer can consume later.
  Web UI (FastAPI + browser renderer over the event stream) comes after the engine works.
- **Claude-powered agents behind a provider-agnostic interface.** One agent-turn shape:
  in = system prompt + structured state + transcript; out = {reasoning, speech,
  updated_beliefs, action}. Swapping providers or running different agents on different
  models must require only a new `LLMClient` implementation.

## The three do-nots (defaults to avoid)

1. **Don't compute the speaking bid with an LLM call.** When the bidding orchestrator
   lands (phase 2), bid = static personality desirability + mechanical situational
   modifiers (named/accused recently, on proposed team, is leader, anti-starvation,
   just-spoke decay) + noise. Only the bid *winner* gets an LLM call.
2. **Don't re-derive game state from the transcript.** Structured game state (teams,
   votes, mission outcomes) is maintained as data outside the model and fed to agents
   alongside the transcript. Each agent keeps a persisted beliefs object, updated lazily
   when the agent is activated.
3. **Don't give agents any shared state.** Private reasoning is per-agent and never read
   by anyone else — including a spy partner. No spy scratchpad. Spies coordinate only by
   watching public play.

## The one do-first

Round-robin discussion shipped before the bidding orchestrator. The bid mechanic is a
second pass on a working spine: assignment → suggestion loop → vote → mission →
win/loss. Per vote attempt the leader may float up to 3 teams for discussion;
the third auto-submits.

## Layout

- `src/resistance/rules.py` — 5-player constants and win conditions
- `src/resistance/state.py` — `GameState` (ground truth, never derived from transcript)
- `src/resistance/events.py` — schema-v1 event types (+ engine extras `llm_call`, `engine_note`)
- `resistance_ui/` — the schema doc (the contract) and the web replayer (Blind ⇄ Omniscient
  toggle, timeline scrubber, suspicion matrix); a static page that loads any game .jsonl
- `src/resistance/views.py` — per-seat filtered view (knowledge boundary lives here)
- `src/resistance/engine.py` — state machine; emits events; calls `Controller.act()`
- `src/resistance/agents/` — `Controller` ABC, scripted agents (tests/offline), LLM agent
- `src/resistance/llm/` — provider-agnostic `LLMClient` + Claude adapter
- `src/resistance/eventlog.py`, `replay.py` — JSONL log incl. raw model output; replay renders without re-running models
- `src/resistance/cli.py` — `resistance play|watch|replay`

## Commands

- `uv sync` — install
- `uv run pytest` — tests (scripted agents, no API key needed)
- `uv run resistance watch --offline` — all-AI scripted game, no API key
- `uv run resistance watch --reveal` — all-Claude game with reasoning shown
- `--web` on play/watch — live browser view (local server tails the .jsonl; play opens
  Blind, watch opens omniscient; `turn_start` events drive the "thinking…" indicator)
- `uv run resistance play` — human + 4 Claude agents (needs `ANTHROPIC_API_KEY` in `.env`)
- `uv run resistance replay logs/<file>.jsonl --reveal` — re-render a recorded game
- `open resistance_ui/resistance-replayer.html` — web replayer; load or drag-drop any
  `logs/*.jsonl`
