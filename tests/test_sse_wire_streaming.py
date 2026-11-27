from __future__ import annotations

import contextlib
import http.client
import http.server
import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from mitmproxy.test import tflow

from holon_coherence.mitm_addon import (
    _MAX_SSE_BUFFER_BYTES,
    MitmproxyAddon,
    extract_sse_content,
    flush_wire_logs,
)
from holon_coherence.proxy.steps.sse_tap import install_sse_tap


@contextlib.contextmanager
def _local_sse_server(chunks: list[bytes]) -> Iterator[int]:
    total_length = sum(len(chunk) for chunk in chunks)

    class _SSEHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length > 0:
                self.rfile.read(content_length)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Content-Length", str(total_length))
            self.send_header("Connection", "close")
            self.end_headers()
            for chunk in chunks:
                self.wfile.write(chunk)
                self.wfile.flush()

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = http.server.HTTPServer(("127.0.0.1", 0), _SSEHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _make_sse_tflow(url: str, payload: dict[str, Any], *, bridged: bool = False) -> Any:
    flow = tflow.tflow(resp=True)
    flow.request.method = "POST"
    flow.request.url = url
    flow.request.headers["content-type"] = "application/json"
    flow.request.content = json.dumps(payload).encode("utf-8")
    flow.response.status_code = 200
    flow.response.headers["content-type"] = "text/event-stream; charset=utf-8"
    flow.response.content = b""
    flow.is_gemini_bridged = bridged
    return flow


def _parse_gemini_sse_events(raw_bytes: bytes) -> list[dict[str, Any]]:
    text = raw_bytes.decode("utf-8")
    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        assert stripped.startswith("data: ")
        events.append(json.loads(stripped[len("data: ") :]))
    return events


def test_bridged_sse_fragmented_json_across_chunk_boundaries() -> None:
    flow = _make_sse_tflow(
        "http://localhost:11434/v1beta/models/gemma:streamGenerateContent?alt=sse",
        {"contents": [{"role": "user", "parts": [{"text": "run"}]}]},
        bridged=True,
    )
    install_sse_tap(flow, flow.response)

    full_stream = (
        b'data: {"choices":[{"index":0,"delta":{"role":"assistant","content":"Alpha "}}]}\n\n'
        b'data: {"choices":[{"index":0,"delta":{"content":"Beta"}}]}\n\n'
        b'data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,'
        b'"function":{"name":"read_file","arguments":"{\\"path\\":"}}]}}]}\n\n'
        b'data: {"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,'
        b'"function":{"arguments":"\\"a.py\\"}"}}]}}]}\n\n'
        b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}]}\n\n'
        b"data: [DONE]\n\n"
    )

    wire_slices = [
        full_stream[:3],
        full_stream[3:17],
        full_stream[17:41],
        *[full_stream[i : i + 1] for i in range(41, 80)],
        full_stream[80:145],
        full_stream[145:210],
        full_stream[210:],
    ]

    emitted: list[bytes] = []
    for part in wire_slices:
        emitted.append(flow.response.stream(part))
    emitted.append(flow.response.stream(b""))

    events = _parse_gemini_sse_events(b"".join(emitted))
    texts: list[str] = []
    function_calls: list[dict[str, Any]] = []
    for event in events:
        for cand in event.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                if "text" in part:
                    texts.append(part["text"])
                if "functionCall" in part:
                    function_calls.append(part["functionCall"])

    assert "".join(texts) == "Alpha Beta"
    assert function_calls == [{"name": "read_file", "args": {"path": "a.py"}}]
    assert b"".join(flow.sse_chunks) == b"".join(emitted)


def test_bridged_sse_split_multibyte_utf8_across_chunks() -> None:
    flow = _make_sse_tflow(
        "http://localhost:11434/v1beta/models/gemma:streamGenerateContent?alt=sse",
        {"contents": [{"role": "user", "parts": [{"text": "utf8"}]}]},
        bridged=True,
    )
    install_sse_tap(flow, flow.response)

    expected_text = "café 日本語 🚀✨"
    raw_line = f'data: {{"choices":[{{"index":0,"delta":{{"content":"{expected_text}"}}}}]}}\n\n'.encode()

    emitted = [flow.response.stream(raw_line[i : i + 1]) for i in range(len(raw_line))]
    emitted.append(flow.response.stream(b""))

    combined_out = b"".join(emitted).decode("utf-8")
    assert "\ufffd" not in combined_out
    events = _parse_gemini_sse_events(b"".join(emitted))
    assert len(events) == 1
    assert events[0]["candidates"][0]["content"]["parts"][0]["text"] == expected_text
    assert b"".join(flow.sse_chunks).decode("utf-8") == combined_out


def test_bridged_sse_flushes_trailing_line_without_newline_on_eof() -> None:
    flow = _make_sse_tflow(
        "http://localhost:11434/v1beta/models/gemma:streamGenerateContent?alt=sse",
        {"contents": [{"role": "user", "parts": [{"text": "eof"}]}]},
        bridged=True,
    )
    install_sse_tap(flow, flow.response)

    trailing_line = b'data: {"choices":[{"index":0,"delta":{"content":"final token"},"finish_reason":"stop"}]}'
    assert flow.response.stream(trailing_line[:25]) == b""
    assert flow.response.stream(trailing_line[25:]) == b""
    assert flow.sse_chunks == []

    flushed = flow.response.stream(b"")
    events = _parse_gemini_sse_events(flushed)
    assert len(events) == 1
    assert events[0]["candidates"][0]["content"]["parts"][0]["text"] == "final token"
    assert events[0]["candidates"][0]["finishReason"] == "STOP"
    assert b"".join(flow.sse_chunks) == flushed

    assert flow.response.stream(b"") == b""
    assert b"".join(flow.sse_chunks) == flushed


def test_bridged_sse_invalid_utf8_at_eof_uses_replacement() -> None:
    flow = _make_sse_tflow(
        "http://localhost:11434/v1beta/models/gemma:streamGenerateContent?alt=sse",
        {"contents": [{"role": "user", "parts": [{"text": "bad-utf8"}]}]},
        bridged=True,
    )
    install_sse_tap(flow, flow.response)

    invalid_mid = b'data: {"choices":[{"index":0,"delta":{"content":"hi ' + b"\xff" + b'"}}]}\n\n'
    truncated_eof = b'data: {"choices":[{"index":0,"delta":{"content":"end ' + b"\xe2\x82"

    first_out = flow.response.stream(invalid_mid)
    second_out = flow.response.stream(truncated_eof)
    eof_out = flow.response.stream(b"")

    assert second_out == b""
    events = _parse_gemini_sse_events(first_out)
    assert events[0]["candidates"][0]["content"]["parts"][0]["text"] == "hi \ufffd"
    assert eof_out == b""


def test_wire_http_server_fragmented_sse_through_mitmproxy_tflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HOLON_PASSIVE_MONITORING", raising=False)
    monkeypatch.setenv("ENABLE_WIRE_LOGGING", "0")
    monkeypatch.setenv("HOLON_LOCAL_MODEL", "qwen-local")

    raw_sse = (
        'data: {"choices":[{"index":0,"delta":{"role":"assistant","content":"Héllo "}}]}\n\n'
        'data: {"choices":[{"index":0,"delta":{"content":"世界 🌍"},"finish_reason":"stop"}],'
        '"usage":{"prompt_tokens":12,"completion_tokens":5,"total_tokens":17}}\n\n'
        "data: [DONE]\n\n"
    ).encode()
    server_chunks = [raw_sse[i : i + 5] for i in range(0, len(raw_sse), 5)]

    addon = MitmproxyAddon(cache_dir=str(tmp_path / "cache"), wire_log_dir=str(tmp_path / "wire"))
    flow = _make_sse_tflow(
        "http://localhost:11434/v1beta/models/gemma:streamGenerateContent?alt=sse",
        {"contents": [{"role": "user", "parts": [{"text": "greet"}]}]},
    )

    with _local_sse_server(server_chunks) as port:
        addon.request(flow)
        assert getattr(flow, "is_gemini_bridged", False) is True
        addon.responseheaders(flow)

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request(
                "POST",
                "/v1/chat/completions",
                body=flow.request.content,
                headers={"Content-Type": "application/json"},
            )
            resp = conn.getresponse()
            assert resp.status == 200
            emitted: list[bytes] = []
            while True:
                piece = resp.read(3)
                if not piece:
                    emitted.append(flow.response.stream(b""))
                    break
                emitted.append(flow.response.stream(piece))
        finally:
            conn.close()

    addon.response(flow)
    flush_wire_logs()

    events = _parse_gemini_sse_events(b"".join(emitted))
    texts = [
        part["text"]
        for event in events
        for cand in event.get("candidates", [])
        for part in cand.get("content", {}).get("parts", [])
        if "text" in part
    ]
    assert "".join(texts) == "Héllo 世界 🌍"
    assert any(
        event.get("usageMetadata") == {"promptTokenCount": 12, "candidatesTokenCount": 5, "totalTokenCount": 17}
        for event in events
    )
    assert b"".join(flow.sse_chunks) == b"".join(emitted)
    assert addon.metrics.total_input_tokens == 12
    assert addon.metrics.total_output_tokens == 5


def test_wire_http_server_non_bridged_sse_split_utf8_passthrough(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HOLON_PASSIVE_MONITORING", raising=False)
    monkeypatch.setenv("ENABLE_WIRE_LOGGING", "0")

    raw_sse = (
        'data: {"choices":[{"delta":{"content":"Héllo "}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"世界 🌍"}}]}\n\n'
        "data: [DONE]\n\n"
    ).encode()
    server_chunks = [raw_sse[i : i + 4] for i in range(0, len(raw_sse), 4)]

    addon = MitmproxyAddon(cache_dir=str(tmp_path / "cache"), wire_log_dir=str(tmp_path / "wire"))
    flow = _make_sse_tflow(
        "https://api.openai.com/v1/chat/completions",
        {"model": "gpt-4o", "stream": True, "messages": [{"role": "user", "content": "hi"}]},
    )

    with _local_sse_server(server_chunks) as port:
        addon.request(flow)
        assert getattr(flow, "is_gemini_bridged", False) is False
        addon.responseheaders(flow)

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request(
                "POST",
                "/v1/chat/completions",
                body=flow.request.content,
                headers={"Content-Type": "application/json"},
            )
            resp = conn.getresponse()
            assert resp.status == 200
            emitted: list[bytes] = []
            while True:
                piece = resp.read(2)
                if not piece:
                    emitted.append(flow.response.stream(b""))
                    break
                emitted.append(flow.response.stream(piece))
        finally:
            conn.close()

    addon.response(flow)
    flush_wire_logs()

    assert b"".join(emitted) == raw_sse
    assert b"".join(flow.sse_chunks) == raw_sse
    assert extract_sse_content(b"".join(flow.sse_chunks).decode("utf-8"), "openai") == "Héllo 世界 🌍"


def test_sse_tap_respects_max_buffer_bytes_and_existing_stream() -> None:
    flow = _make_sse_tflow(
        "https://api.openai.com/v1/chat/completions",
        {"model": "gpt-4o", "stream": True, "messages": [{"role": "user", "content": "cap"}]},
    )
    seen: list[bytes] = []

    def downstream(chunk: bytes) -> bytes:
        seen.append(chunk)
        return chunk.upper()

    flow.response.stream = downstream
    install_sse_tap(flow, flow.response)
    flow.sse_bytes = _MAX_SSE_BUFFER_BYTES - 4

    assert flow.response.stream(b"abcd") == b"ABCD"
    assert flow.response.stream(b"efgh") == b"EFGH"
    assert flow.response.stream(b"") == b""
    assert flow.sse_chunks == [b"abcd"]
    assert flow.sse_bytes == _MAX_SSE_BUFFER_BYTES + 4
    assert seen == [b"abcd", b"efgh", b""]
