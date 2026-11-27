from __future__ import annotations

import json
from typing import Any

import pytest

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


def _parse_gemini_sse(raw: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        assert stripped.startswith("data: ")
        events.append(json.loads(stripped[len("data: ") :]))
    return events


def test_translate_openai_sse_chunk_reassembles_split_mid_json_lines() -> None:
    full_stream = (
        'data: {"choices":[{"index":0,"delta":{"role":"assistant","content":"Alpha "}}]}\n\n'
        'data: {"choices":[{"index":0,"delta":{"content":"Beta"}}]}\n\n'
        'data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,'
        '"function":{"name":"read_file","arguments":"{\\"path\\":"}}]}}]}\n\n'
        'data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,'
        '"function":{"arguments":"\\"a.py\\"}"}}]}}]}\n\n'
        'data: {"choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}]}\n\n'
        "data: [DONE]\n\n"
    )
    slices = [
        full_stream[:2],
        full_stream[2:6],
        full_stream[6:25],
        *[full_stream[i : i + 1] for i in range(25, 60)],
        full_stream[60:130],
        full_stream[130:205],
        full_stream[205:],
    ]

    state: dict[str, Any] = {}
    outputs: list[str] = []
    for piece in slices:
        outputs.append(translate_openai_sse_chunk_to_gemini(piece, stream_state=state))

    assert outputs[0] == ""
    assert outputs[1] == ""
    assert outputs[2] == ""
    assert state.get("line_buffer", "") == ""

    events = _parse_gemini_sse("".join(outputs))
    texts: list[str] = []
    function_calls: list[dict[str, Any]] = []
    finish_reasons: list[str] = []
    for event in events:
        for cand in event.get("candidates", []):
            if "finishReason" in cand:
                finish_reasons.append(cand["finishReason"])
            for part in cand.get("content", {}).get("parts", []):
                if "text" in part:
                    texts.append(part["text"])
                if "functionCall" in part:
                    function_calls.append(part["functionCall"])

    assert "".join(texts) == "Alpha Beta"
    assert function_calls == [{"name": "read_file", "args": {"path": "a.py"}}]
    assert finish_reasons == ["STOP"]


def test_translate_openai_sse_chunk_flushes_trailing_line_on_eof() -> None:
    trailing_line = 'data: {"choices":[{"index":0,"delta":{"content":"tail"},"finish_reason":"stop"}]}'
    state: dict[str, Any] = {}

    assert translate_openai_sse_chunk_to_gemini(trailing_line[:20], stream_state=state) == ""
    assert translate_openai_sse_chunk_to_gemini(trailing_line[20:], stream_state=state) == ""

    flushed = translate_openai_sse_chunk_to_gemini("", stream_state=state, flush=True)
    events = _parse_gemini_sse(flushed)
    assert len(events) == 1
    assert events[0]["candidates"][0]["content"]["parts"][0]["text"] == "tail"
    assert events[0]["candidates"][0]["finishReason"] == "STOP"

    assert translate_openai_sse_chunk_to_gemini("", stream_state=state, flush=True) == ""


@pytest.mark.parametrize("finish_reason", ["stop", "tool_calls", "length", "content_filter", "function_call"])
def test_streaming_and_non_streaming_finish_reason_parity(finish_reason: str) -> None:
    non_streaming = translate_openai_to_gemini_response(
        {
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "done"},
                    "finish_reason": finish_reason,
                }
            ]
        }
    )
    chunk_raw = (
        "data: "
        + json.dumps(
            {
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": "done"},
                        "finish_reason": finish_reason,
                    }
                ]
            }
        )
        + "\n\n"
    )
    streaming_raw = translate_openai_sse_chunk_to_gemini(chunk_raw, stream_state={})
    streaming_events = _parse_gemini_sse(streaming_raw)
    assert len(streaming_events) == 1

    non_streaming_reason = non_streaming["candidates"][0]["finishReason"]
    streaming_reason = streaming_events[0]["candidates"][0]["finishReason"]
    assert streaming_reason == non_streaming_reason

    if finish_reason == "length":
        assert streaming_reason == "MAX_TOKENS"
    elif finish_reason in ("stop", "tool_calls"):
        assert streaming_reason == "STOP"
