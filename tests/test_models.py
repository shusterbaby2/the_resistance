from resistance.llm.models import (
    DEFAULT_EFFORT,
    DEFAULT_MODEL,
    resolve_effort,
    resolve_model,
    supports_adaptive_thinking,
    thinking_request_options,
)


def test_resolve_model_known_and_fallback():
    assert resolve_model("claude-sonnet-4-6") == "claude-sonnet-4-6"
    assert resolve_model("not-a-model", "claude-haiku-4-5") == "claude-haiku-4-5"
    assert resolve_model(None) == DEFAULT_MODEL


def test_resolve_effort_known_and_fallback():
    assert resolve_effort("high") == "high"
    assert resolve_effort("bogus", "low") == "low"
    assert resolve_effort(None) == DEFAULT_EFFORT


def test_adaptive_thinking_by_model():
    assert supports_adaptive_thinking("claude-opus-4-8")
    assert supports_adaptive_thinking("claude-sonnet-4-6")
    assert not supports_adaptive_thinking("claude-haiku-4-5")


def test_thinking_request_options_omits_haiku():
    assert thinking_request_options("claude-haiku-4-5", "high") == {}
    opts = thinking_request_options("claude-sonnet-4-6", "high")
    assert opts == {
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "high"},
    }
