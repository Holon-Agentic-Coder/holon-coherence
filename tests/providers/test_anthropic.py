"""Unit tests for AnthropicProvider."""

from __future__ import annotations

import json
from types import SimpleNamespace

from holon_coherence.providers.anthropic import (
    AnthropicProvider,
    _iter_cache_control_holders,
    _parse_ttl_rank,
    count_existing_cache_controls,
    inject_anthropic_cache_control,
    sanitize_and_normalize_cache_controls,
)


def test_anthropic_payload_cleaning_dedup_and_cache_control() -> None:
    provider = AnthropicProvider()
    cleaner = SimpleNamespace(
        enable_deduplication=True,
        enable_prompt_caching=True,
        max_turns=50,
        recent_turns_to_keep=2,
    )

    long_output = "x" * 150
    payload = {
        "system": "You are a helpful assistant.",
        "messages": [
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "tool_1", "content": long_output}],
            },
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Acknowledged."}],
            },
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "tool_2", "content": long_output}],
            },
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Understood."}],
            },
            {
                "role": "user",
                "content": [{"type": "text", "text": "Final question"}],
            },
        ],
    }

    seen_hashes: dict[str, tuple[int, str]] = {}
    stats = {"tool_outputs_omitted": 0, "turns_summarized": 0, "cache_control_injected": 0}

    cleaned = provider.clean(cleaner, payload, seen_hashes, stats=stats)
    assert stats["tool_outputs_omitted"] >= 0
    assert stats["cache_control_injected"] > 0
    assert isinstance(cleaned["system"], list)
    assert any("cache_control" in b for b in cleaned["system"])


def test_anthropic_summarization() -> None:
    provider = AnthropicProvider()
    cleaner = SimpleNamespace(
        enable_deduplication=False,
        enable_prompt_caching=False,
        max_turns=4,
        recent_turns_to_keep=2,
    )
    messages = [
        {"role": "user", "content": "Turn 0"},
        {"role": "assistant", "content": "Turn 1"},
        {"role": "user", "content": "Turn 2"},
        {"role": "assistant", "content": "Turn 3"},
        {"role": "user", "content": "Turn 4"},
        {"role": "assistant", "content": "Turn 5"},
    ]
    payload = {"messages": messages}
    stats = {"tool_outputs_omitted": 0, "turns_summarized": 0, "cache_control_injected": 0}
    cleaned = provider.clean(cleaner, payload, {}, stats=stats)
    assert stats["turns_summarized"] > 0
    assert len(cleaned["messages"]) < len(messages)


def test_anthropic_sse_content_extraction() -> None:
    provider = AnthropicProvider()
    tool_start = {"type": "content_block_start", "content_block": {"type": "tool_use", "name": "read_file"}}
    lines = [
        f"data: {json.dumps(tool_start)}",
        (
            "data: "
            + json.dumps(
                {
                    "type": "content_block_delta",
                    "delta": {"type": "input_json_delta", "partial_json": '{"path": "foo.py"}'},
                }
            )
        ),
        f"data: {json.dumps({'type': 'content_block_stop'})}",
        f"data: {json.dumps({'type': 'content_block_start', 'content_block': {'type': 'text'}})}",
        f"data: {json.dumps({'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': 'Done!'}})}",
        f"data: {json.dumps({'type': 'content_block_stop'})}",
    ]
    extracted = provider.extract_sse_content("\n".join(lines))
    assert "read_file(" in extracted
    assert '{"path": "foo.py"}' in extracted
    assert "Done!" in extracted


def test_anthropic_token_counts_from_sse_and_dict() -> None:
    provider = AnthropicProvider()
    start_payload = {
        "type": "message_start",
        "message": {
            "usage": {
                "input_tokens": 100,
                "cache_read_input_tokens": 50,
                "cache_creation_input_tokens": 20,
            }
        },
    }
    delta_payload = {
        "type": "message_delta",
        "usage": {"output_tokens": 80, "thinking_tokens": 15},
    }
    stream = f"data: {json.dumps(start_payload)}\ndata: {json.dumps(delta_payload)}"
    counts = provider.token_counts_from_sse(stream, {})
    assert counts.input_tokens == 170
    assert counts.output_tokens == 80
    assert counts.cache_read_tokens == 50
    assert counts.cache_creation_tokens == 20
    assert counts.reasoning_tokens == 15

    resp_dict = {
        "usage": {
            "input_tokens": 100,
            "output_tokens": 40,
            "cache_read_input_tokens": 25,
            "cache_creation_input_tokens": 10,
            "thinking_tokens": 5,
        }
    }
    dict_counts = provider.token_counts_from_dict({}, resp_dict)
    assert dict_counts.input_tokens == 135
    assert dict_counts.output_tokens == 40
    assert dict_counts.cache_read_tokens == 25


def test_anthropic_extract_cache_key_parts() -> None:
    provider = AnthropicProvider()
    payload = {
        "system": [{"type": "text", "text": "System prompt text"}],
        "messages": [
            {"role": "user", "content": "Question 1"},
            {"role": "assistant", "content": "Answer 1"},
            {"role": "user", "content": [{"type": "text", "text": "Question 2"}]},
        ],
    }
    user_content, system_prompt = provider.extract_cache_key_parts(payload)
    assert "Question 1" in user_content
    assert "Question 2" in user_content
    assert system_prompt == "System prompt text"


def _assert_non_increasing_ttl_and_max_4(payload: dict) -> None:
    assert count_existing_cache_controls(payload) <= 4
    ranks = [
        _parse_ttl_rank(block.get("cache_control"))
        for _, block in _iter_cache_control_holders(payload, ("tools", "system", "messages"))
    ]
    assert ranks == sorted(ranks, reverse=True), f"TTL ranks not non-increasing: {ranks}"


def test_system_multi_block_cache_control_ttl_ordering() -> None:
    provider = AnthropicProvider()
    cleaner = SimpleNamespace(
        enable_deduplication=True,
        enable_prompt_caching=True,
        max_turns=50,
        recent_turns_to_keep=2,
    )
    payload = {
        "system": [
            {"type": "text", "text": "Block 0", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "Block 1", "cache_control": {"type": "ephemeral", "ttl": "5m"}},
            {"type": "text", "text": "Block 2", "cache_control": {"type": "ephemeral", "ttl": "1h"}},
        ],
        "messages": [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
            {"role": "user", "content": "Next"},
        ],
    }
    stats = {"tool_outputs_omitted": 0, "turns_summarized": 0, "cache_control_injected": 0}
    cleaned = provider.clean(cleaner, payload, {}, stats=stats)
    _assert_non_increasing_ttl_and_max_4(cleaned)
    assert cleaned["system"][2]["cache_control"].get("ttl") != "1h"


def test_tools_and_system_ttl_ordering_prevents_5m_before_1h() -> None:
    payload = {
        "system": [
            {"type": "text", "text": "System instructions", "cache_control": {"type": "ephemeral", "ttl": "1h"}},
        ],
        "tools": [
            {"name": "read_file", "description": "Read a file"},
        ],
        "messages": [
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": "First answer"},
        ],
    }
    stats = {"cache_control_injected": 0}
    cleaned = inject_anthropic_cache_control(payload, stats=stats)
    _assert_non_increasing_ttl_and_max_4(cleaned)
    assert cleaned["tools"][-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert cleaned["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_existing_valid_1h_then_5m_ttl_preserved_within_4_breakpoint_limit() -> None:
    payload = {
        "system": [
            {"type": "text", "text": "Sys 0", "cache_control": {"type": "ephemeral", "ttl": "1h"}},
            {"type": "text", "text": "Sys 1", "cache_control": {"type": "ephemeral", "ttl": "5m"}},
        ],
        "tools": [
            {"name": "tool_a", "description": "Tool A", "cache_control": {"type": "ephemeral", "ttl": "1h"}},
        ],
        "messages": [
            {"role": "user", "content": "Turn 1"},
            {"role": "assistant", "content": "Turn 2"},
            {"role": "user", "content": "Turn 3"},
        ],
    }
    stats = {"cache_control_injected": 0}
    cleaned = inject_anthropic_cache_control(payload, stats=stats)
    _assert_non_increasing_ttl_and_max_4(cleaned)
    assert cleaned["system"][0]["cache_control"]["ttl"] == "1h"
    assert cleaned["system"][1]["cache_control"]["ttl"] == "5m"
    assert cleaned["tools"][0]["cache_control"]["ttl"] == "1h"
    assert cleaned["messages"][-2]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert stats["cache_control_injected"] == 1


def test_invalid_ttl_values_and_excess_breakpoints_sanitized() -> None:
    payload = {
        "system": [
            {"type": "text", "text": "S0", "cache_control": {"type": "ephemeral", "ttl": "10m"}},
            {"type": "text", "text": "S1", "cache_control": {"type": "ephemeral", "ttl": None}},
            {"type": "text", "text": "S2", "cache_control": {"type": "ephemeral", "ttl": 3600}},
        ],
        "tools": [
            {"name": "t1", "cache_control": {"type": "ephemeral", "ttl": "5m"}},
            {"name": "t2", "cache_control": {"type": "invalid_type"}},
        ],
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "M0", "cache_control": {"type": "ephemeral"}},
                    {"type": "text", "text": "M1", "cache_control": {"type": "ephemeral", "ttl": "1h"}},
                ],
            }
        ],
    }
    sanitize_and_normalize_cache_controls(payload)
    _assert_non_increasing_ttl_and_max_4(payload)
    assert count_existing_cache_controls(payload) == 4
    assert "cache_control" not in payload["tools"][1]
    for _sec, block in _iter_cache_control_holders(payload):
        cc = block["cache_control"]
        assert cc["type"] == "ephemeral"
        if "ttl" in cc:
            assert cc["ttl"] in ("5m", "1h")
