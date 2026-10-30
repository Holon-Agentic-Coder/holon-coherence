"""Request body parsing and provider detection."""

from __future__ import annotations

import json
import time

from holon_coherence.proxy.steps._compat import _get_is_local_target
from holon_coherence.proxy.steps.base import Outcome, RequestContext, logger

__all__ = ["identify_provider", "parse_request_body"]


def parse_request_body(ctx: RequestContext) -> Outcome:
    """Parse the JSON request body into ``ctx.data``; non-JSON bodies leave it ``None``."""
    try:
        content = ctx.flow.request.get_text()
        if content:
            ctx.data = json.loads(content)
    except Exception as exc:
        # Request body is non-JSON or unparseable; proceed with URL-based provider detection
        logger.debug("Non-JSON or unparseable request body for endpoint %s: %s", ctx.url, exc)
    return Outcome.CONTINUE


def identify_provider(ctx: RequestContext) -> Outcome:
    """Detect the LLM provider and count the request; non-LLM traffic halts the pipeline untouched."""
    provider = ctx.addon.interceptor.detect_provider(ctx.url, ctx.data)
    if provider == "unknown":
        return Outcome.HALT
    flow, addon = ctx.flow, ctx.addon
    ctx.provider = provider
    flow.provider = provider
    flow.request_start_time = time.perf_counter()  # float: timestamp from time.perf_counter()
    addon.total_requests += 1
    addon.metrics.record_request()
    ctx.is_local = _get_is_local_target()(flow)
    return Outcome.CONTINUE
