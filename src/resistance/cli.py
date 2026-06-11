"""Command-line runner: one of two renderers over the event stream.

(The other is resistance_ui/resistance-replayer.html, which loads the same
.jsonl log.) No game logic lives here — this module only draws events and
collects human input.

Subcommands:
  play    one human seat + four AI agents (blind view: your role only)
  watch   all-AI game; --reveal for the omniscient view
  replay  re-render a recorded game from its JSONL log
"""

import argparse
import os
import random
import sys
import time
import webbrowser
from pathlib import Path

from . import rules
from .agents.base import Action, AgentOutput, Controller
from .agents.scripted import RandomController
from .engine import GameEngine, SeatConfig
from .eventlog import JsonlEventLog
from .events import Event, EventType
from .personality import PRESETS
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

    def _on_engine_note(self, e: Event) -> None:
        if self.reveal:
            print(self._dim(f"      [engine] {e['note']} for {self._name(e['agent'])}"))


# --------------------------------------------------------------- human seat

class HumanController(Controller):
    """The human's I/O boundary. The engine treats this seat like any other."""

    def act(self, view: SeatView, action: Action) -> AgentOutput:
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
        raise ValueError(action)

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


def _make_llm_controllers(seats: list[int], args) -> dict[int, Controller]:
    if args.offline:
        return {
            s: RandomController(s, args.seed, PRESETS[s % len(PRESETS)])
            for s in seats
        }
    _load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        sys.exit("No ANTHROPIC_API_KEY found. Copy .env.example to .env, "
                 "or run with --offline for scripted agents.")
    from .agents.llm_agent import LLMController
    from .llm.claude import ClaudeClient

    client = ClaudeClient(model=args.model, effort=args.effort)
    personas = PRESETS[: len(seats)]
    return {s: LLMController(s, persona, client)
            for s, persona in zip(seats, personas)}


def _log_path(prefix: str, seed: int) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return Path("logs") / f"{prefix}-{stamp}-seed{seed}.jsonl"


def _run_game(seat_configs: list[SeatConfig], args, human: bool) -> None:
    log = JsonlEventLog(_log_path(args.command, args.seed))
    server = None
    if args.web:
        from .webserver import live_url, start_server

        server = start_server(Path.cwd())
        # Human players get the blind view — no spoilers; spectators get omniscient.
        url = live_url(server, log.path, blind=human)
        webbrowser.open(url)
        print(f"Live web view: {url}")
    renderer = ConsoleRenderer(human=human, reveal=args.reveal)
    engine = GameEngine(seat_configs, seed=args.seed, listeners=[log, renderer])
    try:
        engine.run()
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


def cmd_play(args) -> None:
    ai_seats = list(range(1, rules.N_PLAYERS))
    controllers = _make_llm_controllers(ai_seats, args)
    ai_names = [PRESETS[i - 1].name for i in ai_seats]
    seats = [SeatConfig(name=args.name, controller=HumanController(), is_human=True)]
    seats += [SeatConfig(name=n, controller=controllers[s])
              for s, n in zip(ai_seats, ai_names)]
    _run_game(seats, args, human=True)


def cmd_watch(args) -> None:
    all_seats = list(range(rules.N_PLAYERS))
    controllers = _make_llm_controllers(all_seats, args)
    names = [p.name for p in PRESETS[: rules.N_PLAYERS]]
    seats = [SeatConfig(name=n, controller=controllers[s])
             for s, n in zip(all_seats, names)]
    _run_game(seats, args, human=False)


def cmd_replay(args) -> None:
    renderer = ConsoleRenderer(human=False, reveal=args.reveal)
    run_replay(args.logfile, renderer)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="resistance")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--seed", type=int, default=random.randrange(1_000_000))
        p.add_argument("--model", default="claude-opus-4-8")
        p.add_argument("--effort", default="medium",
                       choices=["low", "medium", "high", "xhigh", "max"],
                       help="agent thinking depth: low = snappiest turns, "
                            "high+ = strongest deduction (default: medium)")
        p.add_argument("--offline", action="store_true",
                       help="use scripted agents (no API key needed)")
        p.add_argument("--reveal", action="store_true",
                       help="omniscient view: roles, thoughts, mission cards")
        p.add_argument("--web", action="store_true",
                       help="open a live web view that follows the game")

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

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
