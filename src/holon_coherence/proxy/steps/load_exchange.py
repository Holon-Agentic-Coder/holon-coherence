"""Load the request/response payload pair a successful provider response is accounted against."""

from __future__ import annotations

import json
from typing import Any

from holon_coherence.proxy.steps.base import Outcome, ResponseContext, logger
from holon_coherence.proxy.translation.gemini_openai import translate_openai_to_gemini_response

__all__ = ["load_request", "load_response", "require_payloads"]


def load_request(ctx: ResponseContext) -> Outcome:
    """The cleaned request recorded by the request hook, else the parsed wire body."""
    req_data = getattr(ctx.flow, "req_data", None)
    if req_data is None:
        req_text = ctx.flow.request.get_text()
        if req_text:
            req_data = json.loads(req_text)
    ctx.req_data = req_data
    return Outcome.CONTINUE


def _translate_bridged(flow: Any, resp_data: dict[str, Any]) -> Any:
    try:
        gemini_data = translate_openai_to_gemini_response(resp_data)
        flow.response.set_text(json.dumps(gemini_data))
        return gemini_data
    except Exception as exc:
        logger.debug("Failed translating bridged Gemini response: %s", exc)
        return resp_data


def load_response(ctx: ResponseContext) -> Outcome:
    """Joined SSE text for streams, else the JSON body (translated back to Gemini when bridged)."""
    flow = ctx.flow
    sse_chunks = getattr(flow, "sse_chunks", None)
    ctx.is_sse = sse_chunks is not None
    if ctx.is_sse:
        ctx.resp_data = b"".join(sse_chunks).decode("utf-8", errors="ignore")
        return Outcome.CONTINUE
    resp_text = flow.response.get_text()
    resp_data = json.loads(resp_text) if resp_text else None
    if getattr(flow, "is_gemini_bridged", False) and isinstance(resp_data, dict):
        resp_data = _translate_bridged(flow, resp_data)
    ctx.resp_data = resp_data
    return Outcome.CONTINUE


def require_payloads(ctx: ResponseContext) -> Outcome:
    """Stop unless both a request payload and a non-empty response were loaded."""
    if ctx.req_data is not None and ctx.resp_data:
        return Outcome.CONTINUE
    return Outcome.HALT
