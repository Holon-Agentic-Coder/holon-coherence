"""Unit tests for the ``holon_coherence.proxy.steps`` pipeline runner and individual steps."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from holon_coherence.mitm_addon import MitmproxyAddon
from holon_coherence.payload_cleaner import CleaningResult
from holon_coherence.proxy.steps import (
    FAILURE_POLICY,
    REQUEST_GUARDED,
    REQUEST_POLICY,
    REQUEST_PRELUDE,
    RESPONSE_FAILURE,
    RESPONSE_SUCCESS,
    SUCCESS_POLICY,
    ErrorPolicy,
    Outcome,
    RequestContext,
    ResponseContext,
    StepSpec,
    run_guarded,
    run_steps,
)
from holon_coherence.proxy.steps.apply_cache import serve_cached, store_response
from holon_coherence.proxy.steps.clean_payload import clean_payload, snapshot_request
from holon_coherence.proxy.steps.identify_provider import identify_provider
from holon_coherence.proxy.steps.route_local_target import route_local_target
from holon_coherence.proxy.steps.serve_dashboard import serve_mode
from holon_coherence.proxy.steps.wire_record import (
    WireTransaction,
    _content,
    _delta,
    _timing,
    build_wire_record,
)


class _Req:
    def __init__(self, url: str = "https://api.openai.com/v1/chat/completions", text: str = "", **attrs: Any):
        self.pretty_url = url
        self.headers: dict[str, str] = attrs.pop("headers", {})
        self._text = text
        for key, value in attrs.items():
            setattr(self, key, value)

    def get_text(self) -> str:
        return self._text

    def set_text(self, text: str) -> None:
        self._text = text


def _flow(**req_attrs: Any) -> SimpleNamespace:
    return SimpleNamespace(id="f-1", request=_Req(**req_attrs), response=None)


@pytest.fixture
def addon(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> MitmproxyAddon:
    for name in ("HOLON_PASSIVE_MONITORING", "COHERENCE_TOKEN_REDUCTION", "HOLON_HOST_LOCAL_HOSTS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("holon_coherence.mitm_addon.log_telemetry", lambda _msg: None)
    return MitmproxyAddon(cache_dir=str(tmp_path / "cache"), wire_log_dir=str(tmp_path / "wire"))


def _req_ctx(addon: MitmproxyAddon, flow: Any, **fields: Any) -> RequestContext:
    ctx = RequestContext.from_flow(addon, flow)
    for key, value in fields.items():
        setattr(ctx, key, value)
    return ctx


# --------------------------------------------------------------------------------------------------
# Pipeline shape
# --------------------------------------------------------------------------------------------------


def test_request_pipeline_order_is_frozen() -> None:
    assert [(s.name, s.mode) for s in REQUEST_PRELUDE + REQUEST_GUARDED] == [
        ("serve_dashboard", "always"),
        ("route_local_target", "always"),
        ("parse_request_body", "always"),
        ("identify_provider", "always"),
        ("adapt_local_protocol", "always"),
        ("snapshot_request", "always"),
        ("passthrough_payload", "passive"),
        ("clean_payload", "active"),
        ("serve_cached", "active"),
    ]


def test_response_pipeline_order_is_frozen() -> None:
    assert [(s.name, s.mode) for s in RESPONSE_SUCCESS] == [
        ("load_request", "always"),
        ("load_response", "always"),
        ("require_payloads", "always"),
        ("store_response", "active"),
        ("compute_telemetry", "always"),
        ("inject_miss_headers", "always"),
        ("log_miss_telemetry", "always"),
        ("dump_miss_transaction", "always"),
        ("record_response_metrics", "always"),
    ]
    assert [s.name for s in RESPONSE_FAILURE] == ["record_failure"]


def test_prelude_is_unguarded_and_only_runner_branches_on_mode() -> None:
    assert all(s.mode == "always" for s in REQUEST_PRELUDE)
    assert {s.mode for s in REQUEST_GUARDED} == {"always", "active", "passive"}


# --------------------------------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------------------------------


class _Ctx:
    def __init__(self, passive: bool) -> None:
        self._passive = passive
        self.passive_reads = 0
        self.url = "https://example.test/v1"
        self.trace: list[str] = []

    @property
    def passive(self) -> bool:
        self.passive_reads += 1
        return self._passive


def _recorder(name: str, outcome: Outcome = Outcome.CONTINUE) -> StepSpec:
    def fn(ctx: _Ctx) -> Outcome:
        ctx.trace.append(name)
        return outcome

    return StepSpec(name, fn)


@pytest.mark.parametrize(("passive", "expected"), [(True, ["a", "p", "z"]), (False, ["a", "x", "z"])])
def test_passive_gate_selects_steps(passive: bool, expected: list[str]) -> None:
    steps = (
        _recorder("a"),
        StepSpec("p", _recorder("p").fn, mode="passive"),
        StepSpec("x", _recorder("x").fn, mode="active"),
        _recorder("z"),
    )
    ctx = _Ctx(passive)
    assert run_steps(steps, ctx) is Outcome.CONTINUE
    assert ctx.trace == expected


def test_halt_stops_the_run_and_always_steps_never_read_passive() -> None:
    ctx = _Ctx(False)
    steps = (_recorder("a"), _recorder("stop", Outcome.HALT), StepSpec("x", _recorder("x").fn, mode="active"))
    assert run_steps(steps, ctx) is Outcome.HALT
    assert ctx.trace == ["a", "stop"]
    assert ctx.passive_reads == 0


def test_request_context_evaluates_passive_once(addon: MitmproxyAddon, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []

    def fake_is_flow_passive(flow: Any, default_passive: bool | None = None) -> bool:
        calls.append(flow)
        return True

    monkeypatch.setattr("holon_coherence.proxy.steps.base.is_flow_passive", fake_is_flow_passive)
    ctx = _req_ctx(addon, _flow())
    assert ctx.passive is True
    assert ctx.passive is True
    assert len(calls) == 1


def test_snapshot_halt_skips_passive_evaluation(addon: MitmproxyAddon, monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_args: Any, **_kwargs: Any) -> bool:
        raise AssertionError("passive must not be evaluated for bodiless requests")

    monkeypatch.setattr("holon_coherence.proxy.steps.base.is_flow_passive", explode)
    ctx = _req_ctx(addon, _flow(), data=None)
    assert run_steps(REQUEST_GUARDED, ctx) is Outcome.HALT


def _raiser(exc: Exception) -> StepSpec:
    def fn(_ctx: Any) -> Outcome:
        raise exc

    return StepSpec("boom", fn)


@pytest.mark.parametrize(
    ("policy", "exc", "level", "message"),
    [
        (
            REQUEST_POLICY,
            json.JSONDecodeError("bad", "x", 0),
            logging.DEBUG,
            "Non-JSON request body for endpoint https://example.test/v1: bad: line 1 column 1 (char 0)",
        ),
        (
            REQUEST_POLICY,
            RuntimeError("kaput"),
            logging.ERROR,
            "Mitmproxy request intercept error for endpoint: https://example.test/v1",
        ),
        (
            SUCCESS_POLICY,
            json.JSONDecodeError("bad", "x", 0),
            logging.DEBUG,
            "Non-JSON request/response body for endpoint https://example.test/v1: bad: line 1 column 1 (char 0)",
        ),
        (
            SUCCESS_POLICY,
            ValueError("kaput"),
            logging.ERROR,
            "Mitmproxy response intercept error for endpoint: https://example.test/v1",
        ),
        (
            FAILURE_POLICY,
            json.JSONDecodeError("bad", "x", 0),
            logging.DEBUG,
            "Failed to record non-200 wire transaction: bad: line 1 column 1 (char 0)",
        ),
        (FAILURE_POLICY, RuntimeError("kaput"), logging.DEBUG, "Failed to record non-200 wire transaction: kaput"),
    ],
)
def test_error_policies_route_to_the_right_level(
    policy: ErrorPolicy, exc: Exception, level: int, message: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="holon_coherence.proxy.addon")
    run_guarded((_raiser(exc),), _Ctx(False), policy)
    records = [r for r in caplog.records if r.name == "holon_coherence.proxy.addon"]
    assert [(r.levelno, r.getMessage()) for r in records] == [(level, message)]
    assert (records[0].exc_info is not None) is (level == logging.ERROR)


# --------------------------------------------------------------------------------------------------
# Individual steps
# --------------------------------------------------------------------------------------------------


def test_serve_mode_falls_through_for_put(addon: MitmproxyAddon) -> None:
    flow = _flow(url="http://127.0.0.1:8080/holon/api/mode", method="PUT", path="/holon/api/mode")
    ctx = _req_ctx(addon, flow)
    assert serve_mode(ctx) is Outcome.CONTINUE
    assert flow.response is None


def test_route_local_target_without_targets_is_noop(addon: MitmproxyAddon, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("holon_coherence.mitm_addon.in_container", lambda: False)
    monkeypatch.setattr("holon_coherence.mitm_addon.ctx", None)
    flow = _flow(url="http://localhost:8080/v1/chat/completions", host="localhost", port=8080, scheme="http")
    ctx = _req_ctx(addon, flow)
    assert route_local_target(ctx) is Outcome.CONTINUE
    assert (flow.request.host, flow.request.port, flow.request.scheme) == ("localhost", 8080, "http")
    assert ctx.url == "http://localhost:8080/v1/chat/completions"


def test_identify_provider_unknown_halts_without_counting(addon: MitmproxyAddon) -> None:
    flow = _flow(url="https://example.com/upload")
    ctx = _req_ctx(addon, flow, data={"file": "x"})
    assert identify_provider(ctx) is Outcome.HALT
    assert addon.total_requests == 0
    assert addon.metrics.to_dict()["total_requests"] == 0
    assert not hasattr(flow, "provider")


def test_snapshot_request_deep_copies(addon: MitmproxyAddon) -> None:
    data = {"messages": [{"role": "user", "content": "x"}]}
    flow = _flow()
    ctx = _req_ctx(addon, flow, data=data)
    assert snapshot_request(ctx) is Outcome.CONTINUE
    assert flow.raw_request_data == data
    assert flow.raw_request_data is not data
    assert flow.raw_request_data["messages"] is not data["messages"]


def test_clean_payload_local_fixup_zeroes_cache_control(addon: MitmproxyAddon, monkeypatch: pytest.MonkeyPatch) -> None:
    res = CleaningResult(payload={}, chars_saved=0, cache_control_injected=3)
    cleaned = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
    monkeypatch.setattr(addon.interceptor, "intercept_request_with_stats", lambda url, data: (cleaned, None, res))
    flow = _flow(url="http://localhost:11434/v1/messages")
    ctx = _req_ctx(addon, flow, data=dict(cleaned), is_local=True)
    assert clean_payload(ctx) is Outcome.CONTINUE
    assert res.cache_control_injected == 0
    assert flow.cleaner_result is res
    assert json.loads(flow.request.get_text()) == flow.req_data
    assert ctx.clean_res is res
    assert ctx.cached_resp is None


def test_serve_cached_without_cached_response_continues(addon: MitmproxyAddon) -> None:
    flow = _flow()
    ctx = _req_ctx(addon, flow, cached_resp=None, provider="openai")
    assert serve_cached(ctx) is Outcome.CONTINUE
    assert addon.cache_hits == 0
    assert flow.response is None


def test_store_response_skipped_for_sse(addon: MitmproxyAddon, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []
    monkeypatch.setattr(addon.interceptor, "intercept_response", lambda *a, **k: calls.append((a, k)))
    flow = _flow()
    ctx = ResponseContext(addon=addon, flow=flow, url="u", provider="openai", req_data={}, resp_data="data: x")
    ctx.is_sse = True
    store_response(ctx)
    assert calls == []
    ctx.is_sse = False
    store_response(ctx)
    assert calls == [(("u", {}, "data: x"), {"status_code": 200})]


# --------------------------------------------------------------------------------------------------
# Wire record builder
# --------------------------------------------------------------------------------------------------


def test_delta_without_clean_result_uses_char_difference() -> None:
    raw = {"a": "x" * 10}
    cleaned = {"a": "x"}
    assert _delta(raw, cleaned, None) == {
        "raw_chars": len(json.dumps(raw)),
        "cleaned_chars": len(json.dumps(cleaned)),
        "chars_saved": 9,
        "tool_outputs_omitted": 0,
        "turns_summarized": 0,
        "cache_control_injected": 0,
    }


def test_delta_with_clean_result_reports_cleaner_counters() -> None:
    res = CleaningResult(
        payload={}, chars_saved=5, tool_outputs_omitted=1, turns_summarized=2, cache_control_injected=3
    )
    assert _delta({}, {}, res) == {
        "raw_chars": 0,
        "cleaned_chars": 0,
        "chars_saved": 5,
        "tool_outputs_omitted": 1,
        "turns_summarized": 2,
        "cache_control_injected": 3,
    }


def test_delta_unserialisable_payload_counts_zero() -> None:
    assert _delta({"x": object()}, {"y": 1}, None)["raw_chars"] == 0


def test_content_variants() -> None:
    assert _content({"a": 1}, "openai", is_sse=False) == {"a": 1}
    assert _content(["a"], "openai", is_sse=False) == "['a']"
    sse = 'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
    assert _content(sse, "openai", is_sse=True) == "hi"


def test_timing_rounding_and_hit_defaults() -> None:
    assert _timing(WireTransaction(is_hit=True)) == {
        "ttft_ms": 0.0,
        "total_ms": 0.0,
        "streaming": False,
        "generation_ms": None,
        "prefill_tps": None,
        "tail_prefill_tps": None,
        "decode_tps": None,
    }
    assert _timing(WireTransaction())["ttft_ms"] is None
    timing = _timing(
        WireTransaction(
            is_sse=True,
            ttft=0.123456,
            total_time=1.0004999,
            generation_time=0.5,
            prefill_tps=12.3456,
            tail_prefill_tps=1.005,
            decode_tps=99.999,
        )
    )
    assert timing == {
        "ttft_ms": round(0.123456 * 1000, 2),
        "total_ms": round(1.0004999 * 1000, 2),
        "streaming": True,
        "generation_ms": 500.0,
        "prefill_tps": 12.35,
        "tail_prefill_tps": round(1.005, 2),
        "decode_tps": 100.0,
    }


def test_wire_record_key_order_is_frozen(addon: MitmproxyAddon) -> None:
    flow = _flow(headers={"authorization": "Bearer sk-secret"})
    flow.provider = "openai"
    record = build_wire_record(addon, flow, {"ok": True}, 200, WireTransaction())
    assert list(record) == [
        "turn_id",
        "flow_id",
        "agent_id",
        "agent_role",
        "timestamp",
        "provider",
        "endpoint",
        "headers",
        "raw_request",
        "cleaned_request",
        "delta",
        "mode",
        "cache_action",
        "response",
        "timing",
    ]
    assert list(record["response"]) == ["status", "usage", "content"]
    assert list(record["response"]["usage"]) == [
        "input_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
        "output_tokens",
        "reasoning_tokens",
    ]
    assert record["headers"]["authorization"] == "[REDACTED]"


def test_dump_flow_transaction_rejects_unknown_fields_quietly(
    addon: MitmproxyAddon, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="holon_coherence.proxy.addon")
    addon._dump_flow_transaction(_flow(), resp_data={}, bogus=1)
    assert any("Failed to record flow wire transaction" in r.getMessage() for r in caplog.records)
