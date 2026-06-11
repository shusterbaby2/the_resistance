"""Lobby config wiring — per-seat models and effort from browser start payload."""

import argparse

from resistance.cli import _build_lobby, _seat_llm_options
from resistance.llm.models import DEFAULT_EFFORT, DEFAULT_MODEL


def _args(**overrides):
    base = argparse.Namespace(
        seed=99,
        command="watch",
        offline=False,
        model=DEFAULT_MODEL,
        effort=DEFAULT_EFFORT,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def test_build_lobby_includes_model_catalog():
    lobby = _build_lobby(_args(), human=False)
    model_ids = {m["id"] for m in lobby["models"]}
    assert "claude-opus-4-8" in model_ids
    assert "claude-sonnet-4-6" in model_ids
    assert "claude-haiku-4-5" in model_ids
    assert all("model" in s and "effort" in s for s in lobby["seats"])


def test_seat_llm_options_from_start_payload():
    config = {
        "presets": [0, 1, 2, 3, 4],
        "models": [
            "claude-sonnet-4-6",
            "claude-haiku-4-5",
            "claude-opus-4-8",
            "claude-sonnet-4-6",
            "claude-haiku-4-5",
        ],
        "efforts": ["low", "medium", "high", "xhigh", "max"],
    }
    presets, models, efforts = _seat_llm_options(config, _args())
    assert presets == [0, 1, 2, 3, 4]
    assert models[1] == "claude-haiku-4-5"
    assert efforts[4] == "max"
