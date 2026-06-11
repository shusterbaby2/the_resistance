"""Claude adapter for the LLMClient interface."""

import time
from typing import Any, TypeVar

from pydantic import BaseModel

from .models import DEFAULT_MODEL, thinking_request_options

T = TypeVar("T", bound=BaseModel)


class ClaudeClient:
    def __init__(self, model: str = DEFAULT_MODEL, max_tokens: int = 4096,
                 effort: str | None = None):
        import anthropic  # deferred so offline mode never needs the package configured

        self._client = anthropic.Anthropic()
        self.model = model
        self.max_tokens = max_tokens
        self.effort = effort

    def complete(self, *, system: str, user: str, schema: type[T],
                 thinking: bool = False) -> tuple[T, dict[str, Any]]:
        kwargs: dict[str, Any] = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            # The system prompt is stable per agent per game; cache it so every
            # turn after the first reads the prefix instead of re-paying it.
            system=[{
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user}],
            output_format=schema,
            **(thinking_request_options(self.model, self.effort) if thinking else {}),
        )
        started = time.monotonic()
        response = self._client.messages.parse(**kwargs)
        duration_ms = int((time.monotonic() - started) * 1000)
        parsed = response.parsed_output
        if parsed is None:
            raise ValueError(
                f"model returned no parseable output (stop_reason={response.stop_reason})"
            )
        record = {
            "model": self.model,
            "thinking": thinking,
            "duration_ms": duration_ms,
            "stop_reason": response.stop_reason,
            "usage": response.usage.model_dump(),
            "output": parsed.model_dump(),
        }
        return parsed, record
