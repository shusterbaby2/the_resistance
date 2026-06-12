"""Ollama adapter tests — stubbed transport, no server needed."""

import json

import pytest
from pydantic import BaseModel, ValidationError

from resistance.llm.factory import make_client
from resistance.llm.ollama import OllamaClient, _normalize_host


class Out(BaseModel):
    reasoning: str
    speech: str


def _stubbed(client: OllamaClient, content: str):
    """Capture the payload and return a canned Ollama response."""
    sent = {}

    def fake_post(payload):
        sent.update(payload)
        return {
            "message": {"content": content},
            "done_reason": "stop",
            "prompt_eval_count": 100,
            "eval_count": 42,
        }

    client._post = fake_post  # type: ignore[method-assign]
    return sent


def test_complete_parses_structured_output():
    client = OllamaClient(model="gpt-oss:20b", effort="medium")
    sent = _stubbed(client, json.dumps({"reasoning": "r", "speech": "s"}))
    parsed, record = client.complete(system="sys", user="usr", schema=Out)
    assert parsed == Out(reasoning="r", speech="s")
    assert sent["format"] == Out.model_json_schema()
    assert sent["messages"][0] == {"role": "system", "content": "sys"}
    assert record["usage"] == {"input_tokens": 100, "output_tokens": 42}
    assert record["stop_reason"] == "stop"


def test_gpt_oss_reasoning_effort_mapping():
    client = OllamaClient(model="gpt-oss:20b", effort="xhigh")
    sent = _stubbed(client, json.dumps({"reasoning": "r", "speech": "s"}))
    client.complete(system="s", user="u", schema=Out, thinking=True)
    assert sent["think"] == "high"  # xhigh collapses to Ollama's high
    client.complete(system="s", user="u", schema=Out, thinking=False)
    assert sent["think"] == "low"  # fast table talk stays at low


def test_non_gpt_oss_models_get_no_think_param():
    client = OllamaClient(model="llama3.1:8b", effort="high")
    sent = _stubbed(client, json.dumps({"reasoning": "r", "speech": "s"}))
    client.complete(system="s", user="u", schema=Out, thinking=True)
    assert "think" not in sent


def test_bad_json_raises_for_agent_retry_path():
    client = OllamaClient(model="gpt-oss:20b")
    _stubbed(client, "not json at all")
    with pytest.raises(ValidationError):
        client.complete(system="s", user="u", schema=Out)


def test_normalize_host():
    assert _normalize_host("localhost:11434") == "http://localhost:11434"
    assert _normalize_host("http://box:11434/") == "http://box:11434"


def test_factory_routes_by_provider(monkeypatch):
    assert isinstance(make_client("gpt-oss:20b"), OllamaClient)
    assert isinstance(make_client("qwen3:14b"), OllamaClient)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from resistance.llm.claude import ClaudeClient

    assert isinstance(make_client("claude-sonnet-4-6", "low"), ClaudeClient)
