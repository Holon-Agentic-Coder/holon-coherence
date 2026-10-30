"""Response telemetry: token/timing computation, X-Holon headers, telemetry lines, wire dump and metrics."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from holon_coherence.metrics_math import (
    UNMEASURED,
    compute_decode_tps,
    compute_prefill_tps,
    compute_tail_prefill_tps,
    format_rate,
)
from holon_coherence.parsers import extract_token_counts
from holon_coherence.proxy.steps._compat import _get_log_telemetry
from holon_coherence.proxy.steps._headers import writable_headers
from holon_coherence.proxy.steps.base import Outcome, ResponseContext, hit_rate, logger
from holon_coherence.proxy.timing import FlowTiming, resolve_flow_timing

__all__ = [
    "Telemetry",
    "compute_telemetry",
    "dump_miss_transaction",
    "inject_miss_headers",
    "log_failure",
    "log_miss_telemetry",
    "record_failure",
    "record_response_metrics",
]


@dataclass(frozen=True)
class Telemetry:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    reasoning_tokens: int
    ttft: float | None
    total_time: float | None
    generation_time: float | None
    prefill_tps: float | None
    tail_prefill_tps: float | None
    output_tps: float | None
    hit_rate: float
    timing: FlowTiming


def compute_telemetry(ctx: ResponseContext) -> Outcome:
    """Token counts and timing-derived rates for a successful response."""
    # Extract token counts and cache read tokens in a single pass
    token_counts = extract_token_counts(ctx.req_data, ctx.resp_data, ctx.provider)
    input_tokens = token_counts[0]
    output_tokens = token_counts[1]
    cache_read_tokens = token_counts[2]

    # Compute timing from one clock domain; a missing stamp means "not measured"
    # and must never be replaced by `now`, which is what yielded ttft == 0.0 and the
    # 0.00 tokens/sec prefill readings.
    now = time.perf_counter()
    timing = resolve_flow_timing(ctx.flow, completed_at=now)
    ttft = timing.ttft_sec
    generation_time = timing.generation_sec

    uncached_input_tokens = max(0, input_tokens - cache_read_tokens)
    ctx.telemetry = Telemetry(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_creation_tokens=getattr(token_counts, "cache_creation_tokens", 0),
        reasoning_tokens=getattr(token_counts, "reasoning_tokens", 0),
        ttft=ttft,
        total_time=timing.total_sec,
        generation_time=generation_time,
        prefill_tps=compute_prefill_tps(input_tokens, ttft),
        tail_prefill_tps=compute_tail_prefill_tps(uncached_input_tokens, ttft),
        output_tps=compute_decode_tps(output_tokens, generation_time, streaming=timing.streaming),
        hit_rate=hit_rate(ctx.addon),
        timing=timing,
    )
    return Outcome.CONTINUE


def _ms_header(seconds: float | None) -> str:
    return f"{seconds * 1000:.2f}" if seconds is not None else UNMEASURED


def inject_miss_headers(ctx: ResponseContext) -> Outcome:
    """Inject telemetry headers on cache miss."""
    t = ctx.telemetry
    headers = writable_headers(ctx.flow)
    if headers is None:
        return Outcome.CONTINUE
    headers["X-Holon-Cache-Hit-Rate"] = f"{t.hit_rate:.4f}"
    headers["X-Holon-Streaming"] = "true" if t.timing.streaming else "false"
    headers["X-Holon-TTFT-Ms"] = _ms_header(t.ttft)
    headers["X-Holon-Prefill-TPS"] = format_rate(t.prefill_tps, 4)
    headers["X-Holon-Tail-Prefill-TPS"] = format_rate(t.tail_prefill_tps, 4)
    headers["X-Holon-Decode-Time-Sec"] = f"{t.generation_time:.3f}" if t.generation_time is not None else UNMEASURED
    headers["X-Holon-Output-TPS"] = format_rate(t.output_tps, 4)
    headers["X-Holon-Total-Time-Ms"] = _ms_header(t.total_time)
    return Outcome.CONTINUE


def _ms_label(seconds: float | None) -> str:
    return f"{seconds * 1000:.1f}ms" if seconds is not None else UNMEASURED


def _output_label(t: Telemetry) -> str:
    if t.output_tps is not None and t.generation_time is not None:
        return f"{t.output_tps:.2f} t/s ({t.output_tokens} tok in {t.generation_time:.2f}s)"
    return f"n/a [{t.timing.decode_reason()}] ({t.output_tokens} tok)"


def log_miss_telemetry(ctx: ResponseContext) -> Outcome:
    """One telemetry line per cache-miss response."""
    t = ctx.telemetry
    log_msg = (
        f"📊 [TELEMETRY] Provider: {ctx.provider.upper()} | "
        f"Cache: MISS (Hit Rate: {t.hit_rate * 100:.1f}%) | "
        f"TTFT: {_ms_label(t.ttft)} | "
        f"Prefill: {format_rate(t.prefill_tps)} t/s ({t.input_tokens} tok) | "
        f"Output: {_output_label(t)} | "
        f"Total: {_ms_label(t.total_time)}"
    )
    _get_log_telemetry()(log_msg)
    return Outcome.CONTINUE


def dump_miss_transaction(ctx: ResponseContext) -> Outcome:
    """Persist wire transaction dump."""
    t = ctx.telemetry
    ctx.addon._dump_flow_transaction(
        ctx.flow,
        resp_data=ctx.resp_data,
        status_code=ctx.status_code,
        is_hit=False,
        is_sse=ctx.is_sse,
        ttft=t.ttft,
        total_time=t.total_time,
        prefill_tps=t.prefill_tps,
        tail_prefill_tps=t.tail_prefill_tps,
        decode_tps=t.output_tps,
        generation_time=t.generation_time,
    )
    return Outcome.CONTINUE


def record_response_metrics(ctx: ResponseContext) -> Outcome:
    """Update in-memory cumulative optimization metrics."""
    t = ctx.telemetry
    ctx.addon.metrics.record_response(
        input_tokens=t.input_tokens,
        output_tokens=t.output_tokens,
        cache_read_tokens=t.cache_read_tokens,
        cache_creation_tokens=t.cache_creation_tokens,
        reasoning_tokens=t.reasoning_tokens,
        ttft=t.ttft,
        output_tps=t.output_tps,
        prefill_tps=t.prefill_tps,
        tail_prefill_tps=t.tail_prefill_tps,
        total_time=t.total_time,
    )
    return Outcome.CONTINUE


def log_failure(ctx: ResponseContext) -> None:
    """Warn about a non-200 response and emit its telemetry line; runs outside the error guard."""
    logger.warning("Skipping caching response with HTTP status code %d for %s", ctx.status_code, ctx.url)
    start_t = getattr(ctx.flow, "request_start_time", None) or time.perf_counter()
    ctx.elapsed_ms = (time.perf_counter() - start_t) * 1000
    log_msg = (
        f"⚠️ [TELEMETRY] Provider: {ctx.provider.upper()} | Status: {ctx.status_code} | Total: {ctx.elapsed_ms:.1f}ms"
    )
    _get_log_telemetry()(log_msg)


def _best_effort_json(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return text


def _load_failure_request(flow: Any) -> None:
    if getattr(flow, "req_data", None) is None and getattr(flow, "request", None) and hasattr(flow.request, "get_text"):
        req_text = flow.request.get_text()
        if req_text:
            flow.req_data = _best_effort_json(req_text)


def _load_failure_response(flow: Any) -> Any:
    resp_data = None
    if getattr(flow, "response", None) and hasattr(flow.response, "get_text"):
        resp_text = flow.response.get_text()
        if resp_text:
            resp_data = _best_effort_json(resp_text)
    return resp_data


def record_failure(ctx: ResponseContext) -> Outcome:
    """Best-effort wire record and zeroed metrics sample for a non-200 response."""
    flow = ctx.flow
    _load_failure_request(flow)
    resp_data = _load_failure_response(flow)
    ctx.addon._dump_flow_transaction(
        flow,
        resp_data=resp_data,
        status_code=ctx.status_code,
        is_hit=False,
        is_sse=False,
        ttft=None,
        total_time=(ctx.elapsed_ms / 1000.0),
    )
    ctx.addon.metrics.record_response(
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        reasoning_tokens=0,
        ttft=None,
        output_tps=None,
        prefill_tps=None,
        tail_prefill_tps=None,
    )
    return Outcome.CONTINUE
