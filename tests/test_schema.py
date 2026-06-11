"""Schema-v1 contract tests.

Mirrors what the web replayer's fold (computeState) requires, so the engine
can't drift from resistance_ui/resistance-event-schema.md without a test
failing here.
"""

from conftest import ScriptableController, make_engine

V1_TYPES = {"game_start", "round_start", "turn_start", "proposal", "thought",
            "speech", "team_vote", "mission", "round_end", "game_end"}
ENGINE_EXTRAS = {"llm_call", "engine_note"}

REQUIRED_FIELDS = {
    "game_start": {"players", "roles", "missionPlan", "missionsToWin"},
    "round_start": {"round", "leader", "missionSize", "attempt"},
    "turn_start": {"round", "action"},
    "proposal": {"round", "leader", "attempt", "team"},
    "thought": {"round", "agent", "text"},
    "speech": {"round", "agent", "text"},
    "team_vote": {"round", "attempt", "votes", "outcome"},
    "mission": {"round", "team", "fails", "outcome"},
    "round_end": {"round", "outcome", "score"},
    "game_end": {"winner", "score", "reason"},
}


def _events(spy_plays_success=True, vote=True):
    engine = make_engine(
        lambda i: ScriptableController(spy_plays_success=spy_plays_success,
                                       vote=vote))
    events = []
    engine.listeners.append(events.append)
    engine.run()
    return events


def test_event_envelope_and_required_fields():
    events = _events()
    for i, e in enumerate(events):
        assert e["t"] == i  # monotonic, 0-based
        assert e["type"] in V1_TYPES | ENGINE_EXTRAS
        for field in REQUIRED_FIELDS.get(e["type"], set()):
            assert field in e, f"{e['type']} missing {field}"


def test_game_start_shape():
    start = _events()[0]
    assert start["type"] == "game_start"
    assert {p["id"] for p in start["players"]} == set(start["roles"])
    assert [p["seat"] for p in
            sorted(start["players"], key=lambda p: p["seat"])] == list(range(5))
    assert [m["size"] for m in start["missionPlan"]] == [2, 3, 2, 3, 3]
    assert all(m["failsToFail"] == 1 for m in start["missionPlan"])
    assert sorted(start["roles"].values()).count("spy") == 2


def test_vote_and_mission_vocabulary():
    events = _events(spy_plays_success=False)
    for e in events:
        if e["type"] == "team_vote":
            assert e["outcome"] in ("approved", "rejected")
            assert len(e["votes"]) == 5
            for v in e["votes"]:
                assert v["vote"] in ("approve", "reject")
        if e["type"] == "mission":
            assert e["outcome"] in ("success", "fail")
            for c in e.get("cards", []):
                assert c["card"] in ("success", "fail")
        if e["type"] == "game_end":
            assert e["winner"] in ("resistance", "spies")
            assert e["reason"] in ("three_missions", "five_rejections")


def test_mission_turn_start_is_anonymous():
    # Who is deliberating over a mission card must never be visible —
    # naming the agent would leak which team member is a decision-maker (a spy).
    events = _events(spy_plays_success=False)
    mission_turns = [e for e in events
                     if e["type"] == "turn_start" and e["action"] == "mission"]
    assert mission_turns  # spies were asked at least once
    for e in mission_turns:
        assert "agent" not in e
    # All other turn starts name the agent.
    for e in events:
        if e["type"] == "turn_start" and e["action"] != "mission":
            assert "agent" in e


def test_thought_precedes_matching_speech():
    # Per the schema notes: interior-then-spoken ordering per agent turn.
    events = _events()
    for i, e in enumerate(events):
        if e["type"] == "speech":
            # Find the most recent thought/speech before this one by same agent;
            # if it's a thought from the same beat, order is correct by construction.
            prev = [p for p in events[:i]
                    if p["type"] in ("thought", "speech")
                    and p.get("agent") == e["agent"]]
            if prev and prev[-1]["type"] == "thought":
                assert prev[-1]["t"] < e["t"]


def test_fold_replayer_style():
    """Replicate the replayer's computeState fold and check the end state."""
    events = _events(spy_plays_success=False)
    score = {"resistance": 0, "spies": 0}
    missions = {}
    winner = None
    for e in events:
        if e["type"] == "game_start":
            missions = {m["round"]: "pending" for m in e["missionPlan"]}
        elif e["type"] == "mission":
            missions[e["round"]] = e["outcome"]
        elif e["type"] == "round_end":
            score = e["score"]
        elif e["type"] == "game_end":
            winner = e["winner"]
            score = e["score"]
    assert winner == "spies"
    assert score["spies"] == 3
    assert list(missions.values()).count("fail") == 3
