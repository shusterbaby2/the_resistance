"""Mechanical speaking-bid orchestrator for table talk.

Bid = static talkativeness desirability + situational modifiers + noise.
Only the bid winner receives a DISCUSS controller call (no LLM for losers).
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from . import rules
from .personality import Personality
from .state import GameState
from .views import TranscriptEntry

ACCUSE_PATTERN = re.compile(
    r"\b(spy|spies|liar|lying|suspect|suspicious|fishy|sketchy|accus(e|ed|ing)|"
    r"can't trust|cannot trust|don't trust|do not trust)\b",
    re.IGNORECASE,
)

# Situational boosts (tuned for 0..1 bid scale).
ON_TEAM_BOOST = 0.22
LEADER_BOOST = 0.12
NAMED_BOOST = 0.28
ACCUSED_BOOST = 0.38
STARVATION_PER_SLOT = 0.09
STARVATION_CAP = 0.45
JUST_SPOKE_PENALTY = 0.42
RECENT_SPOKE_PENALTY = 0.18
NOISE_SPREAD = 0.12
SPEAK_FLOOR = 0.32  # below this, the table is quiet — leader may call a vote
RAISED_HAND_BID = 2.0  # a seat that asked for the floor outbids everyone
PASS_PENALTY = 0.55  # winner took the floor but stayed silent
FATIGUE_PER_UTTERANCE = 0.12  # each speech cools the table a little
DEFAULT_MAX_TURNS = 10  # hard cap per discussion; fatigue usually ends it sooner


@dataclass
class DiscussionTracker:
    """Per-discussion-phase state for bid modifiers."""

    transcript_start: int
    speak_count: dict[int, int] = field(default_factory=dict)
    slots_since_spoke: dict[int, int] = field(default_factory=dict)
    last_speaker: int | None = None
    pass_penalty: dict[int, float] = field(default_factory=dict)
    utterances: int = 0

    def note_utterance(self) -> None:
        self.utterances += 1

    def discussion_fatigue(self) -> float:
        return self.utterances * FATIGUE_PER_UTTERANCE

    def note_slot(self, seats: range | list[int]) -> None:
        for seat in seats:
            self.slots_since_spoke[seat] = self.slots_since_spoke.get(seat, 0) + 1
        self.pass_penalty.clear()

    def note_pass(self, seat: int) -> None:
        self.pass_penalty[seat] = PASS_PENALTY

    def note_spoke(self, seat: int) -> None:
        self.speak_count[seat] = self.speak_count.get(seat, 0) + 1
        self.slots_since_spoke[seat] = 0
        self.last_speaker = seat


def _mentioned(name: str, text: str) -> bool:
    return name.lower() in text.lower()


def _accused(name: str, text: str) -> bool:
    return _mentioned(name, text) and ACCUSE_PATTERN.search(text) is not None


def _recent_entries(
    transcript: list[TranscriptEntry], start: int, *, limit: int = 6,
) -> list[TranscriptEntry]:
    return transcript[start:][-limit:]


def compute_bid(
    seat: int,
    persona: Personality,
    state: GameState,
    transcript: list[TranscriptEntry],
    tracker: DiscussionTracker,
    rng: random.Random,
) -> float:
    """Return a clamped 0..1 speak-urge score for one seat this slot."""
    score = persona.talkativeness / 10.0

    team = state.current_team or []
    if seat in team:
        score += ON_TEAM_BOOST
    if seat == state.leader_seat:
        score += LEADER_BOOST

    name = state.player(seat).name
    for entry in _recent_entries(transcript, tracker.transcript_start):
        if _accused(name, entry.text):
            score += ACCUSED_BOOST
            break
    else:
        for entry in _recent_entries(transcript, tracker.transcript_start):
            if _mentioned(name, entry.text):
                score += NAMED_BOOST
                break

    silent = tracker.slots_since_spoke.get(seat, 0)
    score += min(silent * STARVATION_PER_SLOT, STARVATION_CAP)

    if tracker.last_speaker == seat:
        score -= JUST_SPOKE_PENALTY
    elif (
        tracker.last_speaker is not None
        and silent <= 1
        and tracker.speak_count.get(seat, 0)
    ):
        score -= RECENT_SPOKE_PENALTY

    score -= tracker.pass_penalty.get(seat, 0.0)
    score -= tracker.discussion_fatigue()
    score += rng.uniform(-NOISE_SPREAD, NOISE_SPREAD)
    return max(0.0, min(1.0, score))


def compute_bids(
    rng: random.Random,
    personas: dict[int, Personality],
    state: GameState,
    transcript: list[TranscriptEntry],
    tracker: DiscussionTracker,
) -> dict[int, float]:
    return {
        seat: compute_bid(seat, personas[seat], state, transcript, tracker, rng)
        for seat in range(rules.N_PLAYERS)
    }


def table_wants_to_talk(
    bids: dict[int, float], floor: float = SPEAK_FLOOR,
) -> bool:
    return max(bids.values()) >= floor


def pick_speaker(
    rng: random.Random,
    personas: dict[int, Personality],
    state: GameState,
    transcript: list[TranscriptEntry],
    tracker: DiscussionTracker,
    bids: dict[int, float] | None = None,
) -> tuple[int, float, dict[int, float]]:
    """Highest bid wins; ties broken randomly."""
    if bids is None:
        bids = compute_bids(rng, personas, state, transcript, tracker)
    winner = max(bids, key=lambda s: (bids[s], rng.random()))
    return winner, bids[winner], bids
