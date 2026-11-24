from __future__ import annotations

from typing import Any

from holon_coherence.proxy.routing import is_local_target

__all__ = ["normalize_anthropic_request"]

UNSUPPORTED_LOCAL_ANTHROPIC_TOP_LEVEL_KEYS = (
    "thinking",
    "output_config",
    "context_management",
)
CACHE_CONTROL_KEY = "cache_control"
ANTHROPIC_BETA_HEADER = "anthropic-beta"


def normalize_anthropic_request(  # noqa: C901, PLR0912
    flow: Any,
    data: dict[str, Any],
    is_local: bool | None = None,
) -> tuple[dict[str, Any], bool]:
    if is_local is None:
        is_local = is_local_target(flow)

    if not is_local:
        return data, False

    for unsupported_key in UNSUPPORTED_LOCAL_ANTHROPIC_TOP_LEVEL_KEYS:
        data.pop(unsupported_key, None)

    messages = data.get("messages")
    if isinstance(messages, list):
        for msg in messages:
            if isinstance(msg, dict):
                msg.pop(CACHE_CONTROL_KEY, None)
                content = msg.get("content")
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict):
                            part.pop(CACHE_CONTROL_KEY, None)
                elif isinstance(content, dict):
                    content.pop(CACHE_CONTROL_KEY, None)

    system = data.get("system")
    if isinstance(system, list):
        for part in system:
            if isinstance(part, dict):
                part.pop(CACHE_CONTROL_KEY, None)
    elif isinstance(system, dict):
        system.pop(CACHE_CONTROL_KEY, None)

    tools = data.get("tools")
    if isinstance(tools, list):
        for tool in tools:
            if isinstance(tool, dict):
                tool.pop(CACHE_CONTROL_KEY, None)

    req = getattr(flow, "request", None)
    if req is not None and hasattr(req, "headers") and req.headers is not None:
        headers = req.headers
        if hasattr(headers, "keys"):
            for k in list(headers.keys()):
                if str(k).lower() == ANTHROPIC_BETA_HEADER:
                    del headers[k]

    return data, True
