"""Ollama adapter for the LLMClient interface — local models, no API key.

Talks to the Ollama HTTP API (default http://localhost:11434) with stdlib
urllib so no new dependency is needed. Structured output uses Ollama's
`format` parameter, which constrains generation to the pydantic JSON schema.
"""

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

DEFAULT_HOST = "http://localhost:11434"

# gpt-oss reasoning levels; the game's five effort steps collapse onto three.
_GPT_OSS_EFFORT = {"low": "low", "medium": "medium", "high": "high",
                   "xhigh": "high", "max": "high"}


def _normalize_host(host: str) -> str:
    host = host.rstrip("/")
    if "://" not in host:
        host = "http://" + host
    return host


class OllamaClient:
    def __init__(self, model: str = "gpt-oss:20b", effort: str | None = None,
                 host: str | None = None, timeout: float = 300.0):
        self.model = model
        self.effort = effort
        self.host = _normalize_host(
            host or os.environ.get("OLLAMA_HOST") or DEFAULT_HOST)
        self.timeout = timeout

    def _payload(self, *, system: str, user: str, schema: type[T],
                 thinking: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": schema.model_json_schema(),
            # Keep the model loaded for a whole game session, including the
            # pauses while the human reads and types.
            "keep_alive": "30m",
        }
        if "gpt-oss" in self.model:
            # gpt-oss cannot stop reasoning, but the effort is tunable: stay
            # at "low" for fast table talk, raise it for the big decisions.
            level = _GPT_OSS_EFFORT.get(self.effort or "medium", "medium")
            payload["think"] = level if thinking else "low"
        return payload

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.host}/api/chat",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read()).get("error", "")
            except Exception:
                detail = str(exc.reason)
            if exc.code == 404 and "not found" in detail:
                raise RuntimeError(
                    f"Ollama model {self.model!r} is not installed — run "
                    f"`ollama pull {self.model}`"
                ) from exc
            raise RuntimeError(f"Ollama error ({exc.code}): {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"cannot reach Ollama at {self.host} — is `ollama serve` "
                "running? (set OLLAMA_HOST if it lives elsewhere)"
            ) from exc

    def complete(self, *, system: str, user: str, schema: type[T],
                 thinking: bool = False) -> tuple[T, dict[str, Any]]:
        payload = self._payload(system=system, user=user, schema=schema,
                                thinking=thinking)
        started = time.monotonic()
        data = self._post(payload)
        duration_ms = int((time.monotonic() - started) * 1000)
        content = (data.get("message") or {}).get("content") or ""
        # Invalid/empty JSON raises ValidationError -> the agent's retry path.
        parsed = schema.model_validate_json(content)
        record = {
            "model": self.model,
            "thinking": thinking,
            "duration_ms": duration_ms,
            "stop_reason": data.get("done_reason"),
            "usage": {
                "input_tokens": data.get("prompt_eval_count"),
                "output_tokens": data.get("eval_count"),
            },
            "output": parsed.model_dump(),
        }
        return parsed, record
