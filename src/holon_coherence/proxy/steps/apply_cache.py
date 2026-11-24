from __future__ import annotations

import json
from typing import Any

from holon_coherence.proxy.steps._compat import _get_log_telemetry, resolve_response_cls
from holon_coherence.proxy.steps._headers import writable_headers
from holon_coherence.proxy.steps.base import Outcome, RequestContext, ResponseContext, hit_rate

__all__ = ["serve_cached", "store_response"]

_HIT_TIMING_HEADERS = (
    ("X-Holon-TTFT-Ms", "0.00"),
    ("X-Holon-Prefill-TPS", "0.0000"),
    ("X-Holon-Tail-Prefill-TPS", "0.0000"),
    ("X-Holon-Decode-Time-Sec", "0.000"),
    ("X-Holon-Output-TPS", "0.0000"),
    ("X-Holon-Total-Time-Ms", "0.00"),
)


def _inject_cache_hit_headers(flow: Any, rate: float) -> None:
    out_headers = writable_headers(flow)
    if out_headers is not None:
        out_headers["X-Holon-Cache-Hit-Rate"] = f"{rate:.4f}"
        for name, value in _HIT_TIMING_HEADERS:
            out_headers[name] = value


def serve_cached(ctx: RequestContext) -> Outcome:
    cached_resp = ctx.cached_resp
    if not cached_resp:
        return Outcome.CONTINUE
    addon, flow = ctx.addon, ctx.flow
    addon.cache_hits += 1
    addon.metrics.record_cache_hit()
    flow.is_cached = True

    headers = {"Content-Type": "application/json"}
    response_cls = resolve_response_cls(flow)
    if response_cls and hasattr(response_cls, "make"):
        flow.response = response_cls.make(200, json.dumps(cached_resp).encode("utf-8"), headers)

    rate = hit_rate(addon)
    _inject_cache_hit_headers(flow, rate)

    log_msg = (
        f"📊 [TELEMETRY] Provider: {ctx.provider.upper()} | "
        f"Cache: HIT (Hit Rate: {rate * 100:.1f}%) | "
        f"TTFT: 0.00ms | Prefill: 0.00 t/s | Output: 0.00 t/s | "
        f"Total: 0.00ms"
    )
    _get_log_telemetry()(log_msg)

    addon._dump_flow_transaction(flow, resp_data=cached_resp, status_code=200, is_hit=True)
    return Outcome.HALT


def store_response(ctx: ResponseContext) -> Outcome:
    is_non_streaming_response = not ctx.is_sse
    if is_non_streaming_response:
        ctx.addon.interceptor.intercept_response(ctx.url, ctx.req_data, ctx.resp_data, status_code=ctx.status_code)
    return Outcome.CONTINUE
