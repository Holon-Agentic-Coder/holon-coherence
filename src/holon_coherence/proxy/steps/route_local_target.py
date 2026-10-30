"""Routing and protocol adaptation for host-local inference engines."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from holon_coherence.host_local import GATEWAY_HOSTNAME, targets_from_env
from holon_coherence.proxy.normalise.anthropic import normalize_anthropic_request
from holon_coherence.proxy.steps._compat import _get_in_container
from holon_coherence.proxy.steps.base import Outcome, RequestContext
from holon_coherence.proxy.translation.gemini_openai import translate_gemini_to_openai_request

__all__ = ["adapt_local_protocol", "route_local_target"]

_SELF_HOSTS = ("127.0.0.1", "localhost", "127.0.0.1.nip.io", "localhost.nip.io")


def route_local_target(ctx: RequestContext) -> Outcome:
    """Reverse-proxy rewrite when the agent addresses the proxy's own port directly."""
    request = ctx.flow.request
    req_host = (getattr(request, "pretty_host", "") or getattr(request, "host", "")).lower()
    req_port = getattr(request, "port", None)
    if req_host not in _SELF_HOSTS or req_port not in ctx.addon._proxy_own_ports():
        return Outcome.CONTINUE
    targets = targets_from_env()
    if not targets:
        return Outcome.CONTINUE
    target = targets[0]
    if _get_in_container()():
        request.host = GATEWAY_HOSTNAME
    else:
        request.host = target.host
    if target.port:
        request.port = target.port
    request.scheme = "http"
    ctx.url = getattr(request, "pretty_url", "")
    return Outcome.CONTINUE


def _bridge_target_model(flow: Any, url: str) -> str | None:
    target_model = os.getenv("AGY_MODEL") or os.getenv("HOLON_LOCAL_MODEL")
    if not target_model:
        path_or_url = getattr(flow.request, "path", "") or url
        match = re.search(r"/models/([^/:]+)", path_or_url)
        if match:
            target_model = match.group(1)
    return target_model


def _bridge_gemini(ctx: RequestContext) -> None:
    """Gemini v1beta bridge to OpenAI /v1/chat/completions for host-local engines."""
    flow, url = ctx.flow, ctx.url
    flow.is_gemini_bridged = True
    target_model = _bridge_target_model(flow, url)
    data = translate_gemini_to_openai_request(ctx.data, model=target_model or "default")
    flow.request.path = "/v1/chat/completions"
    if ":streamgeneratecontent" in url.lower() or "alt=sse" in url.lower():
        data["stream"] = True
    flow.request.set_text(json.dumps(data))
    ctx.data = data


def adapt_local_protocol(ctx: RequestContext) -> Outcome:
    """Translate or normalise request payloads bound for host-local engines."""
    if ctx.provider == "gemini" and ctx.is_local and ctx.data is not None:
        _bridge_gemini(ctx)

    # Strict Anthropic normaliser for host-local engines
    if ctx.provider == "anthropic" and ctx.is_local and ctx.data is not None:
        ctx.data, _ = normalize_anthropic_request(ctx.flow, ctx.data, is_local=True)
        ctx.flow.request.set_text(json.dumps(ctx.data))
    return Outcome.CONTINUE
