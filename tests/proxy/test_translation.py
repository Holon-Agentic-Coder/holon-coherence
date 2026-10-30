"""Unit tests for Gemini <-> OpenAI bidirectional protocol translation."""

from __future__ import annotations

import json

from holon_coherence.proxy.translation.gemini_openai import (
    translate_gemini_to_openai_request,
    translate_openai_sse_chunk_to_gemini,
    translate_openai_to_gemini_response,
)


def test_translate_gemini_to_openai_request() -> None:
    gemini_req = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": "Hello model"}],
            }
        ],
        "systemInstruction": {
            "parts": [{"text": "You are a helpful assistant."}],
        },
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 1024,
        },
    }
    openai_req = translate_gemini_to_openai_request(gemini_req, model="gpt-4o")
    assert openai_req["model"] == "gpt-4o"
    assert openai_req["temperature"] == 0.7
    assert openai_req["max_tokens"] == 1024
    assert len(openai_req["messages"]) == 2
    assert openai_req["messages"][0]["role"] == "system"
    assert openai_req["messages"][0]["content"] == "You are a helpful assistant."
    assert openai_req["messages"][1]["role"] == "user"
    assert openai_req["messages"][1]["content"] == "Hello model"


def test_translate_openai_to_gemini_response() -> None:
    openai_resp = {
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Hello! How can I help you today?",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 15,
            "completion_tokens": 9,
            "total_tokens": 24,
        },
    }
    gemini_resp = translate_openai_to_gemini_response(openai_resp)
    assert len(gemini_resp["candidates"]) == 1
    candidate = gemini_resp["candidates"][0]
    assert candidate["finishReason"] == "STOP"
    assert candidate["content"]["parts"][0]["text"] == "Hello! How can I help you today?"
    assert gemini_resp["usageMetadata"]["promptTokenCount"] == 15
    assert gemini_resp["usageMetadata"]["candidatesTokenCount"] == 9


def test_translate_openai_sse_chunk_to_gemini() -> None:
    chunk_str = (
        'data: {"choices":[{"index":0,"delta":{"content":"Hi"},"finish_reason":null}]}\n\n'
        'data: {"choices":[{"index":0,"delta":{"content":" there"},"finish_reason":"stop"}]}\n\n'
        "data: [DONE]\n\n"
    )
    translated = translate_openai_sse_chunk_to_gemini(chunk_str)
    assert "data: " in translated
    lines = [line[len("data: ") :] for line in translated.strip().split("\n\n") if line.startswith("data: ")]
    parsed0 = json.loads(lines[0])
    assert parsed0["candidates"][0]["content"]["parts"][0]["text"] == "Hi"
    parsed1 = json.loads(lines[1])
    assert parsed1["candidates"][0]["content"]["parts"][0]["text"] == " there"
    assert parsed1["candidates"][0]["finishReason"] == "STOP"
