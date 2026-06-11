# The Resistance — AI Edition

One human plays 5-player [The Resistance](https://en.wikipedia.org/wiki/The_Resistance_(game))
against four Claude-powered agents that bluff, deduce, accuse, and lie — each with its own
personality. The human is just another seat: roles are random, so some games *you* are a spy
trying to fool the AI.

Phase 1 (this repo today): the complete text game loop in the terminal, with a structured
event log as the observability backbone. Phase 2: mechanical speaking-bid orchestrator and a
web UI rendered over the event stream. Phase 3: voice. See `CLAUDE.md` for the architecture
contract and `AI Resistance PRD.md` for the product spec.

## Setup

```sh
uv sync
cp .env.example .env   # add your ANTHROPIC_API_KEY (not needed for --offline)
```

## Play

```sh
uv run resistance watch --web          # spectate live in the browser (recommended)
uv run resistance play --web           # you + 4 Claude agents, live blind web view
uv run resistance watch --reveal       # terminal spectate, reasoning shown
uv run resistance watch --offline      # scripted agents, no API key, instant
uv run resistance replay logs/<file>.jsonl --reveal
open resistance_ui/resistance-replayer.html   # web replayer: load any logs/*.jsonl
```

`--web` starts a tiny local server, opens the browser, and the page follows the game
live — including a pulsing "X is thinking…" indicator while a model call is in flight,
so silences are visibly thinking time. `play --web` opens in Blind mode (no spoilers);
`watch --web` opens omniscient. Scrub backward any time to rewind; press ⏭ to resume
following.

The web replayer is the main instrument: scrub through a game, flip
**Omniscient ⇄ Blind** to A/B what the agents were thinking against what a human at the
table would hear, and watch the suspicion matrix converge. The engine emits the event
schema in `resistance_ui/resistance-event-schema.md`; every renderer is a consumer of the
same `.jsonl` stream. Per-call model latency is recorded on `llm_call` events
(`duration_ms`) and shown in the terminal with `--reveal`.

Useful flags: `--seed N` (reproducible setup), `--model claude-sonnet-4-6` (cheaper/faster
agents), `--effort low|medium|high` (agent thinking depth vs latency; default medium).

**About slow turns:** a silent stretch is one agent's model call — proposals are the
longest since they're the most open-ended decision over the largest context, and the SDK
also waits and retries silently on API rate limits. The live web view shows a counting
timer on the "X is thinking…" row, and each thought row shows that turn's model latency
(e.g. `42.0s`) in Omniscient mode. If turns drag: `--effort low` is the biggest lever,
then `--model claude-sonnet-4-6`.

## How it works

- `engine.py` runs the state machine (propose → discuss → vote → mission) and emits one
  structured event per turn: public events (what the table sees), private events (your
  role), and log events (each agent's hidden reasoning, suspicion vector, and raw LLM
  output).
- Every game writes `logs/*.jsonl`. `resistance replay --reveal` re-renders a recorded game
  — including every lie's private justification — without re-running any model.
- Agents act through one interface: structured game state + transcript in,
  `{reasoning, speech, beliefs, action}` out. The Claude adapter is ~50 lines; any other
  provider is one new adapter.

## Develop

```sh
uv run pytest    # full suite runs offline, no API key
```
