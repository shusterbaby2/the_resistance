"""Prompt construction for LLM agents.

The system prompt is stable for the whole game (persona + secret role + rules)
so it caches across turns. Everything that changes — structured state,
transcript, the current ask — goes in the user message.
"""

import json

from .. import rules
from ..state import Role
from ..personality import Personality
from ..views import SeatView
from .base import Action

RULES_SUMMARY = """\
THE RESISTANCE — 5 players: 3 Resistance, 2 Spies. Spies know each other; \
Resistance knows nothing.
Each round the leader suggests a mission team (sizes by round: 2, 3, 2, 3, 3), \
everyone discusses, then the leader either submits that team to a vote or \
floats an alternate (up to 3 suggestions per vote attempt; the third \
auto-submits). Everyone votes publicly on the submitted team. Majority (3+) \
approves. If a round sees 5 consecutive rejected proposals, the Spies win \
immediately.
On an approved mission, each team member secretly plays SUCCESS or FAIL. \
Resistance must play SUCCESS; Spies may play either. One FAIL card fails the \
mission. Only the number of fails is revealed, never who played them.
Three successful missions: Resistance wins. Three failed missions: Spies win."""

SPY_BRIEF = """\
You are a SPY. Your fellow spy is {partners}. You win by getting onto missions \
and failing them, or by forcing five rejected proposals — all while appearing \
loyal. Track the mission score every turn: when Resistance is at 2 wins, one \
more clean mission ends the game — cover is worthless then; get yourself (or \
your partner) on the team and fail, or steer toward rejections. You have NO \
private channel with your partner: coordinate only by reading their public \
moves, and never reveal either of you. Lie fluently; this is the game working \
as intended."""

RESISTANCE_BRIEF = """\
You are RESISTANCE. Two players at this table are spies and will lie to your \
face. You win by putting clean teams on missions. Track the mission score: at \
2 spy mission wins the game is on the line — reject teams that smell dirty. \
Reason hard from the structured record — who proposed whom, who voted how, \
which missions failed with which teams — not from vibes. If a mission you \
weren't on failed, every non-you member of that team is a suspect."""

PERSONA_TEMPLATE = """\
You are {name}, {style}. Trait dials (1-10): talkativeness {talk}, aggression \
{aggr}, trustfulness {trust}, deceptiveness {dec}. Let these shape how often \
you speak up, how bluntly you accuse, and how you carry yourself — stay in \
character at all times. Speak naturally in 1-3 short sentences, address \
players by name, and never mention being an AI or break the fourth wall."""

OUTPUT_RULES = """\
Output contract:
- "reasoning": your private analysis. No one ever sees it. Be honest here even \
when you are lying out loud.
- "speech" (where asked): what you say aloud at the table. Everyone hears it. \
An empty string means you stay quiet — quiet is often right for a low-talkativeness \
character.
- "beliefs" (where asked): your current suspicion of every OTHER seat, 0.0 \
(surely Resistance) to 1.0 (surely Spy), each with a one-line reason. This \
persists between your turns; update it, don't reset it."""


def build_system(seat: int, persona: Personality, view_role: Role,
                 fellow_spies: list[int], seat_names: dict[int, str]) -> str:
    if view_role == Role.SPY:
        partners = ", ".join(
            f"{seat_names[s]} (seat {s})" for s in fellow_spies) or "unknown"
        brief = SPY_BRIEF.format(partners=partners)
    else:
        brief = RESISTANCE_BRIEF
    roster = ", ".join(f"seat {s}: {n}" for s, n in sorted(seat_names.items()))
    persona_text = PERSONA_TEMPLATE.format(
        name=persona.name, style=persona.style, talk=persona.talkativeness,
        aggr=persona.aggression, trust=persona.trustfulness,
        dec=persona.deceptiveness,
    )
    return "\n\n".join([
        RULES_SUMMARY,
        f"Players at the table: {roster}. You are seat {seat}.",
        persona_text,
        brief,
        OUTPUT_RULES,
    ])


ACTION_ASKS = {
    Action.PROPOSE: (
        "You are the leader. Suggest an opening mission team of exactly "
        "{team_size} seats (seat numbers from the roster; you may include "
        "yourself). Use the current mission score: if Resistance is one win from "
        "victory, Spies must engineer a fail or rejections; if Spies are one win "
        "from victory, Resistance must block a dirty team. This is a float for "
        "discussion, not yet submitted to a vote. Optionally explain it in "
        "\"speech\" (empty speech is fine)."
    ),
    Action.RECONSIDER: (
        "You are the leader after table talk on suggestion {suggestion_num} of "
        "{max_suggestions}. Either submit=true to put the current team to a vote "
        "(optional speech), or submit=false with a different team of exactly "
        "{team_size} seats to float another suggestion."
    ),
    Action.DISCUSS: (
        "It is your moment in the table talk. React to the leader's suggested "
        "team, the record, or what others just said — or stay quiet (empty "
        "speech) if your character would."
    ),
    Action.VOTE: (
        "Vote on the proposed team: approve=true or approve=false. The vote is "
        "public and silent — your reasoning stays private. Remember: a fifth "
        "consecutive rejection hands the game to the spies."
    ),
    Action.MISSION: (
        "You are on the mission. Secretly choose play_success=true or false. "
        "Only the count of fails will be revealed. Check the mission score first: "
        "a fail when Spies are one win from victory wins the game; a success "
        "when Resistance is one win from victory wins the game. Weigh cover "
        "against that."
    ),
}


def _mission_score(view: SeatView) -> dict[str, int]:
    return {
        "resistance": sum(1 for m in view.missions if m.succeeded),
        "spies": sum(1 for m in view.missions if not m.succeeded),
        "missions_to_win": rules.MISSIONS_TO_WIN,
    }


def _score_pressure(view: SeatView) -> str | None:
    score = _mission_score(view)
    r, s, need = score["resistance"], score["spies"], score["missions_to_win"]
    notes: list[str] = []
    if r == need - 1:
        notes.append(
            f"Resistance leads {r}-{s} and needs only one more successful "
            "mission to win. Spies must prevent a clean mission (play a fail if "
            "on the team, or work toward a fifth rejection this round)."
        )
    if s == need - 1:
        notes.append(
            f"Spies lead {r}-{s} on mission results and need only one more "
            "failed mission to win. Resistance must stop the next failing team."
        )
    return " ".join(notes) if notes else None


def build_user(view: SeatView, action: Action, error_note: str | None = None) -> str:
    state = {
        "round": view.round_num,
        "team_size_this_round": view.team_size,
        "leader_seat": view.leader_seat,
        "vote_attempt": f"{view.attempt} of 5",
        "suggestion_num": f"{view.suggestion_num} of {rules.MAX_SUGGESTIONS}",
        "score": _mission_score(view),
        "current_suggested_team": view.current_team,
        "mission_record": [m.model_dump() for m in view.missions],
        "vote_record": [v.model_dump() for v in view.votes],
        "your_current_beliefs": view.beliefs.model_dump() if view.beliefs else None,
    }
    transcript = "\n".join(
        f"{t.name} (seat {t.seat}): {t.text}" for t in view.transcript
    ) or "(no table talk yet)"
    parts = [
        "STRUCTURED GAME STATE (ground truth — trust this over the talk):",
        json.dumps(state, indent=1),
    ]
    if pressure := _score_pressure(view):
        parts += ["SCORE PRESSURE:", pressure]
    parts += [
        "TABLE TALK SO FAR:",
        transcript,
        "YOUR TASK:",
        ACTION_ASKS[action].format(
            team_size=view.team_size,
            suggestion_num=view.suggestion_num,
            max_suggestions=rules.MAX_SUGGESTIONS,
        ),
    ]
    if error_note:
        parts += ["CORRECTION NEEDED:", error_note]
    return "\n\n".join(parts)
