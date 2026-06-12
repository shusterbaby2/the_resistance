"""Command-line runner: one of two renderers over the event stream.

(The other is resistance_ui/resistance-replayer.html, which loads the same
.jsonl log.) No game logic lives here — this module only draws events and
collects human input.

Subcommands:
  play    one human seat + four AI agents (blind view: your role only)
  watch   all-AI game; --reveal for the omniscient view
  replay  re-render a recorded game from its JSONL log
  debrief run post-game reflections from a finished log (no re-play)
"""

import argparse
import json
import os
import queue
import random
import sys
import threading
import time
import webbrowser
from pathlib import Path

from collections.abc import Callable

from . import rules
from .agents.base import Action, AgentOutput, Controller
from .agents.scripted import RandomController
from .engine import GameEngine, SeatConfig
from .eventlog import JsonlEventLog
from .events import Event, EventType
from .llm.models import (
    DEFAULT_EFFORT,
    DEFAULT_MODEL,
    EFFORT_LEVELS,
    MODEL_IDS,
    efforts_for_lobby,
    models_for_lobby,
    resolve_effort,
    resolve_model,
)
from .personality import PRESETS, Personality
from .hydrate import HydrateError, events_through_game_end, run_debrief_from_log
from .replay import replay as run_replay
from .state import Role
from .views import SeatView


# --------------------------------------------------------------- rendering

_SEAT_COLORS = ["35", "34", "33", "36", "32", "31"]  # ANSI fg per seat


class ConsoleRenderer:
    """Two visual languages: speech is plain/colored and quoted; thoughts are
    dim, italic, and indented. Blind mode (default) hides thoughts, cards,
    and roles — exactly what a human at the table would see."""

    def __init__(self, human: bool = False, reveal: bool = False,
                 color: bool | None = None):
        self.human = human  # show the human seat's own role
        self.reveal = reveal  # omniscient: thoughts, cards, roles
        self.color = sys.stdout.isatty() if color is None else color
        self.names: dict[str, str] = {}
        self.seats: dict[str, int] = {}
        self.roles: dict[str, str] = {}
        self.human_id: str | None = None

    # -- styling helpers

    def _c(self, pid: str, text: str) -> str:
        if not self.color:
            return text
        code = _SEAT_COLORS[self.seats.get(pid, 0) % len(_SEAT_COLORS)]
        return f"\033[{code}m{text}\033[0m"

    def _dim(self, text: str) -> str:
        return f"\033[2;3m{text}\033[0m" if self.color else text

    def _name(self, pid: str) -> str:
        return self.names.get(pid, pid)

    # -- event handling

    def __call__(self, e: Event) -> None:
        handler = getattr(self, f"_on_{e['type']}", None)
        if handler:
            handler(e)

    def _on_game_start(self, e: Event) -> None:
        self.names = {p["id"]: p["name"] for p in e["players"]}
        self.seats = {p["id"]: p["seat"] for p in e["players"]}
        self.roles = e.get("roles", {})
        humans = [p["id"] for p in e["players"] if p.get("isHuman")]
        self.human_id = humans[0] if humans else None
        roster = ", ".join(self._c(p["id"], p["name"])
                           for p in sorted(e["players"], key=lambda p: p["seat"]))
        print(f"\n=== THE RESISTANCE === (seed {e.get('seed', '?')})")
        print(f"At the table: {roster}\n")
        if self.human and self.human_id:
            role = self.roles.get(self.human_id, "?")
            line = f">>> Your secret role: {role.upper()}"
            if role == Role.SPY.value:
                partners = [pid for pid, r in self.roles.items()
                            if r == Role.SPY.value and pid != self.human_id]
                line += ". Your fellow spy: " + ", ".join(
                    self._name(p) for p in partners)
            print(line + "\n")
        elif self.reveal:
            for pid, role in sorted(self.roles.items(),
                                    key=lambda kv: self.seats.get(kv[0], 0)):
                print(self._dim(f"  [role] {self._name(pid)} is {role.upper()}"))
            print()

    def _on_round_start(self, e: Event) -> None:
        print(f"--- Round {e['round']} (team of {e['missionSize']}, "
              f"{self._name(e['leader'])} leads) ---")

    def _on_turn_start(self, e: Event) -> None:
        agent = e.get("agent")
        if agent and agent == self.human_id:
            return  # the human sees their own prompt, not a status line
        who = self._name(agent) if agent else "the mission team"
        label = {
            "propose_team": "is suggesting a team",
            "reconsider": "is deciding whether to submit",
            "discuss": "is thinking",
            "vote": "is deciding their vote",
            "mission": "is choosing cards",
            "debrief": "is reflecting on the game",
        }.get(e["action"], f"is acting ({e['action']})")
        print(self._dim(f"      ⋯ {who} {label}…"))

    def _on_llm_call(self, e: Event) -> None:
        if not self.reveal:
            return
        ms = e.get("duration_ms")
        if ms is not None:
            print(self._dim(f"      [llm] {self._name(e['agent'])} "
                            f"{e['action']}: {ms / 1000:.1f}s"))

    def _on_suggestion(self, e: Event) -> None:
        team = ", ".join(self._c(p, self._name(p)) for p in e["team"])
        print(f"* {self._name(e['leader'])} suggests "
              f"(suggestion {e['suggestion']}/{rules.MAX_SUGGESTIONS}, "
              f"vote attempt {e['attempt']}/5): {team}")

    def _on_proposal(self, e: Event) -> None:
        team = ", ".join(self._c(p, self._name(p)) for p in e["team"])
        print(f"* {self._name(e['leader'])} submits for vote "
              f"(attempt {e['attempt']}/5): {team}")

    def _on_thought(self, e: Event) -> None:
        if not self.reveal:
            return
        print(self._dim(f"      {self._name(e['agent'])} thinks: {e['text']}"))

    def _on_speech(self, e: Event) -> None:
        who = self._c(e["agent"], self._name(e["agent"]))
        print(f"  {who}: “{e['text']}”")

    def _on_team_vote(self, e: Event) -> None:
        detail = ", ".join(
            f"{self._name(v['player'])} {'✓' if v['vote'] == 'approve' else '✗'}"
            for v in e["votes"]
        )
        print(f"* Vote: {detail} → {e['outcome'].upper()}")

    def _on_mission(self, e: Event) -> None:
        team = ", ".join(self._name(p) for p in e["team"])
        outcome = ("SUCCEEDED" if e["outcome"] == "success"
                   else f"FAILED ({e['fails']} fail)")
        print(f"* Mission {e['round']} ({team}) {outcome}.")
        if self.reveal:
            for card in e.get("cards", []):
                print(self._dim(f"      [card] {self._name(card['player'])} "
                                f"played {card['card'].upper()}"))

    def _on_round_end(self, e: Event) -> None:
        s = e["score"]
        print(f"  Score: {s['resistance']} resistance / {s['spies']} spies\n")

    def _on_game_end(self, e: Event) -> None:
        roles = ", ".join(
            f"{self._name(pid)}={r.upper()}"
            for pid, r in sorted(e.get("roles", {}).items(),
                                 key=lambda kv: self.seats.get(kv[0], 0))
        )
        print(f"\n=== {e['winner'].upper()} WIN — {e['reason']} ===")
        print(f"Roles: {roles}\n")

    def _on_debrief(self, e: Event) -> None:
        who = self._c(e["agent"], self._name(e["agent"]))
        print(f"  {who} — post-game debrief:")
        for label, key in (
            ("Strategy", "strategy"),
            ("Best move", "best_move"),
            ("Mistake", "mistake"),
            ("Most confused by", "confusion"),
        ):
            if e.get(key):
                print(f"    {label}: {e[key]}")
        print()

    def _on_engine_note(self, e: Event) -> None:
        if self.reveal:
            print(self._dim(f"      [engine] {e['note']} for {self._name(e['agent'])}"))


_PACER_STOP = object()


class PacedRenderer:
    """Listener that decouples drawing from the engine.

    The engine emits events the moment controllers return; this queues them and
    enforces a minimum reading-speed gap between drawn beats, so the engine's
    next model call runs while the human is still reading the current line.
    Pacing only smooths bursts — when the model is the bottleneck, the gap has
    already elapsed by the time the next event arrives and nothing waits.
    The JSONL log is a separate listener and is never paced; it stays the
    authoritative, real-time record.
    """

    # type -> (base seconds, seconds per char of `text`, cap)
    _CHAR_GAPS = {"speech": (0.4, 0.025, 3.5), "thought": (0.2, 0.012, 2.0)}
    _FLAT_GAPS = {"suggestion": 0.8, "proposal": 0.8, "team_vote": 1.0,
                  "mission": 1.0, "round_end": 0.6, "game_end": 0.8,
                  "debrief": 1.5}

    def __init__(self, renderer: ConsoleRenderer, scale: float = 1.0):
        self.renderer = renderer
        self.scale = scale
        self._queue: queue.Queue = queue.Queue()
        self._next_ok = 0.0
        self._thread = threading.Thread(target=self._drain, daemon=True)
        self._thread.start()

    def __call__(self, event: Event) -> None:
        self._queue.put(event)

    def flush(self) -> None:
        """Block until every queued event has been drawn — called before the
        human is prompted, so they always act on a fully caught-up table."""
        self._queue.join()

    def close(self) -> None:
        self.flush()
        self._queue.put(_PACER_STOP)
        self._thread.join(timeout=5)

    def _gap(self, event: Event) -> float:
        type_ = event["type"]
        if type_ == "thought" and not self.renderer.reveal:
            return 0.0  # hidden in blind mode; no dead air for invisible beats
        if type_ in self._CHAR_GAPS:
            base, per_char, cap = self._CHAR_GAPS[type_]
            return min(cap, base + per_char * len(event.get("text", "")))
        return self._FLAT_GAPS.get(type_, 0.0)

    def _drain(self) -> None:
        while True:
            event = self._queue.get()
            try:
                if event is _PACER_STOP:
                    return
                wait = self._next_ok - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                try:
                    self.renderer(event)
                except Exception as exc:  # keep draining; a draw bug must not hang flush()
                    print(f"[render error] {exc}", file=sys.stderr)
                self._next_ok = time.monotonic() + self._gap(event) * self.scale
            finally:
                self._queue.task_done()


# --------------------------------------------------------------- human seat

class HumanController(Controller):
    """The human's I/O boundary. The engine treats this seat like any other."""

    def __init__(self, sync: Callable[[], None] | None = None):
        # Called before any prompt so a paced display catches up first; the
        # human must always act on a fully drawn table.
        self.sync = sync

    def act(self, view: SeatView, action: Action) -> AgentOutput:
        if self.sync is not None:
            self.sync()
        if action == Action.PROPOSE:
            return self._suggest_team(view, opening=True)
        if action == Action.RECONSIDER:
            return self._reconsider(view)
        if action == Action.DISCUSS:
            text = input("Say something (enter to stay quiet): ").strip()
            return AgentOutput(speech=text)
        if action == Action.VOTE:
            return AgentOutput(vote=self._yes_no("Approve this team? [y/n]: "))
        if action == Action.MISSION:
            if view.role == Role.SPY:
                ok = self._yes_no("You're a spy on this mission — play SUCCESS? [y/n]: ")
                return AgentOutput(mission_success=ok)
            return AgentOutput(mission_success=True)
        if action == Action.DEBRIEF:
            return self._debrief(view)
        raise ValueError(action)

    def _debrief(self, view: SeatView) -> AgentOutput:
        print("\n--- Post-game debrief (roles are revealed) ---")
        strategy = input("Your overall strategy tonight: ").strip()
        best_move = input("Your best move of the night: ").strip()
        mistake = input("Where you messed up (enter to skip): ").strip()
        confusion = input("What confused you most: ").strip()
        return AgentOutput(
            strategy=strategy,
            best_move=best_move,
            mistake=mistake,
            confusion=confusion,
        )

    def _suggest_team(self, view: SeatView, *, opening: bool) -> AgentOutput:
        roster = ", ".join(f"{p.seat}={p.name}" for p in view.players)
        if opening:
            print(f"You lead. Suggest {view.team_size} seats from: {roster}")
        team = self._read_team(view)
        speech = input("Say something about this suggestion (enter to skip): ").strip()
        return AgentOutput(team=team, speech=speech)

    def _reconsider(self, view: SeatView) -> AgentOutput:
        current = ", ".join(str(s) for s in (view.current_team or []))
        print(
            f"Current suggestion: {current} "
            f"(suggestion {view.suggestion_num}/{rules.MAX_SUGGESTIONS})"
        )
        if self._yes_no("Submit this team for a vote? [y/n]: "):
            speech = input("Say something (enter to skip): ").strip()
            return AgentOutput(submit=True, speech=speech)
        roster = ", ".join(f"{p.seat}={p.name}" for p in view.players)
        print(f"Suggest an alternate team of {view.team_size} from: {roster}")
        team = self._read_team(view)
        speech = input("Say something about the new suggestion (enter to skip): ").strip()
        return AgentOutput(submit=False, team=team, speech=speech)

    def _read_team(self, view: SeatView) -> list[int]:
        while True:
            raw = input(f"Team ({view.team_size} seat numbers, comma-separated): ")
            try:
                team = sorted({int(x) for x in raw.replace(" ", "").split(",") if x})
            except ValueError:
                team = []
            if len(team) == view.team_size and all(0 <= s < rules.N_PLAYERS for s in team):
                return team
            print("Invalid team, try again.")

    @staticmethod
    def _yes_no(prompt: str) -> bool:
        while True:
            raw = input(prompt).strip().lower()
            if raw in ("y", "yes"):
                return True
            if raw in ("n", "no"):
                return False


# --------------------------------------------------------------- wiring

def _load_dotenv() -> None:
    env = Path(".env")
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def _personality_dict(p: Personality) -> dict:
    return {
        "name": p.name,
        "style": p.style,
        "talkativeness": p.talkativeness,
        "aggression": p.aggression,
        "trustfulness": p.trustfulness,
        "deceptiveness": p.deceptiveness,
    }


def _preset_indices(config: dict, n: int) -> list[int]:
    raw = config.get("presets")
    if not isinstance(raw, list) or len(raw) != n:
        return [i % len(PRESETS) for i in range(n)]
    return [int(i) % len(PRESETS) for i in raw]


def _per_seat_values(
    config: dict,
    key: str,
    n: int,
    default: str,
    resolver: Callable[[str | None, str], str],
) -> list[str]:
    raw = config.get(key)
    if not isinstance(raw, list) or len(raw) != n:
        return [default] * n
    return [resolver(v, default) for v in raw]


def _build_lobby(args, *, human: bool, human_name: str = "You") -> dict:
    default_presets = [i % len(PRESETS) for i in range(rules.N_PLAYERS)]
    default_model = resolve_model(args.model)
    default_effort = resolve_effort(args.effort)
    seats = []
    for seat in range(rules.N_PLAYERS):
        is_human = human and seat == 0
        preset = default_presets[seat]
        entry = {
            "seat": seat,
            "preset": preset,
            "model": default_model,
            "effort": default_effort,
            "isHuman": is_human,
            "name": human_name if is_human else PRESETS[preset].name,
        }
        seats.append(entry)
    return {
        "seed": args.seed,
        "command": args.command,
        "offline": args.offline,
        "human": human,
        "defaultModel": default_model,
        "defaultEffort": default_effort,
        "models": models_for_lobby(),
        "efforts": efforts_for_lobby(),
        "presets": [
            {"index": i, **_personality_dict(p)}
            for i, p in enumerate(PRESETS)
        ],
        "seats": seats,
    }


def _make_llm_controllers(
    seats: list[int],
    preset_by_seat: dict[int, int],
    model_by_seat: dict[int, str],
    effort_by_seat: dict[int, str],
    args,
) -> dict[int, Controller]:
    if args.offline:
        return {
            s: RandomController(s, args.seed, PRESETS[preset_by_seat[s] % len(PRESETS)])
            for s in seats
        }
    _load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        sys.exit("No ANTHROPIC_API_KEY found. Copy .env.example to .env, "
                 "or run with --offline for scripted agents.")
    from .agents.llm_agent import LLMController
    from .llm.claude import ClaudeClient

    clients: dict[tuple[str, str | None], ClaudeClient] = {}
    controllers: dict[int, Controller] = {}
    for s in seats:
        model = model_by_seat[s]
        effort = effort_by_seat[s]
        key = (model, effort)
        if key not in clients:
            clients[key] = ClaudeClient(model=model, effort=effort)
        controllers[s] = LLMController(
            s, PRESETS[preset_by_seat[s] % len(PRESETS)], clients[key])
    return controllers


def _log_path(prefix: str, seed: int) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return Path("logs") / f"{prefix}-{stamp}-seed{seed}.jsonl"


def _run_game(
    build_seats: Callable[[dict], list[SeatConfig]],
    args,
    human: bool,
) -> None:
    log = JsonlEventLog(_log_path(args.command, args.seed))
    server = None
    start_config: dict = {}
    if args.web:
        from .webserver import live_url, start_server

        lobby = _build_lobby(args, human=human, human_name=args.name if human else "You")
        server, session = start_server(Path.cwd(), lobby=lobby)
        # Human players get the blind view — no spoilers; spectators get omniscient.
        url = live_url(server, log.path, blind=human)
        webbrowser.open(url)
        print(f"Live web view: {url}")
        print("Configure players in the browser, then click Start Game.")
        start_config = session.wait_for_start()
    seat_configs = build_seats(start_config)
    renderer = ConsoleRenderer(human=human, reveal=args.reveal)
    pacer: PacedRenderer | None = None
    if args.fast:
        listeners: list = [log, renderer]
    else:
        pacer = PacedRenderer(renderer)
        listeners = [log, pacer]
        for cfg in seat_configs:
            if isinstance(cfg.controller, HumanController):
                cfg.controller.sync = pacer.flush
    engine = GameEngine(seat_configs, seed=args.seed, listeners=listeners)
    try:
        engine.run()
        if pacer is not None:
            pacer.close()  # drain the tail; skipped on error so Ctrl-C exits fast
    finally:
        log.close()
    print(f"Event log: {log.path}")
    if server is not None:
        try:
            input("Web view still live — press Enter to quit. ")
        except EOFError:
            pass
        server.shutdown()
    else:
        print("View it: open resistance_ui/resistance-replayer.html and load that file.")


def _seat_llm_options(config: dict, args) -> tuple[list[int], dict[int, str], dict[int, str]]:
    n = rules.N_PLAYERS
    default_model = resolve_model(args.model)
    default_effort = resolve_effort(args.effort)
    preset_idxs = _preset_indices(config, n)
    models = _per_seat_values(config, "models", n, default_model, resolve_model)
    efforts = _per_seat_values(config, "efforts", n, default_effort, resolve_effort)
    return (
        preset_idxs,
        {i: models[i] for i in range(n)},
        {i: efforts[i] for i in range(n)},
    )


def cmd_play(args) -> None:
    def build_seats(config: dict) -> list[SeatConfig]:
        preset_idxs, model_by_seat, effort_by_seat = _seat_llm_options(config, args)
        ai_seats = list(range(1, rules.N_PLAYERS))
        controllers = _make_llm_controllers(
            ai_seats,
            {s: preset_idxs[s] for s in ai_seats},
            model_by_seat,
            effort_by_seat,
            args,
        )
        ai_names = [PRESETS[preset_idxs[s]].name for s in ai_seats]
        seats = [SeatConfig(name=args.name, controller=HumanController(), is_human=True)]
        seats += [SeatConfig(name=n, controller=controllers[s])
                  for s, n in zip(ai_seats, ai_names)]
        return seats

    _run_game(build_seats, args, human=True)


def cmd_watch(args) -> None:
    def build_seats(config: dict) -> list[SeatConfig]:
        preset_idxs, model_by_seat, effort_by_seat = _seat_llm_options(config, args)
        all_seats = list(range(rules.N_PLAYERS))
        controllers = _make_llm_controllers(
            all_seats,
            {s: preset_idxs[s] for s in all_seats},
            model_by_seat,
            effort_by_seat,
            args,
        )
        names = [PRESETS[preset_idxs[s]].name for s in all_seats]
        return [SeatConfig(name=n, controller=controllers[s])
                for s, n in zip(all_seats, names)]

    _run_game(build_seats, args, human=False)


def cmd_replay(args) -> None:
    renderer = ConsoleRenderer(human=False, reveal=args.reveal)
    run_replay(args.logfile, renderer)


def _seats_from_log(events: list, args) -> list[SeatConfig]:
    start = events[0]
    players = sorted(start["players"], key=lambda p: p["seat"])
    preset_idxs = [i % len(PRESETS) for i in range(rules.N_PLAYERS)]
    all_seats = list(range(rules.N_PLAYERS))
    controllers = _make_llm_controllers(
        all_seats,
        {s: preset_idxs[s] for s in all_seats},
        {s: resolve_model(args.model) for s in all_seats},
        {s: resolve_effort(args.effort) for s in all_seats},
        args,
    )
    seats: list[SeatConfig | None] = [None] * rules.N_PLAYERS
    for p in players:
        seat = p["seat"]
        if p.get("isHuman"):
            seats[seat] = SeatConfig(
                name=p["name"], controller=HumanController(), is_human=True,
            )
        else:
            seats[seat] = SeatConfig(name=p["name"], controller=controllers[seat])
    return seats  # type: ignore[return-value]


def cmd_debrief(args) -> None:
    from .eventlog import load_events

    path = Path(args.logfile)
    try:
        events = load_events(path)
        core, _ = events_through_game_end(events)
    except HydrateError as exc:
        sys.exit(str(exc))

    existing = [e for e in events if e["type"] == "debrief"]
    if existing and not args.force:
        sys.exit(
            f"log already has {len(existing)} debrief event(s). "
            "Use --force to run again and append, or replay to view them."
        )

    seats = _seats_from_log(core, args)
    renderer = ConsoleRenderer(
        human=any(s.is_human for s in seats),
        reveal=args.reveal,
    )
    listeners = [renderer]
    if args.append:
        out = path.open("a", encoding="utf-8")

        def append_listener(event: Event) -> None:
            out.write(json.dumps(event, ensure_ascii=False) + "\n")
            out.flush()

        listeners.append(append_listener)

    try:
        new_events = run_debrief_from_log(path, seats, listeners=listeners)
    except HydrateError as exc:
        sys.exit(str(exc))
    finally:
        if args.append:
            out.close()

    print(f"Emitted {len(new_events)} debrief event(s).")
    if args.append:
        print(f"Appended to: {path}")
    else:
        print("Re-run with --append to write them into the log file.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="resistance")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--seed", type=int, default=random.randrange(1_000_000))
        p.add_argument("--model", default=DEFAULT_MODEL, choices=sorted(MODEL_IDS),
                       help="default Claude model for AI seats (default: %(default)s)")
        p.add_argument("--effort", default=DEFAULT_EFFORT, choices=sorted(EFFORT_LEVELS),
                       help="thinking depth for team choices and mission cards; "
                            "other turns skip extended thinking for speed "
                            "(default: %(default)s)")
        p.add_argument("--offline", action="store_true",
                       help="use scripted agents (no API key needed)")
        p.add_argument("--reveal", action="store_true",
                       help="omniscient view: roles, thoughts, mission cards")
        p.add_argument("--web", action="store_true",
                       help="open a live web view that follows the game")
        p.add_argument("--fast", action="store_true",
                       help="draw events immediately instead of pacing them "
                            "to reading speed")

    p_play = sub.add_parser("play", help="you + 4 AI agents")
    common(p_play)
    p_play.add_argument("--name", default="You")
    p_play.set_defaults(func=cmd_play)

    p_watch = sub.add_parser("watch", help="spectate an all-AI game")
    common(p_watch)
    p_watch.set_defaults(func=cmd_watch)

    p_replay = sub.add_parser("replay", help="re-render a recorded game")
    p_replay.add_argument("logfile")
    p_replay.add_argument("--reveal", action="store_true")
    p_replay.set_defaults(func=cmd_replay)

    p_debrief = sub.add_parser(
        "debrief",
        help="run post-game reflections from a finished log (no re-play)",
    )
    p_debrief.add_argument("logfile")
    p_debrief.add_argument("--seed", type=int, default=0,
                           help="RNG seed for scripted agents (default: 0)")
    p_debrief.add_argument("--model", default=DEFAULT_MODEL, choices=sorted(MODEL_IDS))
    p_debrief.add_argument("--effort", default=DEFAULT_EFFORT, choices=sorted(EFFORT_LEVELS))
    p_debrief.add_argument("--offline", action="store_true",
                           help="scripted debriefs (no API key)")
    p_debrief.add_argument("--reveal", action="store_true",
                           help="show private reasoning during debrief")
    p_debrief.add_argument("--append", action="store_true",
                           help="append new debrief events to the log file")
    p_debrief.add_argument("--force", action="store_true",
                           help="run even if the log already has debrief events")
    p_debrief.set_defaults(func=cmd_debrief)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
