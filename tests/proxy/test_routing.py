"""Unit tests for routing heuristics and mock response generation."""

from __future__ import annotations

from unittest.mock import MagicMock

from holon_coherence.proxy.routing import _make_http_response, is_local_target


def test_is_local_target() -> None:
    flow = MagicMock()
    flow.request.pretty_host = "localhost"
    flow.request.pretty_url = "http://localhost:8080/v1/chat"
    assert is_local_target(flow) is True

    flow.request.pretty_host = "127.0.0.1"
    assert is_local_target(flow) is True

    flow.request.pretty_host = "api.anthropic.com"
    flow.provider = "anthropic"
    assert is_local_target(flow) is False

    flow.request.pretty_host = "custom-local-llm.internal"
    flow.provider = "anthropic"
    assert is_local_target(flow) is True


def test_make_http_response_fallback() -> None:
    flow = MagicMock()
    del flow.Response
    resp = _make_http_response(flow, 200, b'{"status": "ok"}', {"Content-Type": "application/json"})
    assert resp.status_code == 200
    assert resp.content == b'{"status": "ok"}'
    assert resp.get_text() == '{"status": "ok"}'
    resp.set_text("updated")
    assert resp.content == b"updated"
