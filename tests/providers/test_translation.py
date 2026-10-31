"""Unit tests for translation module."""

from __future__ import annotations

import json

from holon_coherence.providers.translation import (
    translate_gemini_to_openai_request,
    translate_openai_sse_chunk_to_gemini,
    translate_openai_to_gemini_response,
)


def test_translate_gemini_to_openai_request() -> None:
    gemini_req = {
        "system_instruction": {"parts": [{"text": "You are a test assistant."}]},
        "contents": [
            {"role": "user", "parts": [{"text": "Hello"}]},
            {
                "role": "model",
                "parts": [{"functionCall": {"name": "lookup", "args": {"key": "value"}}}],
            },
            {
                "role": "user",
                "parts": [{"functionResponse": {"name": "lookup", "response": {"result": "success"}}}],
            },
        ],
        "tools": [
            {
                "functionDeclarations": [
                    {
                        "name": "lookup",
                        "description": "Look up key",
                        "parameters": {"type": "object", "properties": {"key": {"type": "string"}}},
                    }
                ]
            }
        ],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1000},
    }

    openai_req = translate_gemini_to_openai_request(gemini_req, model="gpt-4o")
    assert openai_req["model"] == "gpt-4o"
    assert openai_req["temperature"] == 0.7
    assert openai_req["max_tokens"] == 1000
    assert len(openai_req["messages"]) >= 3
    assert openai_req["messages"][0]["role"] == "system"
    assert "You are a test assistant." in openai_req["messages"][0]["content"]
    assert any(m.get("role") == "tool" for m in openai_req["messages"])
    assert len(openai_req.get("tools", [])) == 1


def test_translate_openai_to_gemini_response() -> None:
    openai_resp = {
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Result",
                    "tool_calls": [{"function": {"name": "echo", "arguments": '{"msg": "hi"}'}}],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    gemini_resp = translate_openai_to_gemini_response(openai_resp)
    assert len(gemini_resp["candidates"]) == 1
    cand = gemini_resp["candidates"][0]
    parts = cand["content"]["parts"]
    assert any("text" in p and p["text"] == "Result" for p in parts)
    assert any("functionCall" in p and p["functionCall"]["name"] == "echo" for p in parts)
    assert gemini_resp["usageMetadata"]["promptTokenCount"] == 10


def test_translate_openai_sse_chunk_to_gemini() -> None:
    chunk_raw = (
        "data: "
        + json.dumps(
            {
                "choices": [{"delta": {"content": "Hello stream"}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4},
            }
        )
        + "\n\n"
    )
    gemini_chunk = translate_openai_sse_chunk_to_gemini(chunk_raw)
    assert "data: " in gemini_chunk
    payload = json.loads(gemini_chunk.strip().split("data: ")[1])
    assert "candidates" in payload
    assert payload["candidates"][0]["content"]["parts"][0]["text"] == "Hello stream"
    assert payload["usageMetadata"]["promptTokenCount"] == 2
