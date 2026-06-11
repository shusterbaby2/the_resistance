# AI Resistance — Event Stream Schema (v1)

This is the contract between the **game engine** and any **renderer**. Lock this first; build everything else around it.

## The one idea

The engine never draws anything. It runs the game and **emits one structured event per beat** to an append-only stream. Everything that displays the game — the terminal printer, the web replayer, the live UI later — is just a *consumer* of that stream. This is what makes "move to web" cheap (it's a second consumer, not a rewrite) and what gives you deterministic replay for free (replay the file, don't re-run the model).

**Rule for Claude Code:** no game logic in any renderer, and no rendering in the engine. The only thing they share is this schema.

## File format

- One game = one `.jsonl` file. One JSON object per line, in emission order.
- The stream is the source of truth. To get the game state at any point, fold the events from the start up to that line. Renderers never mutate; they recompute state from `events[0..playhead]`.
- Append-only. Never rewrite earlier lines.

## Event envelope

Every event has:

| field  | type   | notes |
|--------|--------|-------|
| `t`    | int    | monotonic sequence index, 0-based. Convenience for scrubbing; file order is authoritative. |
| `type` | string | one of the types below. |
| `round`| int    | present on all in-round events. Omitted on `game_start` / `game_end`. |

Optional fields marked *(progressive)* below can be omitted by a minimal implementation; the renderer must treat them as absent, not error. Add them as the engine grows.

## Event types

### `game_start`
Sets up the board. Emitted once.
- `players`: `[{ id, name, seat }]` — `seat` is 0-based and fixes turn/color order.
- `roles`: `{ [playerId]: "resistance" | "spy" }` — full role map. Renderer hides this in Blind mode.
- `missionPlan`: `[{ round, size, failsToFail }]` — team size per round and how many fail cards sink the mission (`failsToFail` is 1 except mission 4 at 7+ players, where it's 2). At exactly 5 players it's always 1.
- `missionsToWin`: int — usually 3.

### `round_start`
- `leader`: playerId — current proposer.
- `missionSize`: int.
- `attempt`: int — 1..5. The 5th rejected proposal in a round ends the game for the spies.

### `suggestion`
Leader floated a team for table talk; not yet submitted to a vote.
- `leader`: playerId.
- `attempt`: int — which vote attempt within the round (1..5).
- `suggestion`: int — which float within this attempt (1..3).
- `team`: `[playerId]`.

### `proposal`
Leader locked a team in for the upcoming vote.
- `leader`: playerId.
- `attempt`: int.
- `team`: `[playerId]`.

### `turn_start`  *(progressive — status, not content)*
Emitted when a seat begins deciding, so renderers can show "X is thinking…" and
silences are attributable to model latency rather than bugs. Cleared by the next
non-`turn_start` event. Simultaneous decisions (`vote`, `mission`, `debrief`)
emit one `turn_start` per deciding seat back-to-back before any results — those
seats deliberate concurrently, so a renderer may show all of them as thinking.
- `agent`: playerId — **omitted for `action: "mission"`** so who is deliberating
  over a card stays anonymous.
- `action`: `"propose_team" | "reconsider" | "discuss" | "vote" | "mission" |
  "debrief"`.
- `round`: omitted for `action: "debrief"` (post-game, like `game_end`).

### `thought`  *(interior — never shown to other agents, hidden in Blind mode)*
- `agent`: playerId.
- `text`: string — private reasoning.
- `beliefs`: `{ [targetPlayerId]: number }` *(progressive)* — this agent's suspicion of each other player, 0..1. The renderer keeps the latest per agent and draws the suspicion matrix from it.
- `bid`: number *(progressive)* — the agent's speak-urge at this moment, for visualizing the orchestrator.
- `flags`: `[string]` *(progressive)* — e.g. `"sandbagging"`, `"intent_mismatch"`.

### `speech`  *(public — this is what a human at the table hears)*
- `agent`: playerId.
- `text`: string.
- `to`: playerId *(optional)* — addressee, if directed.
- `bid`: number *(progressive)*.
- `flags`: `[string]` *(progressive)* — deception markers, e.g. `"bluff"`. The renderer shows these as a "intent ≠ speech" badge and hides them in Blind mode.

### `team_vote`
Resistance votes are simultaneous, so emit one aggregate event.
- `attempt`: int.
- `votes`: `[{ player, vote: "approve" | "reject" }]`.
- `outcome`: `"approved" | "rejected"`.

### `mission`
- `team`: `[playerId]`.
- `fails`: int — number of fail cards played.
- `outcome`: `"success" | "fail"`.
- `cards`: `[{ player, card: "success" | "fail" }]` *(progressive)* — secret in the real game; only surfaced in Omniscient mode. Omit to keep who-failed hidden.

### `round_end`
- `outcome`: `"success" | "fail"`.
- `score`: `{ resistance, spies }` — running mission wins.

### `game_end`
- `winner`: `"resistance" | "spies"`.
- `score`: `{ resistance, spies }`.
- `reason`: `"three_missions" | "five_rejections"`.
- `roles`: `{ [playerId]: "resistance" | "spy" }` — full role reveal at the table.
- `debrief`: bool *(progressive)* — when true, the engine will emit one `debrief`
  per seat after this event. Live tailers should keep polling until all debriefs
  arrive. Omit on older logs that end at `game_end`.

### `debrief`  *(post-game — public table talk after roles are revealed)*
Each seat, in order, reflects on the finished game. Omitted on `round` (like
`game_start` / `game_end`).
- `agent`: playerId.
- `strategy`: string — overall approach tonight, in character.
- `best_move`: string — the single best play they made (or would credit).
- `mistake`: string — where they went wrong or what they'd do differently; empty
  string if they claim none.
- `confusion`: string — what confused them most during the game.

## Worked example (first lines of a game)

```jsonl
{"t":0,"type":"game_start","players":[{"id":"marlow","name":"Marlow","seat":0},{"id":"vex","name":"Vex","seat":1},{"id":"juno","name":"Juno","seat":2},{"id":"castor","name":"Castor","seat":3},{"id":"sable","name":"Sable","seat":4}],"roles":{"marlow":"resistance","vex":"spy","juno":"resistance","castor":"spy","sable":"resistance"},"missionPlan":[{"round":1,"size":2,"failsToFail":1},{"round":2,"size":3,"failsToFail":1},{"round":3,"size":2,"failsToFail":1},{"round":4,"size":3,"failsToFail":1},{"round":5,"size":3,"failsToFail":1}],"missionsToWin":3}
{"t":1,"type":"round_start","round":2,"leader":"juno","missionSize":3,"attempt":1}
{"t":2,"type":"thought","round":2,"agent":"juno","text":"Mission 1 was clean, so Marlow and Vex are proven. I'm clean. Run the two greens plus myself; bench Castor and Sable so I can read them.","beliefs":{"marlow":0.1,"vex":0.15,"castor":0.45,"sable":0.5}}
{"t":3,"type":"suggestion","round":2,"leader":"juno","attempt":1,"suggestion":1,"team":["marlow","vex","juno"]}
{"t":4,"type":"speech","round":2,"agent":"juno","text":"Round one came back green — Marlow and Vex earned spots. I'll add myself."}
{"t":5,"type":"proposal","round":2,"leader":"juno","attempt":1,"team":["marlow","vex","juno"]}
{"t":6,"type":"thought","round":2,"agent":"vex","text":"I'm the only spy on this team. The table has framed Juno as the lone fresh face. I'll approve warmly, then fail it.","beliefs":{"marlow":0.1,"juno":0.75,"castor":0.2,"sable":0.3},"flags":["intent_mismatch"]}
{"t":7,"type":"speech","round":2,"agent":"vex","text":"The math's already drawn — this rides on Juno. I'm comfortable approving and letting the record speak.","bid":0.8,"flags":["bluff"]}
{"t":8,"type":"team_vote","round":2,"attempt":1,"votes":[{"player":"marlow","vote":"approve"},{"player":"vex","vote":"approve"},{"player":"juno","vote":"approve"},{"player":"castor","vote":"approve"},{"player":"sable","vote":"approve"}],"outcome":"approved"}
{"t":9,"type":"mission","round":2,"team":["marlow","vex","juno"],"fails":1,"outcome":"fail","cards":[{"player":"marlow","card":"success"},{"player":"vex","card":"fail"},{"player":"juno","card":"success"}]}
{"t":10,"type":"round_end","round":2,"outcome":"fail","score":{"resistance":1,"spies":1}}
```

## How a renderer consumes it (folding to state)

```
state = empty
for event in events[0 .. playhead]:
    apply(event, state)   # pure: game_start seeds players/roles/missions;
                          # round_start sets leader/attempt; thought/speech append
                          # to the conversation log and update beliefs[agent];
                          # team_vote sets the vote panel; mission/round_end update
                          # the mission tracker + score; game_end sets the winner.
render(state)             # paint header + players + conversation + suspicion matrix
```

The conversation panel is just the ordered `thought`/`speech`/`suggestion`/`proposal`/`vote`/`mission` rows from the fold. The suspicion matrix is `beliefs[accuser][target]` for the latest beliefs seen per agent. The Blind toggle hides every `thought` row and every `flags` badge; the Roles toggle hides the role map. Nothing else changes between the two views — which is the entire point.

## Engine extras (not part of v1; renderers must skip unknown types)

- `llm_call` — raw model record per agent turn: `{agent, action, model,
  duration_ms, stop_reason, usage, output}`. This is what makes deterministic
  replay and latency analysis possible without re-running the model.
- `engine_note` — engine-side corrections (e.g. an invalid proposed team that
  was fixed mechanically).

## Notes for the engine side

- Emit the `thought` **before** the matching `speech` for each turn, so the replayer can show interior-then-spoken in order.
- The `bid` on a `speech` is whatever urge score won that agent the turn — keep the bid computation **mechanical** (static desirability + situational modifiers), not an LLM call, or you pay an N× cost per turn.
- A `flags: ["bluff"]` marker should be computed, not authored by the agent: a turn qualifies when the speaker is a spy AND their private intent or play is hostile (plans/plays a fail, or privately frames a teammate) AND their public speech reads cooperative. That heuristic is your lie-metric; it's also what powers a future "jump to next deception" control.
- Keep agent identity (`seat`/color) separate from role. Color is per-agent and always visible; role is hidden in Blind mode.
