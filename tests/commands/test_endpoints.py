"""Unit tests for endpoint resolution, table row formatting, and display helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from holon_coherence.commands.endpoints import (
    ExposedEndpoints,
    format_endpoint_rows,
    format_table_row,
    inspector_url,
    print_endpoints,
    resolve_container_endpoints,
    token_recovery_command,
)


class TestEndpointsFormatting:
    """Tests for rendering endpoint table rows."""

    def test_format_endpoint_rows_alignment(self) -> None:
        rows = format_endpoint_rows(ExposedEndpoints(proxy_port=8080, web_port=8081, web_token="tok"))
        assert rows == [
            "  Proxy Listen Address         : 127.0.0.1:8080",
            "  Coherence Live Dashboard     : http://127.0.0.1:8080/holon/",
            "  mitmweb Req/Resp Inspector   : http://127.0.0.1:8081/?token=tok",
        ]

    def test_format_endpoint_rows_without_token_gives_a_hint_not_a_url(self) -> None:
        rows = format_endpoint_rows(ExposedEndpoints(proxy_port=8080, web_port=8081, web_token=None))
        assert "?token=" not in rows[2]
        assert "running on 127.0.0.1:8081 (token unavailable; recover it with: " in rows[2]
        assert "docker exec <container> sh -c 'cat \"$HOME/.holon/web-token\"'" in rows[2]
        no_token = ExposedEndpoints(proxy_port=8080, web_port=8081, web_token=None)
        named = format_endpoint_rows(no_token, container_name="a")
        assert "docker exec a sh -c" in named[2]

    def test_format_endpoint_rows_when_down(self) -> None:
        rows = format_endpoint_rows(ExposedEndpoints(proxy_port=None, web_port=None, web_token="stale"))
        assert all(row.endswith(": not running") for row in rows)

    def test_print_endpoints(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_endpoints(ExposedEndpoints(proxy_port=8080, web_port=None, web_token=None))
        out = capsys.readouterr().out
        assert "Exposed Endpoints" in out
        assert "127.0.0.1:8080" in out
        assert "not running" in out


class TestResolveContainerEndpoints:
    """Tests for resolving container ports and token into ExposedEndpoints."""

    def test_resolve_container_endpoints_when_running(self) -> None:
        with (
            patch("holon_coherence.commands.endpoints.is_container_running", return_value=True),
            patch("holon_coherence.commands.endpoints.get_container_mapped_port", side_effect=lambda _n, p: p),
            patch("holon_coherence.commands.endpoints.get_container_web_token", return_value="tok-val"),
        ):
            eps = resolve_container_endpoints("my-box")
            assert eps.proxy_port == 8080
            assert eps.web_port == 8081
            assert eps.web_token == "tok-val"

    def test_resolve_container_endpoints_when_not_running(self) -> None:
        with patch("holon_coherence.commands.endpoints.is_container_running", return_value=False):
            eps = resolve_container_endpoints("my-box")
            assert eps.proxy_port is None
            assert eps.web_port is None
            assert eps.web_token is None

    def test_resolve_container_endpoints_headless(self) -> None:
        with (
            patch("holon_coherence.commands.endpoints.is_container_running", return_value=True),
            patch("holon_coherence.commands.endpoints.get_container_mapped_port", side_effect=lambda _n, p: 8080 if p == 8080 else None),
        ):
            eps = resolve_container_endpoints("my-box")
            assert eps.proxy_port == 8080
            assert eps.web_port is None
            assert eps.web_token is None
