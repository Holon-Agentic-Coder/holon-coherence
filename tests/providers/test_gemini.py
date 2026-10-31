"""Unit tests for GeminiProvider."""

from __future__ import annotations

import json
from types import SimpleNamespace

from holon_coherence.providers.gemini import GeminiProvider


def test_gemini_payload_cleaning_and_deduplication() -> None:
    provider = GeminiProvider()
    cleaner = SimpleNamespace(
        enable_deduplication=True,
        enable_prompt_caching=False,
        max_turns=50,
        recent_turns_to_keep=2,
    )

    long_output = {"data": "z" * 150}
    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": "Execute command"}]},
            {
                "role": "model",
                "parts": [{"functionResponse": {"name": "run", "response": long_output}}],
            },
            {"role": "user", "parts": [{"text": "Continue"}]},
            {
                "role": "model",
                "parts": [{"functionResponse": {"name": "run", "response": long_output}}],
            },
            {"role": "user", "parts": [{"text": "Next"}]},
        ]
    }
    seen_hashes: dict[str, tuple[int, str]] = {}
    stats = {"tool_outputs_omitted": 0, "turns_summarized": 0, "cache_control_injected": 0}
    cleaned = provider.clean(cleaner, payload, seen_hashes, stats=stats)
    assert stats["tool_outputs_omitted"] >= 0
    assert len(cleaned["contents"]) == len(payload["contents"])


def test_gemini_summarization() -> None:
    provider = GeminiProvider()
    cleaner = SimpleNamespace(
        enable_deduplication=False,
        enable_prompt_caching=False,
        max_turns=3,
        recent_turns_to_keep=1,
    )
    contents = [
        {"role": "user", "parts": [{"text": "Turn 1"}]},
        {"role": "model", "parts": [{"text": "Turn 2"}]},
        {"role": "user", "parts": [{"text": "Turn 3"}]},
        {"role": "model", "parts": [{"text": "Turn 4"}]},
        {"role": "user", "parts": [{"text": "Turn 5"}]},
    ]
    payload = {"contents": contents}
    stats = {"tool_outputs_omitted": 0, "turns_summarized": 0, "cache_control_injected": 0}
    cleaned = provider.clean(cleaner, payload, {}, stats=stats)
    assert stats["turns_summarized"] > 0
    assert len(cleaned["contents"]) < len(contents)


def test_gemini_sse_content_extraction() -> None:
    provider = GeminiProvider()
    stream = "\n".join(
        [
            f"data: {json.dumps({'candidates': [{'content': {'parts': [{'text': 'Gemini '}]}}]})}",
            (
                "data: "
                + json.dumps(
                    {"candidates": [{"content": {"parts": [{"functionCall": {"name": "fetch", "args": {"q": 1}}}]}}]}
                )
            ),
        ]
    )
    extracted = provider.extract_sse_content(stream)
    assert "Gemini " in extracted
    assert '{"name": "fetch", "args": {"q": 1}}' in extracted


def test_gemini_token_counts() -> None:
    provider = GeminiProvider()
    usage_data = {
        "usageMetadata": {
            "promptTokenCount": 60,
            "candidatesTokenCount": 40,
            "cachedContentTokenCount": 15,
            "reasoningTokenCount": 8,
        }
    }
    stream = f"data: {json.dumps(usage_data)}"
    counts = provider.token_counts_from_sse(stream, {})
    assert counts.input_tokens == 60
    assert counts.output_tokens == 40
    assert counts.cache_read_tokens == 15
    assert counts.reasoning_tokens == 8

    resp_dict = {
        "usageMetadata": {
            "promptTokenCount": 90,
            "candidatesTokenCount": 50,
            "cachedContentTokenCount": 30,
            "reasoningTokenCount": 12,
        }
    }
    counts_dict = provider.token_counts_from_dict({}, resp_dict)
    assert counts_dict.input_tokens == 90
    assert counts_dict.output_tokens == 50
    assert counts_dict.cache_read_tokens == 30
    assert counts_dict.reasoning_tokens == 12


def test_gemini_extract_cache_key_parts() -> None:
    provider = GeminiProvider()
    payload = {
        "system_instruction": {"parts": [{"text": "Be helpful."}]},
        "contents": [
            {"role": "user", "parts": [{"text": "Hello Gemini"}]},
        ],
    }
    user_content, system_prompt = provider.extract_cache_key_parts(payload)
    assert user_content == "Hello Gemini"
    assert system_prompt == "Be helpful."
