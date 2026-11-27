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
from holon_coherence.providers.registry import UNKNOWN_PROVIDER_NAME, is_non_cloud_provider_host

__all__ = ["_make_http_response", "is_local_target"]

LOCAL_LOOPBACK_HOSTS = (
    "localhost",
    "127.0.0.1",
    "::1",
    "127.0.0.1.nip.io",
    "localhost.nip.io",
    GATEWAY_HOSTNAME,
)


def _make_http_response(flow: Any, status_code: int, content: bytes, headers: dict[str, str]) -> Any:
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
    req = getattr(flow, "request", None)
    if req is None:
        return False
    host = getattr(req, "pretty_host", "") or getattr(req, "host", "")
    url = getattr(req, "pretty_url", "")
    if not host and url:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        host = parsed.hostname or ""

    host_lower = host.lower()
    if host_lower in LOCAL_LOOPBACK_HOSTS:
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

    provider = getattr(flow, "provider", UNKNOWN_PROVIDER_NAME)
    return is_non_cloud_provider_host(provider, host_lower)
