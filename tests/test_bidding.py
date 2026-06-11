import random
from collections import Counter

from resistance import rules
from resistance.agents.base import Action, AgentOutput, Controller
from resistance.agents.scripted import RandomController
from resistance.bidding import (
    SPEAK_FLOOR,
    DiscussionTracker,
    compute_bid,
    compute_bids,
    pick_speaker,
    table_wants_to_talk,
)
from resistance.engine import GameEngine, SeatConfig
from resistance.events import EventType
from resistance.personality import PRESETS, Personality
from resistance.state import GameState, PlayerState, Role
from resistance.views import TranscriptEntry


def _quiet_and_chatty_personas() -> dict[int, Personality]:
    quiet = Personality(
        name="Quiet", style="barely speaks", talkativeness=1,
        aggression=5, trustfulness=5, deceptiveness=5,
    )
    chatty = Personality(
        name="Chatty", style="never shuts up", talkativeness=10,
        aggression=5, trustfulness=5, deceptiveness=5,
    )
    return {i: quiet if i % 2 == 0 else chatty for i in range(5)}


def _minimal_state() -> GameState:
  players = [
      PlayerState(seat=i, name=f"P{i}", role=Role.RESISTANCE)
      for i in range(rules.N_PLAYERS)
  ]
  return GameState(seed=1, players=players, leader_seat=0, current_team=[0, 1])


def test_talkative_base_bid_beats_quiet():
    state = _minimal_state()
    tracker = DiscussionTracker(transcript_start=0)
    rng = random.Random(0)
    personas = _quiet_and_chatty_personas()
    quiet_bid = compute_bid(0, personas[0], state, [], tracker, rng)
    chatty_bid = compute_bid(1, personas[1], state, [], tracker, rng)
    assert chatty_bid > quiet_bid


def test_bidding_favors_talkative_over_many_slots():
    state = _minimal_state()
    tracker = DiscussionTracker(transcript_start=0)
    rng = random.Random(99)
    personas = _quiet_and_chatty_personas()
    wins = Counter()
    for _ in range(200):
        seat, _, _ = pick_speaker(rng, personas, state, [], tracker)
        wins[seat] += 1
        tracker.note_spoke(seat)
        tracker.note_slot(range(rules.N_PLAYERS))
    quiet_wins = sum(wins[i] for i in range(0, 5, 2))
    chatty_wins = sum(wins[i] for i in range(1, 5, 2))
    assert chatty_wins > quiet_wins * 2


def test_named_in_transcript_boosts_bid():
    state = _minimal_state()
    state.players[2].name = "Juno"
    transcript = [
        TranscriptEntry(seat=1, name="P1", text="I think Juno is suspicious."),
    ]
    tracker = DiscussionTracker(transcript_start=0)
    rng = random.Random(0)
    persona = PRESETS[2]
    base = compute_bid(2, persona, state, [], tracker, rng)
    boosted = compute_bid(2, persona, state, transcript, tracker, rng)
    assert boosted > base


class CountingDiscussController(Controller):
    def __init__(self, seat: int):
        self.seat = seat
        self.discuss_calls = 0

    def act(self, view, action):
        if action == Action.PROPOSE:
            team = sorted(p.seat for p in view.players)[: view.team_size]
            return AgentOutput(team=team, speech="here", reasoning="r")
        if action == Action.RECONSIDER:
            return AgentOutput(submit=True, reasoning="r")
        if action == Action.DISCUSS:
            self.discuss_calls += 1
            return AgentOutput(speech=f"seat {self.seat}", reasoning="r")
        if action == Action.VOTE:
            return AgentOutput(vote=True, reasoning="r")
        if action == Action.MISSION:
            return AgentOutput(mission_success=True, reasoning="r")
        if action == Action.DEBRIEF:
            return AgentOutput(strategy="s", best_move="b", confusion="c")
        raise ValueError(action)


def test_discussion_calls_only_bid_winners():
    max_turns = 6
    controllers = [CountingDiscussController(i) for i in range(5)]
    seats = [
        SeatConfig(name=f"P{i}", controller=controllers[i],
                   personality=PRESETS[i % len(PRESETS)])
        for i in range(5)
    ]
    engine = GameEngine(
        seats, seed=3,
        discussion_speak_floor=0.0,
        discussion_max_turns=max_turns,
    )
    engine._assign_roles()
    engine.state.current_team = [0, 1]
    engine._run_discussion()
    assert sum(c.discuss_calls for c in controllers) == max_turns


def test_discussion_ends_when_table_is_quiet():
    quiet = Personality(
        name="Mute", style="silent", talkativeness=1,
        aggression=5, trustfulness=5, deceptiveness=5,
    )
    controllers = [CountingDiscussController(i) for i in range(5)]
    seats = [
        SeatConfig(name=f"P{i}", controller=controllers[i], personality=quiet)
        for i in range(5)
    ]
    engine = GameEngine(seats, seed=1, discussion_speak_floor=SPEAK_FLOOR)
    engine._assign_roles()
    # Team in the back row — no leader boost, low talk scores stay under the floor.
    engine.state.current_team = [3, 4]
    engine._run_discussion()
    assert sum(c.discuss_calls for c in controllers) == 0


def test_table_wants_to_talk_responds_to_recent_speech():
    state = _minimal_state()
    tracker = DiscussionTracker(transcript_start=0)
    rng = random.Random(0)
    personas = {i: PRESETS[i] for i in range(5)}
    quiet_bids = compute_bids(rng, personas, state, [], tracker)
    assert table_wants_to_talk(quiet_bids, SPEAK_FLOOR)

    for _ in range(3):
        for seat in range(rules.N_PLAYERS):
            tracker.note_spoke(seat)
            tracker.note_utterance()
        tracker.note_slot(range(rules.N_PLAYERS))

    tired_bids = compute_bids(rng, personas, state, [], tracker)
    assert not table_wants_to_talk(tired_bids, SPEAK_FLOOR)


def test_speech_events_carry_bid():
    events = []
    max_turns = 4
    seats = [
        SeatConfig(name=f"Bot{i}", controller=RandomController(i, 5))
        for i in range(5)
    ]
    GameEngine(
        seats, seed=5, listeners=[events.append],
        discussion_speak_floor=0.0,
        discussion_max_turns=max_turns,
    ).run()
    discuss_turns = sum(
        1 for e in events
        if e["type"] == EventType.TURN_START and e.get("action") == Action.DISCUSS.value
    )
    suggestions = sum(1 for e in events if e["type"] == EventType.SUGGESTION)
    bid_speeches = [e for e in events if e["type"] == EventType.SPEECH and "bid" in e]
    assert discuss_turns == max_turns * suggestions
    assert bid_speeches
    assert all(0 <= e["bid"] <= 1 for e in bid_speeches)
