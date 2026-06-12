"""Prompt construction tests."""

import json

from resistance.agents.base import Action
from resistance.agents.prompts import ACTION_ASKS, build_system, build_user
from resistance.personality import PRESETS
from resistance.state import GameState, MissionRecord, PlayerState, Role
from resistance.views import build_seat_view


def _view_with_missions(missions: list[MissionRecord], *, round_num: int = 3):
    players = [
        PlayerState(seat=i, name=f"P{i}", role=Role.RESISTANCE if i < 3 else Role.SPY)
        for i in range(5)
    ]
    state = GameState(
        seed=1,
        players=players,
        round_num=round_num,
        leader_seat=3,
        current_team=[0, 1],
        missions=missions,
    )
    return build_seat_view(state, seat=3, transcript=[], beliefs=None)


def test_build_user_includes_mission_score():
    view = _view_with_missions([
        MissionRecord(round_num=1, team=[0, 1], fails=0, succeeded=True),
        MissionRecord(round_num=2, team=[0, 2, 3], fails=0, succeeded=True),
    ])
    user = build_user(view, Action.PROPOSE)
    json_blob = user.split("SCORE PRESSURE:")[0]
    state = json.loads(
        json_blob.split(
            "STRUCTURED GAME STATE (ground truth — trust this over the talk):\n"
        )[1].strip()
    )
    assert state["score"] == {
        "resistance": 2,
        "spies": 0,
        "missions_to_win": 3,
    }


def test_build_user_score_pressure_at_resistance_match_point():
    view = _view_with_missions([
        MissionRecord(round_num=1, team=[0, 1], fails=0, succeeded=True),
        MissionRecord(round_num=2, team=[0, 2, 3], fails=0, succeeded=True),
    ])
    user = build_user(view, Action.PROPOSE)
    assert "SCORE PRESSURE:" in user
    assert "Resistance leads 2-0" in user
    assert "one more successful mission" in user


def test_build_user_no_score_pressure_early_game():
    view = _view_with_missions([
        MissionRecord(round_num=1, team=[0, 1], fails=0, succeeded=True),
    ])
    user = build_user(view, Action.DISCUSS)
    assert "SCORE PRESSURE:" not in user


def test_system_prompt_demands_substantive_talk():
    names = {i: f"P{i}" for i in range(5)}
    for role, spies in ((Role.RESISTANCE, []), (Role.SPY, [2])):
        system = build_system(seat=0, persona=PRESETS[0], view_role=role,
                              fellow_spies=spies, seat_names=names)
        assert "Table talk rules" in system
        assert "No filler" in system


def test_discuss_ask_pushes_accusations_over_banter():
    ask = ACTION_ASKS[Action.DISCUSS]
    assert "accuse" in ask.lower()
    assert "stay quiet" in ask
