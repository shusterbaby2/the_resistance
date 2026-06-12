"""Builds the right LLMClient for a model id.

Provider imports stay deferred so a game never imports SDKs it doesn't use
(offline mode needs neither; an all-local game never touches anthropic).
"""

from .models import provider_for


def make_client(model: str, effort: str | None = None):
    if provider_for(model) == "ollama":
        from .ollama import OllamaClient

        return OllamaClient(model=model, effort=effort)
    from .claude import ClaudeClient

    return ClaudeClient(model=model, effort=effort)
