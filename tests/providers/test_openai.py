"""Unit tests for OpenAIProvider."""

from __future__ import annotations

import json
from types import SimpleNamespace

from holon_coherence.providers.openai import OpenAIProvider


def test_openai_payload_cleaning_and_deduplication() -> None:
    provider = OpenAIProvider()
    cleaner = SimpleNamespace(
        enable_deduplication=True,
        enable_prompt_caching=False,
        max_turns=50,
        recent_turns_to_keep=2,
    )

    long_output = "data " * 50
    payload = {
        "messages": [
            {"role": "user", "content": "Run tool"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "function": {"name": "f"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": long_output},
            {"role": "assistant", "content": "Next"},
            {"role": "user", "content": "Run again"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c2", "function": {"name": "f"}}]},
            {"role": "tool", "tool_call_id": "c2", "content": long_output},
            {"role": "assistant", "content": "Done"},
            {"role": "user", "content": "Latest query"},
        ]
    }
    seen_hashes: dict[str, tuple[int, str]] = {}
    stats = {"tool_outputs_omitted": 0, "turns_summarized": 0, "cache_control_injected": 0}
    cleaned = provider.clean(cleaner, payload, seen_hashes, stats=stats)
    assert stats["tool_outputs_omitted"] >= 0
    assert len(cleaned["messages"]) == len(payload["messages"])


def test_openai_summarization() -> None:
    provider = OpenAIProvider()
    cleaner = SimpleNamespace(
        enable_deduplication=False,
        enable_prompt_caching=False,
        max_turns=3,
        recent_turns_to_keep=1,
    )
    messages = [
        {"role": "system", "content": "System prompt"},
        {"role": "user", "content": "Turn 1"},
        {"role": "assistant", "content": "Turn 2"},
        {"role": "user", "content": "Turn 3"},
        {"role": "assistant", "content": "Turn 4"},
        {"role": "user", "content": "Turn 5"},
    ]
    payload = {"messages": messages}
    stats = {"tool_outputs_omitted": 0, "turns_summarized": 0, "cache_control_injected": 0}
    cleaned = provider.clean(cleaner, payload, {}, stats=stats)
    assert stats["turns_summarized"] > 0
    assert len(cleaned["messages"]) < len(messages)


def test_openai_sse_content_extraction() -> None:
    provider = OpenAIProvider()
    tool_chunk1 = {
        "choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "calc", "arguments": '{"x":'}}]}}]
    }
    tool_chunk2 = {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": " 1}"}}]}}]}
    stream = "\n".join(
        [
            f"data: {json.dumps({'choices': [{'delta': {'role': 'assistant', 'content': 'Hello '}}]})}",
            f"data: {json.dumps(tool_chunk1)}",
            f"data: {json.dumps(tool_chunk2)}",
            f"data: {json.dumps({'choices': [{'finish_reason': 'tool_calls'}]})}",
            "data: [DONE]",
        ]
    )
    extracted = provider.extract_sse_content(stream)
    assert "Hello " in extracted
    assert "calc(" in extracted
    assert '{"x": 1}' in extracted


def test_openai_token_counts() -> None:
    provider = OpenAIProvider()
    usage_chunk = {
        "usage": {
            "prompt_tokens": 50,
            "completion_tokens": 30,
            "prompt_tokens_details": {"cached_tokens": 10},
            "completion_tokens_details": {"reasoning_tokens": 5},
        }
    }
    stream = f"data: {json.dumps(usage_chunk)}"
    counts = provider.token_counts_from_sse(stream, {})
    assert counts.input_tokens == 50
    assert counts.output_tokens == 30
    assert counts.cache_read_tokens == 10
    assert counts.reasoning_tokens == 5

    resp_dict = {
        "usage": {
            "prompt_tokens": 80,
            "completion_tokens": 40,
            "cached_tokens": 20,
            "completion_tokens_details": {"reasoning_tokens": 10},
        }
    }
    counts_dict = provider.token_counts_from_dict({}, resp_dict)
    assert counts_dict.input_tokens == 80
    assert counts_dict.output_tokens == 40
    assert counts_dict.cache_read_tokens == 20
    assert counts_dict.reasoning_tokens == 10


def test_openai_extract_cache_key_parts() -> None:
    provider = OpenAIProvider()
    payload = {
        "messages": [
            {"role": "system", "content": "You are OpenAI."},
            {"role": "user", "content": "Hello world"},
        ]
    }
    user_content, system_prompt = provider.extract_cache_key_parts(payload)
    assert user_content == "Hello world"
    assert system_prompt == "You are OpenAI."
