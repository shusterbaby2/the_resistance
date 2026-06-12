"""Selectable models (Claude + local Ollama) and thinking-effort levels."""

from dataclasses import dataclass

DEFAULT_MODEL = "claude-opus-4-8"
DEFAULT_EFFORT = "medium"


@dataclass(frozen=True)
class ModelOption:
    id: str
    label: str
    hint: str = ""
    adaptive_thinking: bool = True
    provider: str = "anthropic"


MODEL_OPTIONS: list[ModelOption] = [
    ModelOption("claude-opus-4-8", "Opus 4.8", "Strongest reasoning"),
    ModelOption("claude-sonnet-4-6", "Sonnet 4.6", "Balanced speed and intelligence"),
    ModelOption(
        "claude-haiku-4-5",
        "Haiku 4.5",
        "Fastest, lowest cost — no adaptive thinking",
        adaptive_thinking=False,
    ),
    ModelOption(
        "gpt-oss:20b",
        "GPT-OSS 20B (local)",
        "Free, runs on your machine via Ollama — no API key",
        provider="ollama",
    ),
]

MODEL_BY_ID = {m.id: m for m in MODEL_OPTIONS}

EFFORT_OPTIONS: list[tuple[str, str]] = [
    ("low", "Low — snappiest turns"),
    ("medium", "Medium"),
    ("high", "High"),
    ("xhigh", "Extra high"),
    ("max", "Max — deepest thinking"),
]

MODEL_IDS = {m.id for m in MODEL_OPTIONS}
EFFORT_LEVELS = {e for e, _ in EFFORT_OPTIONS}


def resolve_model(value: str | None, default: str = DEFAULT_MODEL) -> str:
    if not value:
        return default
    if value in MODEL_IDS:
        return value
    if value.startswith("claude"):
        return default  # unknown Claude id: fall back rather than guess
    return value  # anything else is assumed to be a local Ollama model id


def provider_for(model_id: str) -> str:
    opt = MODEL_BY_ID.get(model_id)
    return opt.provider if opt is not None else "ollama"


def resolve_effort(value: str | None, default: str = DEFAULT_EFFORT) -> str:
    if value in EFFORT_LEVELS:
        return value
    return default


def supports_adaptive_thinking(model_id: str) -> bool:
    opt = MODEL_BY_ID.get(model_id)
    return opt.adaptive_thinking if opt is not None else True


def thinking_request_options(model_id: str, effort: str | None) -> dict:
    """API kwargs for adaptive thinking — omitted on models that reject it (e.g. Haiku)."""
    if not supports_adaptive_thinking(model_id):
        return {}
    opts: dict = {"thinking": {"type": "adaptive"}}
    if effort:
        opts["output_config"] = {"effort": effort}
    return opts


def models_for_lobby() -> list[dict]:
    return [
        {
            "id": m.id,
            "label": m.label,
            "hint": m.hint,
            "adaptiveThinking": m.adaptive_thinking,
            "provider": m.provider,
        }
        for m in MODEL_OPTIONS
    ]


def efforts_for_lobby() -> list[dict]:
    return [{"id": e, "label": label} for e, label in EFFORT_OPTIONS]
