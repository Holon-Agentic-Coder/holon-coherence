"""Request payload snapshot, passive passthrough and active context cleaning."""

from __future__ import annotations

import copy
import json
from typing import Any

from holon_coherence.proxy.normalise.anthropic import normalize_anthropic_request
from holon_coherence.proxy.steps._compat import _get_log_telemetry
from holon_coherence.proxy.steps.base import Outcome, RequestContext

__all__ = ["clean_payload", "passthrough_payload", "snapshot_request"]


def snapshot_request(ctx: RequestContext) -> Outcome:
    """Keep a pristine copy of the request for wire logging; bodiless requests stop here."""
    if ctx.data is None:
        return Outcome.HALT
    ctx.flow.raw_request_data = copy.deepcopy(ctx.data)
    return Outcome.CONTINUE


def passthrough_payload(ctx: RequestContext) -> Outcome:
    """Passive mode: bypass cleaning and cache lookup, preserving raw payload for baseline logging."""
    ctx.flow.cleaner_result = None
    ctx.flow.req_data = ctx.data
    return Outcome.HALT


def _intercept(interceptor: Any, url: str, data: Any) -> tuple[Any, Any, Any]:
    if hasattr(interceptor, "intercept_request_with_stats"):
        return interceptor.intercept_request_with_stats(url, data)
    cleaned_data, cached_resp = interceptor.intercept_request(url, data)
    return cleaned_data, cached_resp, None


def _log_cleaner(clean_res: Any) -> None:
    if (
        clean_res.chars_saved > 0
        or clean_res.tool_outputs_omitted > 0
        or clean_res.turns_summarized > 0
        or clean_res.cache_control_injected > 0
    ):
        cleaner_log = (
            f"🧹 [CLEANER_METRICS] Chars Saved: {clean_res.chars_saved} | "
            f"Tool Outputs Omitted: {clean_res.tool_outputs_omitted} | "
            f"Turns Summarized: {clean_res.turns_summarized} | "
            f"Cache Control Injected: {clean_res.cache_control_injected}"
        )
        _get_log_telemetry()(cleaner_log)


def clean_payload(ctx: RequestContext) -> Outcome:
    """Active mode: clean the payload, rewrite the request body and record cleaner metrics."""
    flow = ctx.flow
    cleaned_data, cached_resp, clean_res = _intercept(ctx.addon.interceptor, ctx.url, ctx.data)

    if ctx.is_local and clean_res:
        clean_res.cache_control_injected = 0
        if isinstance(cleaned_data, dict):
            cleaned_data, _ = normalize_anthropic_request(flow, cleaned_data, is_local=True)

    flow.cleaner_result = clean_res
    flow.req_data = cleaned_data
    flow.request.set_text(json.dumps(cleaned_data))

    if clean_res:
        ctx.addon.metrics.record_cleaner(clean_res)
        _log_cleaner(clean_res)

    ctx.cached_resp = cached_resp
    ctx.clean_res = clean_res
    return Outcome.CONTINUE
