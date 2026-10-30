"""Routing heuristics and host-local target detection."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

try:
    from mitmproxy import http
except ImportError:
    http = None

from holon_coherence.host_local import (
    GATEWAY_HOSTNAME,
    targets_from_env,
)

__all__ = ["_make_http_response", "is_local_target"]


def _make_http_response(flow: Any, status_code: int, content: bytes, headers: dict[str, str]) -> Any:
    """Creates an HTTP response object compatible with both live mitmproxy and mock test harnesses."""
    response_cls = getattr(http, "Response", None) or getattr(flow, "Response", None) or globals().get("Response")
    if response_cls and hasattr(response_cls, "make"):
        return response_cls.make(status_code, content, headers)

    class _SimpleResponse:
        def __init__(self, sc: int, body: bytes, hdrs: dict[str, str]):
            self.status_code = sc
            self.headers = hdrs
            self.content = body
            self._text = body.decode("utf-8", errors="ignore")

        def get_text(self) -> str:
            return self._text

        def set_text(self, text: str) -> None:
            self._text = text
            self.content = text.encode("utf-8")

    return _SimpleResponse(status_code, content, headers)


def is_local_target(flow: Any) -> bool:
    """Checks whether flow is directed to a local or non-cloud target."""
    req = getattr(flow, "request", None)
    if req is None:
        return False
    host = getattr(req, "pretty_host", "") or getattr(req, "host", "")
    url = getattr(req, "pretty_url", "")
    if not host and url:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        host = parsed.hostname or ""

    host_lower = host.lower()
    if host_lower in ("localhost", "127.0.0.1", "::1", "127.0.0.1.nip.io", "localhost.nip.io", GATEWAY_HOSTNAME):
        return True

    targets = targets_from_env()
    for t in targets:
        if t.host == host_lower or t.canonical == host_lower:
            return True
        if (
            hasattr(req, "port")
            and t.port
            and t.port == req.port
            and t.host in ("localhost", "127.0.0.1", "::1", host_lower)
        ):
            return True

    cloud_anthropic = ("api.anthropic.com", "anthropic.com")
    provider = getattr(flow, "provider", "unknown")
    if provider == "anthropic" and host_lower and host_lower not in cloud_anthropic:
        return True

    cloud_gemini = ("generativelanguage.googleapis.com", "googleapis.com")
    return bool(provider == "gemini" and host_lower and not any(host_lower.endswith(c) for c in cloud_gemini))
