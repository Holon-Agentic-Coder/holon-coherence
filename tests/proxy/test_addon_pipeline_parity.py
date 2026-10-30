"""Characterization (parity) suite for the ``MitmproxyAddon`` hook pipelines.

Each scenario drives a real ``MitmproxyAddon`` through ``request`` / ``responseheaders`` /
``response`` and reduces every observable side effect -- the response written to the flow, the flow
attributes the hooks set, the addon counters, the cumulative metrics snapshot, the wire-log records in
``transactions.jsonl``, the telemetry lines and the addon log records -- into a JSON-serialisable
observation. Timing-dependent values are masked to their formatting class. The observations are
compared against ``fixtures/addon_parity_golden.json``, which was captured from the pre-refactor
monolithic hooks, so any drift in wire-level behaviour fails here.

The payloads below are functional regression inputs only. No token-reduction efficacy, scorecard or
benchmark number is derived from them, which is the use the zero-synthetic-data rule restricts.

Regenerate the golden file (only when a behaviour change is intended) with an inline variable:
``HOLON_PARITY_REGEN=1 uv run pytest tests/proxy/test_addon_pipeline_parity.py``.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from holon_coherence.mitm_addon import MitmproxyAddon, flush_wire_logs

GOLDEN_PATH = Path(__file__).parent / "fixtures" / "addon_parity_golden.json"

_FLOAT_RE = re.compile(r"^-?\d+\.(\d+)$")
_TIMING_HEADERS = frozenset(
    {
        "x-holon-ttft-ms",
        "x-holon-prefill-tps",
        "x-holon-tail-prefill-tps",
        "x-holon-decode-time-sec",
        "x-holon-output-tps",
        "x-holon-total-time-ms",
    }
)
_TIMING_METRIC_MARKERS = ("ttft", "tps", "time", "throughput", "speed")
_DECIMAL_RE = re.compile(r"\d+\.\d+")

_ENV_TO_CLEAR = (
    "HOLON_PASSIVE_MONITORING",
    "COHERENCE_TOKEN_REDUCTION",
    "HOLON_HOST_LOCAL_HOSTS",
    "HOLON_PROXY_PORT",
    "HOLON_IN_CONTAINER",
    "AGY_MODEL",
    "HOLON_LOCAL_MODEL",
    "HOLON_AGENT_ID",
    "HOLON_ROLE",
)


class ParityRequest:
    """Duck-typed ``mitmproxy.http.Request`` whose ``pretty_url`` follows host/port/path edits."""

    def __init__(self, url: str, method: str = "POST", text: str = "", headers: dict[str, str] | None = None):
        parts = urlsplit(url)
        self.scheme = parts.scheme
        self.host = parts.hostname or ""
        self.port = parts.port or (443 if parts.scheme == "https" else 80)
        self.path = parts.path + (f"?{parts.query}" if parts.query else "")
        self.method = method
        self.headers = headers if headers is not None else {"Content-Type": "application/json"}
        self._text = text

    @property
    def pretty_host(self) -> str:
        return self.host

    @property
    def pretty_url(self) -> str:
        default_port = 443 if self.scheme == "https" else 80
        authority = self.host if self.port == default_port else f"{self.host}:{self.port}"
        return f"{self.scheme}://{authority}{self.path}"

    def get_text(self) -> str:
        return self._text

    def set_text(self, text: str) -> None:
        self._text = text


class ParityResponse:
    def __init__(self, status_code: int = 200, text: str = "", headers: dict[str, str] | None = None):
        self.status_code = status_code
        self.headers = headers if headers is not None else {"Content-Type": "application/json"}
        self._text = text
        self.stream: Any = None

    def get_text(self) -> str:
        return self._text

    def set_text(self, text: str) -> None:
        self._text = text


class ExplodingResponse(ParityResponse):
    def get_text(self) -> str:
        raise RuntimeError("response body unavailable")


class ParityFlow:
    def __init__(self, request: ParityRequest, flow_id: str = "parity-flow"):
        self.id = flow_id
        self.request = request
        self.response: Any = None


# --------------------------------------------------------------------------------------------------
# Observation helpers
# --------------------------------------------------------------------------------------------------


def _mask_header(name: str, value: str) -> str:
    if name.lower() in _TIMING_HEADERS:
        match = _FLOAT_RE.match(value)
        if match:
            return f"<float:{len(match.group(1))}>"
    return value


def _headers_of(obj: Any) -> dict[str, str] | None:
    headers = getattr(obj, "headers", None)
    if headers is None:
        return None
    return {str(k): _mask_header(str(k), str(v)) for k, v in headers.items()}


def _response_of(flow: Any) -> dict[str, Any] | None:
    resp = getattr(flow, "response", None)
    if resp is None:
        return None
    try:
        body = resp.get_text()
    except Exception as exc:
        body = f"<get_text raised {type(exc).__name__}>"
    headers = _headers_of(resp)
    if headers is not None and "content-length" in headers:
        # The value tracks the body (which may embed the per-run tmp path), so pin consistency instead.
        consistent = int(headers["content-length"]) == len(body.encode("utf-8"))
        headers["content-length"] = "<body length>" if consistent else headers["content-length"]
    return {
        "type": type(resp).__name__,
        "status": resp.status_code,
        "body": body,
        "headers": headers,
    }


def _cleaner_of(flow: Any) -> Any:
    res = getattr(flow, "cleaner_result", "<unset>")
    if res is None or res == "<unset>":
        return res
    return {
        "chars_saved": res.chars_saved,
        "tool_outputs_omitted": res.tool_outputs_omitted,
        "turns_summarized": res.turns_summarized,
        "cache_control_injected": res.cache_control_injected,
        "payload_is_req_data": res.payload is getattr(flow, "req_data", None),
    }


def _flow_of(flow: Any) -> dict[str, Any]:
    req = flow.request
    out: dict[str, Any] = {
        "request": {
            "scheme": req.scheme,
            "host": req.host,
            "port": req.port,
            "path": req.path,
            "text": req.get_text(),
        },
        "cleaner_result": _cleaner_of(flow),
    }
    for attr in ("provider", "req_data", "raw_request_data", "is_cached", "is_gemini_bridged", "sse_bytes"):
        out[attr] = getattr(flow, attr, "<unset>")
    if hasattr(flow, "raw_request_data") and hasattr(flow, "req_data"):
        out["req_data_is_raw"] = flow.req_data is flow.raw_request_data
    for attr in ("request_start_time", "response_headers_time", "first_chunk_time", "last_chunk_time"):
        value = getattr(flow, attr, "<unset>")
        out[attr] = value if value in (None, "<unset>") else "<float>"
    chunks = getattr(flow, "sse_chunks", "<unset>")
    out["sse_chunks"] = chunks if chunks in (None, "<unset>") else [c.decode("utf-8") for c in chunks]
    return out


def _mask_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in metrics.items():
        if isinstance(value, float) and any(m in key for m in _TIMING_METRIC_MARKERS):
            out[key] = "<float>"
        else:
            out[key] = value
    return out


def _wire_records(wire_dir: Path) -> list[dict[str, Any]]:
    flush_wire_logs()
    path = wire_dir / "transactions.jsonl"
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        record["timestamp"] = "<ts>"
        record["timing"] = {
            k: ("<num>" if isinstance(v, int | float) and not isinstance(v, bool) else v)
            for k, v in record["timing"].items()
        }
        record["_key_order"] = list(json.loads(line).keys())
        records.append(record)
    return records


class Harness:
    """Owns one addon, captures telemetry/logs and turns a scenario into an observation."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
        self.tmp_path = tmp_path
        self.wire_dir = tmp_path / "wire"
        self.telemetry: list[str] = []
        self.caplog = caplog
        monkeypatch.setattr("holon_coherence.mitm_addon.log_telemetry", self.telemetry.append)
        self.addon = MitmproxyAddon(cache_dir=str(tmp_path / "cache"), wire_log_dir=str(self.wire_dir))
        caplog.set_level(logging.DEBUG, logger="holon_coherence")
        caplog.clear()
        self.chunks_out: list[str] = []

    def stream(self, flow: Any, chunks: list[bytes]) -> None:
        self.addon.responseheaders(flow)
        stream = getattr(flow.response, "stream", None)
        if callable(stream):
            for chunk in chunks:
                self.chunks_out.append(stream(chunk).decode("utf-8"))

    def observe(self, *flows: Any) -> dict[str, Any]:
        return {
            "flows": [{"response": _response_of(f), **_flow_of(f)} for f in flows],
            "streamed_chunks": self.chunks_out,
            "addon": {
                "total_requests": self.addon.total_requests,
                "cache_hits": self.addon.cache_hits,
                "default_passive": self.addon.default_passive,
                "wire_log_dir_is_default": self.addon.wire_log_dir == str(self.wire_dir),
            },
            "metrics": _mask_metrics(self.addon.metrics.to_dict()),
            "wire": _wire_records(self.wire_dir),
            "telemetry": [_DECIMAL_RE.sub("<d>", line) for line in self.telemetry],
            "logs": [
                (r.name, r.levelname, _DECIMAL_RE.sub("<d>", r.getMessage()))
                for r in self.caplog.records
                if r.name.startswith("holon_coherence")
            ],
        }


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> Harness:
    for name in _ENV_TO_CLEAR:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ENABLE_WIRE_LOGGING", "1")
    monkeypatch.setattr("holon_coherence.mitm_addon.in_container", lambda: False)
    monkeypatch.setattr("holon_coherence.mitm_addon.ctx", None)
    return Harness(tmp_path, monkeypatch, caplog)


# --------------------------------------------------------------------------------------------------
# Scenarios
# --------------------------------------------------------------------------------------------------

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

OPENAI_REQ = {
    "model": "gpt-4o",
    "messages": [
        {"role": "user", "content": "run task"},
        {"role": "assistant", "content": "ok", "tool_calls": [{"id": "c1", "function": {"name": "f"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "output " * 200},
        {"role": "assistant", "content": "ok2", "tool_calls": [{"id": "c2", "function": {"name": "f"}}]},
        {"role": "tool", "tool_call_id": "c2", "content": "output " * 200},
        {"role": "user", "content": "next"},
    ],
}
OPENAI_RESP = {
    "id": "chatcmpl-1",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "done"}}],
    "usage": {"prompt_tokens": 120, "completion_tokens": 7, "total_tokens": 127},
}
ANTHROPIC_REQ = {
    "model": "claude-x",
    "max_tokens": 64,
    "system": "be brief",
    "messages": [{"role": "user", "content": "hello"}],
}
ANTHROPIC_RESP = {
    "type": "message",
    "content": [{"type": "text", "text": "hi"}],
    "usage": {"input_tokens": 11, "output_tokens": 2},
}
GEMINI_REQ = {
    "systemInstruction": {"parts": [{"text": "sys"}]},
    "contents": [{"role": "user", "parts": [{"text": "hello"}]}],
}


def _post(url: str, body: Any, headers: dict[str, str] | None = None, flow_id: str = "parity-flow") -> ParityFlow:
    text = body if isinstance(body, str) else json.dumps(body)
    return ParityFlow(ParityRequest(url, "POST", text, headers), flow_id)


def _respond(flow: ParityFlow, body: Any, status: int = 200, headers: dict[str, str] | None = None) -> None:
    text = body if isinstance(body, str) else json.dumps(body)
    flow.response = ParityResponse(status, text, headers)


def _roundtrip(h: Harness, flow: ParityFlow, body: Any, status: int = 200) -> None:
    h.addon.request(flow)
    if getattr(flow, "response", None) is None:
        _respond(flow, body, status)
        h.addon.responseheaders(flow)
    h.addon.response(flow)


def sc_get_metrics(h: Harness) -> dict[str, Any]:
    a = ParityFlow(ParityRequest("http://127.0.0.1:8080/holon/api/metrics", "GET"))
    b = ParityFlow(ParityRequest("http://127.0.0.1:8080/_holon/metrics/", "GET"))
    h.addon.request(a)
    h.addon.request(b)
    return h.observe(a, b)


def sc_post_metrics_falls_through(h: Harness) -> dict[str, Any]:
    flow = ParityFlow(ParityRequest("http://127.0.0.1:9999/holon/api/metrics", "POST", "{}"))
    h.addon.request(flow)
    return h.observe(flow)


def sc_mode_post_variants(h: Harness) -> dict[str, Any]:
    url = "http://127.0.0.1:8080/holon/api/mode"
    flows = [
        ParityFlow(ParityRequest(url, "POST", json.dumps({"mode": "baseline"}))),
        ParityFlow(ParityRequest(url, "GET")),
        ParityFlow(ParityRequest(url, "POST", json.dumps({"mode": " Optimized "}))),
        ParityFlow(ParityRequest("http://127.0.0.1:8080/_holon/mode", "post", json.dumps({"mode": "passive"}))),
        ParityFlow(ParityRequest(url, "POST", json.dumps({"mode": "active", "wire_log_dir": "/tmp/x"}))),
        ParityFlow(ParityRequest(url, "POST", "{not json")),
        ParityFlow(ParityRequest(url, "POST", "")),
        ParityFlow(ParityRequest(url, "POST", json.dumps({"mode": "weird"}))),
        ParityFlow(ParityRequest(url, "GET")),
    ]
    snapshots = []
    for flow in flows:
        h.addon.request(flow)
        snapshots.append((h.addon.default_passive, h.addon.wire_log_dir == str(h.wire_dir)))
    return {**h.observe(*flows), "mode_trace": snapshots}


def sc_mode_get_env_passive(h: Harness, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setenv("HOLON_PASSIVE_MONITORING", "1")
    flow = ParityFlow(ParityRequest("http://127.0.0.1:8080/holon/api/mode", "GET"))
    h.addon.request(flow)
    return h.observe(flow)


def sc_mode_put_falls_through(h: Harness) -> dict[str, Any]:
    flow = ParityFlow(ParityRequest("http://127.0.0.1:9999/holon/api/mode", "PUT", json.dumps({"mode": "baseline"})))
    h.addon.request(flow)
    return h.observe(flow)


def sc_dashboard_html(h: Harness) -> dict[str, Any]:
    a = ParityFlow(ParityRequest("http://127.0.0.1:8080/holon", "GET"))
    b = ParityFlow(ParityRequest("http://127.0.0.1:8080/holon/", "GET"))
    c = ParityFlow(ParityRequest("http://127.0.0.1:8080/holon/", ""))
    for f in (a, b, c):
        h.addon.request(f)
    obs = h.observe(a, b, c)
    for f in obs["flows"]:
        if f["response"] is not None:
            f["response"]["body"] = f"<html len={len(f['response']['body'])}>"
    return obs


def sc_own_port_no_targets(h: Harness) -> dict[str, Any]:
    flow = _post("http://localhost:8080/v1/chat/completions", OPENAI_REQ)
    _roundtrip(h, flow, OPENAI_RESP)
    return h.observe(flow)


def sc_own_port_with_target_host(h: Harness, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setenv("HOLON_HOST_LOCAL_HOSTS", "localhost:11434")
    flow = _post("http://127.0.0.1.nip.io:8080/v1/chat/completions", OPENAI_REQ)
    _roundtrip(h, flow, OPENAI_RESP)
    return h.observe(flow)


def sc_own_port_with_target_container(h: Harness, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setenv("HOLON_HOST_LOCAL_HOSTS", "192.168.1.50:8081")
    monkeypatch.setenv("HOLON_PROXY_PORT", "18080")
    monkeypatch.setattr("holon_coherence.mitm_addon.in_container", lambda: True)
    flow = _post("http://localhost:18080/v1/chat/completions", OPENAI_REQ)
    _roundtrip(h, flow, OPENAI_RESP)
    return h.observe(flow)


def sc_unknown_provider(h: Harness) -> dict[str, Any]:
    flow = _post("https://example.com/upload", {"file": "x"})
    _roundtrip(h, flow, {"ok": True})
    return h.observe(flow)


def sc_non_json_known_provider(h: Harness) -> dict[str, Any]:
    flow = _post(OPENAI_URL, "not json at all")
    _roundtrip(h, flow, OPENAI_RESP)
    return h.observe(flow)


def sc_active_miss_then_hit(h: Harness) -> dict[str, Any]:
    first = _post(ANTHROPIC_URL, ANTHROPIC_REQ, flow_id="flow-a")
    _roundtrip(h, first, ANTHROPIC_RESP)
    second = _post(ANTHROPIC_URL, ANTHROPIC_REQ, flow_id="flow-b")
    _roundtrip(h, second, {"never": "used"})
    return h.observe(first, second)


def sc_openai_cleaner_miss(h: Harness) -> dict[str, Any]:
    flow = _post(OPENAI_URL, OPENAI_REQ)
    _roundtrip(h, flow, OPENAI_RESP)
    return h.observe(flow)


def sc_passive_header(h: Harness) -> dict[str, Any]:
    headers = {"Content-Type": "application/json", "x-holon-mode": "baseline"}
    first = _post(OPENAI_URL, OPENAI_REQ, headers, flow_id="flow-a")
    _roundtrip(h, first, OPENAI_RESP)
    second = _post(OPENAI_URL, OPENAI_REQ, dict(headers), flow_id="flow-b")
    _roundtrip(h, second, OPENAI_RESP)
    return h.observe(first, second)


def sc_passive_default(h: Harness) -> dict[str, Any]:
    h.addon.default_passive = True
    flow = _post(ANTHROPIC_URL, ANTHROPIC_REQ)
    _roundtrip(h, flow, ANTHROPIC_RESP)
    return h.observe(flow)


def sc_passive_header_overrides_default(h: Harness) -> dict[str, Any]:
    h.addon.default_passive = True
    flow = _post(ANTHROPIC_URL, ANTHROPIC_REQ, {"x-holon-passive": "0"})
    _roundtrip(h, flow, ANTHROPIC_RESP)
    return h.observe(flow)


def sc_interceptor_raises(h: Harness, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("interceptor exploded")

    monkeypatch.setattr(h.addon.interceptor, "intercept_request_with_stats", boom)
    flow = _post(OPENAI_URL, OPENAI_REQ)
    h.addon.request(flow)
    return h.observe(flow)


def sc_legacy_intercept_request_only(h: Harness) -> dict[str, Any]:
    class LegacyInterceptor:
        def __init__(self, inner: Any) -> None:
            self.inner = inner

        def detect_provider(self, url: str, data: Any) -> str:
            return self.inner.detect_provider(url, data)

        def intercept_request(self, url: str, data: Any) -> Any:
            return {**data, "legacy": True}, None

        def intercept_response(self, *args: Any, **kwargs: Any) -> None:
            return None

    h.addon.interceptor = LegacyInterceptor(h.addon.interceptor)
    flow = _post(OPENAI_URL, OPENAI_REQ)
    _roundtrip(h, flow, OPENAI_RESP)
    return h.observe(flow)


def sc_cached_dict_without_response_make(h: Harness, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setattr(
        h.addon.interceptor,
        "intercept_request_with_stats",
        lambda url, data: (data, {"cached": True}, None),
    )
    flow = _post(OPENAI_URL, OPENAI_REQ)
    h.addon.request(flow)
    h.addon.response(flow)
    return h.observe(flow)


def sc_gemini_bridge_stream_env_model(h: Harness, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setenv("HOLON_LOCAL_MODEL", "qwen-local")
    flow = _post("http://localhost:11434/v1beta/models/gemma:streamGenerateContent?alt=sse", GEMINI_REQ)
    h.addon.request(flow)
    flow.response = ParityResponse(200, "", {"Content-Type": "text/event-stream"})
    chunks = [
        b'data: {"choices":[{"index":0,"delta":{"role":"assistant","content":"Hel"}}]}\n\n',
        b'data: {"choices":[{"index":0,"delta":{"content":"lo"},"finish_reason":"stop"}],'
        b'"usage":{"prompt_tokens":5,"completion_tokens":2}}\n\n',
        b"",
        b"data: [DONE]\n\n",
    ]
    h.stream(flow, chunks)
    h.addon.response(flow)
    return h.observe(flow)


def sc_gemini_bridge_path_model(h: Harness) -> dict[str, Any]:
    flow = _post("http://localhost:11434/v1beta/models/gemma-3:generateContent", GEMINI_REQ)
    _roundtrip(
        h,
        flow,
        {
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 1},
        },
    )
    return h.observe(flow)


def sc_gemini_bridge_bad_response_translation(h: Harness) -> dict[str, Any]:
    flow = _post("http://localhost:11434/v1beta/models/gemma-3:generateContent", GEMINI_REQ)
    _roundtrip(h, flow, {"choices": "not-a-list", "usage": {"prompt_tokens": 1}})
    return h.observe(flow)


def sc_anthropic_local_normalise(h: Harness) -> dict[str, Any]:
    body = {
        "model": "local",
        "max_tokens": 32,
        "system": [{"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": [{"type": "text", "text": "hi", "cache_control": {"type": "x"}}]}],
    }
    flow = _post("http://localhost:11434/v1/messages", body)
    _roundtrip(h, flow, ANTHROPIC_RESP)
    return h.observe(flow)


def sc_cloud_gemini_not_bridged(h: Harness) -> dict[str, Any]:
    flow = _post("https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent", GEMINI_REQ)
    _roundtrip(
        h,
        flow,
        {
            "candidates": [{"content": {"parts": [{"text": "hey"}]}}],
            "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 1},
        },
    )
    return h.observe(flow)


def sc_sse_openai(h: Harness) -> dict[str, Any]:
    body = {**OPENAI_REQ, "stream": True}
    flow = _post(OPENAI_URL, body)
    h.addon.request(flow)
    flow.response = ParityResponse(200, "", {"content-type": "text/event-stream; charset=utf-8"})
    seen: list[bytes] = []

    def downstream(chunk: bytes) -> bytes:
        seen.append(chunk)
        return chunk.upper()

    flow.response.stream = downstream
    h.stream(
        flow,
        [
            b'data: {"choices":[{"delta":{"content":"a"}}]}\n\n',
            b'data: {"choices":[{"delta":{"content":"b"}}],"usage":{"prompt_tokens":9,"completion_tokens":2}}\n\n',
        ],
    )
    h.addon.response(flow)
    return {**h.observe(flow), "downstream": [c.decode() for c in seen]}


def sc_sse_buffer_cap(h: Harness, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    flow = _post(OPENAI_URL, {**OPENAI_REQ, "stream": True})
    h.addon.request(flow)
    flow.response = ParityResponse(200, "", {"Content-Type": "text/event-stream"})
    h.addon.responseheaders(flow)
    flow.sse_bytes = 50 * 1024 * 1024 - 5
    out = [flow.response.stream(b"0123"), flow.response.stream(b"45678")]
    obs = h.observe(flow)
    return {**obs, "returned": [c.decode() for c in out]}


def sc_responseheaders_variants(h: Harness) -> dict[str, Any]:
    flows = []
    for headers in (None, {}, {"Content-Type": "application/json"}, {"CONTENT-TYPE": "text/event-stream"}):
        flow = _post(OPENAI_URL, OPENAI_REQ)
        flow.provider = "openai"
        flow.response = ParityResponse(200, "", headers)
        if headers is None:
            flow.response.headers = None
        h.addon.responseheaders(flow)
        flows.append(flow)
    unknown = _post(OPENAI_URL, OPENAI_REQ)
    unknown.response = ParityResponse(200, "", {"Content-Type": "text/event-stream"})
    h.addon.responseheaders(unknown)
    no_resp = _post(OPENAI_URL, OPENAI_REQ)
    no_resp.provider = "openai"
    h.addon.responseheaders(no_resp)
    obs = h.observe(*flows, unknown, no_resp)
    obs["stream_installed"] = [callable(getattr(f.response, "stream", None)) for f in [*flows, unknown]]
    return obs


def sc_non_200(h: Harness) -> dict[str, Any]:
    flow = _post(OPENAI_URL, OPENAI_REQ)
    _roundtrip(h, flow, {"error": {"message": "rate limited"}}, status=429)
    return h.observe(flow)


def sc_non_200_text_bodies(h: Harness) -> dict[str, Any]:
    flow = ParityFlow(ParityRequest(OPENAI_URL, "POST", "plain text body"))
    flow.provider = "openai"
    flow.response = ParityResponse(500, "upstream exploded")
    h.addon.response(flow)
    return h.observe(flow)


def sc_non_200_get_text_raises(h: Harness) -> dict[str, Any]:
    flow = _post(OPENAI_URL, OPENAI_REQ)
    h.addon.request(flow)
    flow.response = ExplodingResponse(503)
    h.addon.response(flow)
    obs = h.observe(flow)
    return obs


def sc_response_get_text_raises(h: Harness) -> dict[str, Any]:
    flow = _post(OPENAI_URL, OPENAI_REQ)
    h.addon.request(flow)
    flow.response = ExplodingResponse(200)
    h.addon.response(flow)
    return h.observe(flow)


def sc_response_non_json_body(h: Harness) -> dict[str, Any]:
    flow = _post(OPENAI_URL, OPENAI_REQ)
    _roundtrip(h, flow, "<html>gateway</html>")
    return h.observe(flow)


def sc_response_empty_body(h: Harness) -> dict[str, Any]:
    flow = _post(OPENAI_URL, OPENAI_REQ)
    _roundtrip(h, flow, "")
    return h.observe(flow)


def sc_response_guards(h: Harness) -> dict[str, Any]:
    no_req = ParityFlow(ParityRequest(OPENAI_URL))
    no_req.request = None  # type: ignore[assignment]
    h.addon.request(no_req)
    h.addon.response(no_req)
    no_resp = _post(OPENAI_URL, OPENAI_REQ)
    no_resp.provider = "openai"
    h.addon.response(no_resp)
    cached = _post(OPENAI_URL, OPENAI_REQ)
    cached.provider = "openai"
    cached.is_cached = True
    _respond(cached, OPENAI_RESP)
    h.addon.response(cached)
    return h.observe(no_resp, cached)


def sc_response_without_req_data(h: Harness) -> dict[str, Any]:
    flow = _post(OPENAI_URL, OPENAI_REQ)
    flow.provider = "openai"
    _respond(flow, OPENAI_RESP)
    h.addon.response(flow)
    return h.observe(flow)


def sc_wire_logging_disabled(h: Harness, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setenv("ENABLE_WIRE_LOGGING", "0")
    flow = _post(ANTHROPIC_URL, ANTHROPIC_REQ, {"X-Holon-Agent-Id": "agent-9", "authorization": "Bearer sk-x"})
    _roundtrip(h, flow, ANTHROPIC_RESP)
    return h.observe(flow)


def sc_wire_record_identity(h: Harness, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setenv("HOLON_AGENT_ID", "env-agent")
    monkeypatch.setenv("HOLON_ROLE", "planner")
    flow = _post(
        ANTHROPIC_URL + "?api_key=SECRET123",
        ANTHROPIC_REQ,
        {"x-holon-agent-role": "critic", "x-holon-turn-id": "7", "authorization": "Bearer sk-abcdef"},
    )
    flow.id = ""
    _roundtrip(h, flow, ANTHROPIC_RESP)
    obs = h.observe(flow)
    for rec in obs["wire"]:
        rec["flow_id"] = "<random>" if rec["flow_id"].startswith("flow_") else rec["flow_id"]
    return obs


ScenarioFn = Callable[..., dict[str, Any]]
SCENARIOS: dict[str, ScenarioFn] = {
    name.removeprefix("sc_"): fn for name, fn in sorted(globals().items()) if name.startswith("sc_")
}


def _run(name: str, h: Harness, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    fn = SCENARIOS[name]
    obs = fn(h, monkeypatch) if fn.__code__.co_argcount == 2 else fn(h)
    text = json.dumps(obs, default=repr).replace(str(h.tmp_path), "<tmp>")
    return json.loads(text)


def _load_golden() -> dict[str, Any]:
    if GOLDEN_PATH.exists():
        return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    return {}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_addon_wire_parity(name: str, harness: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    observed = _run(name, harness, monkeypatch)
    if os.environ.get("HOLON_PARITY_REGEN") == "1":
        golden = _load_golden()
        golden[name] = observed
        GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN_PATH.write_text(json.dumps(golden, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return
    golden = _load_golden()
    assert name in golden, f"No golden observation for scenario {name!r}; regenerate deliberately."
    assert observed == golden[name]


def test_golden_has_no_orphans() -> None:
    assert set(_load_golden()) == set(SCENARIOS)


# --------------------------------------------------------------------------------------------------
# Explicit quirk pins (readable assertions on top of the golden comparison)
# --------------------------------------------------------------------------------------------------


def test_bridge_exception_propagates_out_of_request(harness: Harness) -> None:
    flow = _post("http://localhost:11434/v1beta/models/gemma:generateContent", [1, 2, 3])
    with pytest.raises(AttributeError):
        harness.addon.request(flow)
    assert harness.addon.total_requests == 1
    assert getattr(flow, "is_gemini_bridged", False) is True


def test_anthropic_local_normaliser_exception_propagates(harness: Harness) -> None:
    flow = _post("http://localhost:11434/v1/messages", ["not", "a", "dict"])
    with pytest.raises(TypeError):
        harness.addon.request(flow)


def test_cache_hit_headers_are_zeroed(harness: Harness) -> None:
    for flow_id in ("a", "b"):
        flow = _post(ANTHROPIC_URL, ANTHROPIC_REQ, flow_id=flow_id)
        _roundtrip(harness, flow, ANTHROPIC_RESP)
    headers = dict(flow.response.headers.items())
    assert headers["X-Holon-Cache-Hit-Rate"] == "0.5000"
    for name in ("X-Holon-TTFT-Ms", "X-Holon-Total-Time-Ms"):
        assert headers[name] == "0.00"
    assert headers["X-Holon-Decode-Time-Sec"] == "0.000"
    hit = [r for r in _wire_records(harness.wire_dir) if r["cache_action"] == "HIT"]
    assert len(hit) == 1
    assert flow.is_cached is True


def test_interceptor_failure_is_logged_after_counters(harness: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    obs = _run("interceptor_raises", harness, monkeypatch)
    assert obs["addon"]["total_requests"] == 1
    assert ["holon_coherence.proxy.addon", "ERROR"] in [log[:2] for log in obs["logs"]]
