"""Unit tests for Anthropic payload normalisation."""

from __future__ import annotations

from unittest.mock import MagicMock

from holon_coherence.proxy.normalise.anthropic import normalize_anthropic_request


def test_normalize_anthropic_request_cloud_bypass() -> None:
    flow = MagicMock()
    flow.request.pretty_host = "api.anthropic.com"
    data = {
        "thinking": {"type": "enabled", "budget_tokens": 1024},
        "messages": [{"role": "user", "content": "hi"}],
    }
    normalized, was_normalized = normalize_anthropic_request(flow, data, is_local=False)
    assert was_normalized is False
    assert "thinking" in normalized


def test_normalize_anthropic_request_local_stripping() -> None:
    flow = MagicMock()
    flow.request.headers = {"anthropic-beta": "prompt-caching-2024-07-31"}
    data = {
        "thinking": {"type": "enabled", "budget_tokens": 1024},
        "output_config": {"format": "json"},
        "context_management": {"enabled": True},
        "system": [
            {
                "type": "text",
                "text": "System prompt",
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "User msg",
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            }
        ],
        "tools": [
            {
                "name": "tool1",
                "cache_control": {"type": "ephemeral"},
            }
        ],
    }

    normalized, was_normalized = normalize_anthropic_request(flow, data, is_local=True)
    assert was_normalized is True
    assert "thinking" not in normalized
    assert "output_config" not in normalized
    assert "context_management" not in normalized
    assert "cache_control" not in normalized["system"][0]
    assert "cache_control" not in normalized["messages"][0]["content"][0]
    assert "cache_control" not in normalized["tools"][0]
    assert "anthropic-beta" not in flow.request.headers
