"""Response header access shared by the cache-hit and cache-miss telemetry steps."""

from __future__ import annotations

from typing import Any

__all__ = ["writable_headers"]


def writable_headers(flow: Any) -> Any:
    """The flow's response headers if they can be assigned to, else ``None``."""
    response = getattr(flow, "response", None)
    if response is None or not hasattr(response, "headers"):
        return None
    headers = response.headers
    if headers is None or not hasattr(headers, "__setitem__"):
        return None
    return headers
