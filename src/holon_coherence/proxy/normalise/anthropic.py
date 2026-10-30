"""Anthropic payload normalisation for host-local engines."""

from __future__ import annotations

from typing import Any

from holon_coherence.proxy.routing import is_local_target

__all__ = ["normalize_anthropic_request"]


def normalize_anthropic_request(  # noqa: C901, PLR0912
    flow: Any,
    data: dict[str, Any],
    is_local: bool | None = None,
) -> tuple[dict[str, Any], bool]:
    """Normalizes Anthropic request for host-local engines by stripping vendor-specific fields.

    Strips thinking, output_config, context_management, vendor anthropic-beta headers,
    and prompt cache control blocks when targeting host-local servers.
    """
    if is_local is None:
        is_local = is_local_target(flow)

    if not is_local:
        return data, False

    # 1. Pop unsupported vendor blocks from top-level body
    data.pop("thinking", None)
    data.pop("output_config", None)
    data.pop("context_management", None)

    # 2. Recursively strip cache_control from messages
    messages = data.get("messages")
    if isinstance(messages, list):
        for msg in messages:
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict):
                            part.pop("cache_control", None)
                elif isinstance(content, dict):
                    content.pop("cache_control", None)

    # 3. Strip cache_control from system prompts
    system = data.get("system")
    if isinstance(system, list):
        for part in system:
            if isinstance(part, dict):
                part.pop("cache_control", None)
    elif isinstance(system, dict):
        system.pop("cache_control", None)

    # 4. Strip cache_control from tool definitions
    tools = data.get("tools")
    if isinstance(tools, list):
        for tool in tools:
            if isinstance(tool, dict):
                tool.pop("cache_control", None)

    # 5. Remove vendor anthropic-beta header from request headers
    req = getattr(flow, "request", None)
    if req is not None and hasattr(req, "headers") and req.headers is not None:
        headers = req.headers
        if hasattr(headers, "keys"):
            for k in list(headers.keys()):
                if str(k).lower() == "anthropic-beta":
                    del headers[k]

    return data, True
