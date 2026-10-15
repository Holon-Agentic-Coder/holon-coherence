"""Tests for mitm_addon metrics, dashboard, and host-local LLM protocol adapters (Beans 0043 & 0051)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from holon_coherence.mitm_addon import (
    CumulativeMetrics,
    MitmproxyAddon,
    is_local_target,
    normalize_anthropic_request,
    render_dashboard_html,
    translate_gemini_to_openai_request,
    translate_openai_sse_chunk_to_gemini,
    translate_openai_to_gemini_response,
)
from holon_coherence.payload_cleaner import CleaningResult


class DummyHeaders(dict):
    """Case-insensitive dictionary for headers mocking."""

    def get(self, key: str, default: str | None = None) -> str | None:
        target = key.lower()
        for k, v in self.items():
            if k.lower() == target:
                return v
        return default

    def __delitem__(self, key: str) -> None:
        target = key.lower()
        for k in list(self.keys()):
            if k.lower() == target:
                super().__delitem__(k)


class DummyRequest:
    def __init__(
        self,
        url: str = "http://localhost:8080/v1/messages",
        method: str = "POST",
        headers: dict[str, str] | None = None,
        text: str = "",
        host: str = "localhost",
        port: int = 8080,
        path: str = "/v1/messages",
    ) -> None:
        self.pretty_url = url
        self.url = url
        self.method = method
        self.headers = DummyHeaders(headers or {})
        self._text = text
        self.pretty_host = host
        self.host = host
        self.port = port
        self.path = path
        self.scheme = "http"

    def get_text(self) -> str:
        return self._text

    def set_text(self, text: str) -> None:
        self._text = text


class DummyResponse:
    def __init__(
        self,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self.headers = DummyHeaders(headers or {})
        self._text = text
        self.stream = None

    def get_text(self) -> str:
        return self._text

    def set_text(self, text: str) -> None:
        self._text = text

    @classmethod
    def make(cls, status_code: int, content: bytes, headers: dict[str, str] | None = None) -> DummyResponse:
        return cls(status_code=status_code, headers=headers or {}, text=content.decode("utf-8"))


class DummyFlow:
    def __init__(
        self,
        request: DummyRequest | None = None,
        response: DummyResponse | None = None,
    ) -> None:
        self.id = "flow-test-1"
        self.request = request or DummyRequest()
        self.response = response or DummyResponse()
        self.Response = DummyResponse
        self.provider = "unknown"
        self.raw_request_data = None
        self.req_data = None
        self.cleaner_result = None
        self.request_start_time = None
        self.response_headers_time = None
        self.first_chunk_time = None
        self.sse_chunks = None
        self.sse_bytes = 0
        self.is_cached = False
        self.is_gemini_bridged = False


class TestCumulativeMetrics:
    """Unit tests for CumulativeMetrics thread-safe collector (Bean 0043)."""

    def test_initial_state(self) -> None:
        m = CumulativeMetrics()
        d = m.to_dict()
        assert d["total_turns"] == 0
        assert d["total_requests"] == 0
        assert d["cache_hits"] == 0
        assert d["cache_misses"] == 0
        assert d["cache_hit_rate"] == 0.0
        assert d["tool_calls_pruned"] == 0
        assert d["tokens_reduced"] == 0
        assert d["chars_saved"] == 0
        assert d["avg_ttft_ms"] == 0.0
        assert d["avg_decode_throughput_tps"] == 0.0

    def test_record_cleaner(self) -> None:
        m = CumulativeMetrics()
        res = CleaningResult(
            payload={},
            tool_outputs_omitted=5,
            turns_summarized=2,
            cache_control_injected=3,
            chars_saved=400,
        )
        m.record_cleaner(res)
        d = m.to_dict()
        assert d["tool_calls_pruned"] == 5
        assert d["turns_summarized"] == 2
        assert d["cache_control_injected"] == 3
        assert d["chars_saved"] == 400
        assert d["tokens_reduced"] == 100

    def test_record_requests_and_hits(self) -> None:
        m = CumulativeMetrics()
        m.record_request()
        m.record_request()
        m.record_cache_hit()
        d = m.to_dict()
        assert d["total_requests"] == 2
        assert d["cache_hits"] == 1
        assert d["cache_misses"] == 1
        assert d["cache_hit_rate"] == 0.5
        assert d["total_turns"] == 1

    def test_record_response(self) -> None:
        m = CumulativeMetrics()
        m.record_response(input_tokens=100, output_tokens=50, cache_read_tokens=20, ttft=0.2, output_tps=25.0)
        m.record_response(input_tokens=200, output_tokens=100, cache_read_tokens=40, ttft=0.4, output_tps=35.0)
        d = m.to_dict()
        assert d["total_turns"] == 2
        assert d["total_input_tokens"] == 300
        assert d["total_output_tokens"] == 150
        assert d["total_cache_read_tokens"] == 60
        assert d["avg_ttft_ms"] == 300.0  # (200ms + 400ms) / 2
        assert d["avg_decode_throughput_tps"] == 30.0  # (25.0 + 35.0) / 2


class TestMetricsAndDashboardEndpoints:
    """Unit tests for intercepted /holon/api/metrics and /holon/ dashboard endpoints (Bean 0043)."""

    def test_metrics_api_endpoint(self) -> None:
        addon = MitmproxyAddon()
        addon.metrics.record_request()
        addon.metrics.record_cleaner(CleaningResult(payload={}, tool_outputs_omitted=7, chars_saved=800))

        flow = DummyFlow(
            request=DummyRequest(
                url="http://127.0.0.1:8080/holon/api/metrics",
                method="GET",
                path="/holon/api/metrics",
            )
        )
        addon.request(flow)

        assert flow.response.status_code == 200
        assert "application/json" in flow.response.headers["Content-Type"]
        body = json.loads(flow.response.get_text())
        assert body["tool_calls_pruned"] == 7
        assert body["tokens_reduced"] == 200
        assert body["total_requests"] == 1

    def test_metrics_api_endpoint_alias(self) -> None:
        addon = MitmproxyAddon()
        flow = DummyFlow(
            request=DummyRequest(
                url="http://127.0.0.1:8080/_holon/metrics",
                method="GET",
                path="/_holon/metrics",
            )
        )
        addon.request(flow)
        assert flow.response.status_code == 200
        body = json.loads(flow.response.get_text())
        assert "total_turns" in body

    def test_dashboard_web_endpoint(self) -> None:
        addon = MitmproxyAddon()
        flow = DummyFlow(
            request=DummyRequest(
                url="http://127.0.0.1:8080/holon/",
                method="GET",
                path="/holon/",
            )
        )
        addon.request(flow)

        assert flow.response.status_code == 200
        assert "text/html" in flow.response.headers["Content-Type"]
        html = flow.response.get_text()
        assert "Holon Coherence" in html
        assert "Tool Calls Pruned" in html
        assert "Tokens Reduced" in html
        assert "Cache Hit Rate" in html
        assert "Latency & Speed" in html
        assert "/holon/api/metrics" in html

    def test_render_dashboard_html_structure(self) -> None:
        html = render_dashboard_html()
        assert "<!DOCTYPE html>" in html
        assert "tool-calls-pruned" in html
        assert "tokens-reduced" in html
        assert "cache-hit-rate" in html
        assert "avg-ttft" in html


class TestIsLocalTarget:
    """Unit tests for host-local target detection (Bean 0051)."""

    def test_loopback_and_gateway_hosts(self) -> None:
        for h in ("localhost", "127.0.0.1", "::1", "127.0.0.1.nip.io", "host.docker.internal"):
            flow = DummyFlow(request=DummyRequest(host=h, url=f"http://{h}:8080/v1/messages"))
            assert is_local_target(flow) is True

    def test_cloud_hosts_not_local(self) -> None:
        anthropic_flow = DummyFlow(
            request=DummyRequest(host="api.anthropic.com", url="https://api.anthropic.com/v1/messages")
        )
        anthropic_flow.provider = "anthropic"
        assert is_local_target(anthropic_flow) is False

        gemini_flow = DummyFlow(
            request=DummyRequest(
                host="generativelanguage.googleapis.com",
                url="https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent",
            )
        )
        gemini_flow.provider = "gemini"
        assert is_local_target(gemini_flow) is False

    def test_configured_host_local_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_HOST_LOCAL_HOSTS", "192.168.1.50:8081,custom-host:11434")
        flow1 = DummyFlow(request=DummyRequest(host="192.168.1.50", port=8081))
        assert is_local_target(flow1) is True

        flow2 = DummyFlow(request=DummyRequest(host="custom-host", port=11434))
        assert is_local_target(flow2) is True

        flow_remote = DummyFlow(request=DummyRequest(host="192.168.1.99", port=8081))
        flow_remote.provider = "openai"
        assert is_local_target(flow_remote) is False


class TestAnthropicNormalizer:
    """Unit tests for Anthropic protocol normalization for host-local engines (Bean 0051)."""

    def test_normalizer_strips_vendor_constructs(self) -> None:
        data = {
            "model": "claude-3-opus",
            "thinking": {"type": "enabled", "budget_tokens": 1024},
            "output_config": {"effort": "high"},
            "context_management": {"enabled": True},
            "system": [{"type": "text", "text": "You are a coding assistant.", "cache_control": {"type": "ephemeral"}}],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Hello", "cache_control": {"type": "ephemeral"}},
                        {"type": "text", "text": "World"},
                    ],
                }
            ],
            "tools": [
                {
                    "name": "run_command",
                    "description": "Run shell command",
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        }
        headers = {
            "anthropic-beta": "thinking-2024-11-04,prompt-caching-2024-07-31",
            "Content-Type": "application/json",
        }
        flow = DummyFlow(request=DummyRequest(host="localhost", headers=headers))

        cleaned, modified = normalize_anthropic_request(flow, data, is_local=True)
        assert modified is True
        assert "thinking" not in cleaned
        assert "output_config" not in cleaned
        assert "context_management" not in cleaned
        assert "cache_control" not in cleaned["system"][0]
        assert "cache_control" not in cleaned["messages"][0]["content"][0]
        assert "cache_control" not in cleaned["tools"][0]
        assert "anthropic-beta" not in flow.request.headers
        assert flow.request.headers.get("Content-Type") == "application/json"

    def test_normalizer_skips_cloud_requests(self) -> None:
        data = {
            "model": "claude-3-opus",
            "thinking": {"type": "enabled", "budget_tokens": 1024},
        }
        flow = DummyFlow(request=DummyRequest(host="api.anthropic.com"))
        flow.provider = "anthropic"

        cleaned, modified = normalize_anthropic_request(flow, data, is_local=False)
        assert modified is False
        assert "thinking" in cleaned


class TestGeminiOpenAIBridge:
    """Unit tests for bidirectional Gemini v1beta <-> OpenAI ChatCompletions bridge (Bean 0051)."""

    def test_request_translation_basic_messages(self) -> None:
        gemini_req = {
            "systemInstruction": {"parts": [{"text": "System prompt."}]},
            "contents": [
                {"role": "user", "parts": [{"text": "Hello model"}]},
                {"role": "model", "parts": [{"text": "Hello user"}]},
            ],
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 2048,
                "topP": 0.95,
                "stopSequences": ["###"],
            },
        }
        openai_req = translate_gemini_to_openai_request(gemini_req, model="qwen2.5-coder")
        assert openai_req["model"] == "qwen2.5-coder"
        assert openai_req["temperature"] == 0.7
        assert openai_req["max_tokens"] == 2048
        assert openai_req["top_p"] == 0.95
        assert openai_req["stop"] == ["###"]

        messages = openai_req["messages"]
        assert len(messages) == 3
        assert messages[0] == {"role": "system", "content": "System prompt."}
        assert messages[1] == {"role": "user", "content": "Hello model"}
        assert messages[2] == {"role": "assistant", "content": "Hello user"}

    def test_request_translation_tool_declarations_and_calls(self) -> None:
        gemini_req = {
            "tools": [
                {
                    "functionDeclarations": [
                        {
                            "name": "run_command",
                            "description": "Execute bash command",
                            "parameters": {
                                "type": "OBJECT",
                                "properties": {"cmd": {"type": "STRING"}},
                                "required": ["cmd"],
                            },
                        }
                    ]
                }
            ],
            "contents": [
                {
                    "role": "model",
                    "parts": [{"functionCall": {"name": "run_command", "args": {"cmd": "ls -la"}}}],
                },
                {
                    "role": "user",
                    "parts": [{"functionResponse": {"name": "run_command", "response": {"output": "total 0"}}}],
                },
            ],
        }
        openai_req = translate_gemini_to_openai_request(gemini_req)
        assert len(openai_req["tools"]) == 1
        tool = openai_req["tools"][0]
        assert tool["type"] == "function"
        assert tool["function"]["name"] == "run_command"
        assert tool["function"]["parameters"]["required"] == ["cmd"]

        messages = openai_req["messages"]
        assert len(messages) == 2
        # Assistant tool call
        assert messages[0]["role"] == "assistant"
        assert len(messages[0]["tool_calls"]) == 1
        tc = messages[0]["tool_calls"][0]
        assert tc["function"]["name"] == "run_command"
        assert json.loads(tc["function"]["arguments"]) == {"cmd": "ls -la"}

        # Tool response
        assert messages[1]["role"] == "tool"
        assert messages[1]["name"] == "run_command"
        assert json.loads(messages[1]["content"]) == {"output": "total 0"}
        assert tc["id"] == messages[1]["tool_call_id"]

    def test_request_translation_multi_turn_tool_call_id_alignment(self) -> None:
        gemini_req = {
            "contents": [
                {
                    "role": "model",
                    "parts": [{"functionCall": {"name": "run_command", "args": {"cmd": "ls"}}}],
                },
                {
                    "role": "user",
                    "parts": [{"functionResponse": {"name": "run_command", "response": {"output": "file.txt"}}}],
                },
                {
                    "role": "model",
                    "parts": [{"functionCall": {"name": "run_command", "args": {"cmd": "cat file.txt"}}}],
                },
                {
                    "role": "user",
                    "parts": [{"functionResponse": {"name": "run_command", "response": {"output": "hello"}}}],
                },
            ]
        }
        openai_req = translate_gemini_to_openai_request(gemini_req)
        msgs = openai_req["messages"]
        assert len(msgs) == 4
        assert msgs[0]["tool_calls"][0]["id"] == msgs[1]["tool_call_id"]
        assert msgs[2]["tool_calls"][0]["id"] == msgs[3]["tool_call_id"]
        assert msgs[0]["tool_calls"][0]["id"] != msgs[2]["tool_calls"][0]["id"]

    def test_response_translation(self) -> None:
        openai_resp = {
            "id": "chatcmpl-42",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Running task...",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "grep_search",
                                    "arguments": '{"pattern": "def "}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {
                "prompt_tokens": 50,
                "completion_tokens": 25,
                "total_tokens": 75,
            },
        }
        gemini_resp = translate_openai_to_gemini_response(openai_resp)
        assert "candidates" in gemini_resp
        cand = gemini_resp["candidates"][0]
        assert cand["content"]["role"] == "model"
        parts = cand["content"]["parts"]
        assert len(parts) == 2
        assert parts[0]["text"] == "Running task..."
        assert parts[1]["functionCall"]["name"] == "grep_search"
        assert parts[1]["functionCall"]["args"] == {"pattern": "def "}
        assert cand["finishReason"] == "STOP"

        usage = gemini_resp["usageMetadata"]
        assert usage["promptTokenCount"] == 50
        assert usage["candidatesTokenCount"] == 25
        assert usage["totalTokenCount"] == 75

    def test_sse_chunk_translation(self) -> None:
        chunk = (
            'data: {"choices": [{"delta": {"content": "Hello "}}]}\n\n'
            'data: {"choices": [{"delta": {"content": "world!"}, "finish_reason": "stop"}]}\n\n'
            "data: [DONE]\n\n"
        )
        translated = translate_openai_sse_chunk_to_gemini(chunk)
        assert "data: " in translated
        lines = [line.strip() for line in translated.split("\n") if line.startswith("data: ")]
        assert len(lines) == 2

        first_data = json.loads(lines[0][len("data: ") :])
        assert first_data["candidates"][0]["content"]["parts"][0]["text"] == "Hello "

        second_data = json.loads(lines[1][len("data: ") :])
        assert second_data["candidates"][0]["content"]["parts"][0]["text"] == "world!"
        assert second_data["candidates"][0]["finishReason"] == "STOP"

    def test_gemini_bridge_model_from_url_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AGY_MODEL", raising=False)
        monkeypatch.delenv("HOLON_LOCAL_MODEL", raising=False)
        addon = MitmproxyAddon()
        req_body = {"contents": [{"role": "user", "parts": [{"text": "Hello"}]}]}
        flow = DummyFlow(
            request=DummyRequest(
                url="http://127.0.0.1:8080/v1beta/models/qwen2.5-coder:streamGenerateContent?alt=sse",
                method="POST",
                path="/v1beta/models/qwen2.5-coder:streamGenerateContent?alt=sse",
                headers={"Content-Type": "application/json"},
                text=json.dumps(req_body),
            )
        )
        flow.provider = "gemini"
        with patch("holon_coherence.mitm_addon.is_local_target", return_value=True):
            addon.request(flow)
        assert flow.is_gemini_bridged is True
        assert flow.request.path == "/v1/chat/completions"
        parsed_req = json.loads(flow.request.get_text())
        assert parsed_req["model"] == "qwen2.5-coder"
        assert parsed_req.get("stream") is True

    def test_sse_chunk_translation_usage_metadata(self) -> None:
        chunk = 'data: {"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}}\n\n'
        translated = translate_openai_sse_chunk_to_gemini(chunk)
        assert "data: " in translated
        parsed = json.loads(translated.strip()[len("data: ") :])
        assert "usageMetadata" in parsed
        assert parsed["usageMetadata"]["promptTokenCount"] == 12
        assert parsed["usageMetadata"]["candidatesTokenCount"] == 8
        assert parsed["usageMetadata"]["totalTokenCount"] == 20

    def test_sse_chunk_translation_tool_call_fragments_and_buffering(self) -> None:
        stream_state: dict[str, Any] = {}
        # Fragment 1: function name declared, empty arguments
        chunk1 = (
            'data: {"choices": [{"delta": {"tool_calls": ['
            '{"index": 0, "function": {"name": "run_command", "arguments": ""}}]}}]}\n\n'
        )
        out1 = translate_openai_sse_chunk_to_gemini(chunk1, stream_state=stream_state)
        # Should not emit candidate yet
        assert out1 == ""

        # Fragment 2: partial arguments
        chunk2 = (
            'data: {"choices": [{"delta": {"tool_calls": ['
            '{"index": 0, "function": {"arguments": "{\\"cmd\\": \\"ls\\"}"}}]}}]}\n\n'
        )
        out2 = translate_openai_sse_chunk_to_gemini(chunk2, stream_state=stream_state)
        assert out2 == ""

        # Fragment 3: finish_reason tool_calls
        chunk3 = 'data: {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}\n\n'
        out3 = translate_openai_sse_chunk_to_gemini(chunk3, stream_state=stream_state)
        assert "data: " in out3
        parsed = json.loads(out3.strip()[len("data: ") :])
        cand = parsed["candidates"][0]
        assert cand["finishReason"] == "STOP"
        part = cand["content"]["parts"][0]
        assert part["functionCall"]["name"] == "run_command"
        assert part["functionCall"]["args"] == {"cmd": "ls"}
