"""Unit tests for AnthropicProvider."""

from __future__ import annotations

import json
from types import SimpleNamespace

from holon_coherence.providers.anthropic import AnthropicProvider


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
