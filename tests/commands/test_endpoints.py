"""Unit tests for endpoint resolution, table row formatting, and display helpers."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from holon_coherence.cli import main
from holon_coherence.commands.docker_ops import get_container_web_token
from holon_coherence.commands.endpoints import (
    ExposedEndpoints,
    format_endpoint_rows,
    print_endpoints,
    resolve_container_endpoints,
)
from holon_coherence.commands.metrics import handle_metrics


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
            patch(
                "holon_coherence.commands.endpoints.get_container_mapped_port",
                side_effect=lambda _n, p: 8080 if p == 8080 else None,
            ),
        ):
            eps = resolve_container_endpoints("my-box")
            assert eps.proxy_port == 8080
            assert eps.web_port is None
            assert eps.web_token is None


class TestEndpointReporting:
    """``status``, ``metrics`` and ``web-token`` report the resolved endpoints, never a stale URL."""

    @staticmethod
    def _mapped_ports(mapping: dict[int, int | None]) -> Any:
        return lambda _name, container_port: mapping.get(container_port)

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

    def test_status_prints_all_endpoints_when_running(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("holon_coherence.commands.docker_ops.is_container_running", return_value=True),
            patch("holon_coherence.commands.endpoints.is_container_running", return_value=True),
            patch(
                "holon_coherence.commands.endpoints.get_container_mapped_port",
                side_effect=self._mapped_ports({8080: 8080, 8081: 8082}),
            ),
            patch("holon_coherence.commands.endpoints.get_container_web_token", return_value="tok"),
            patch("subprocess.run", return_value=MagicMock(returncode=0)),
            patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")),
        ):
            main(["status"])
        out = capsys.readouterr().out
        assert "Proxy Listen Address         : 127.0.0.1:8080" in out
        assert "Coherence Live Dashboard     : http://127.0.0.1:8080/holon/" in out
        assert "mitmweb Req/Resp Inspector   : http://127.0.0.1:8082/?token=tok" in out

    def test_status_reports_inspector_not_running_without_stale_url(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("holon_coherence.commands.docker_ops.is_container_running", return_value=False),
            patch("holon_coherence.commands.endpoints.is_container_running", return_value=False),
            patch("holon_coherence.commands.web_token.get_active_web_token", return_value="stale-token"),
            patch("subprocess.run", return_value=MagicMock(returncode=0)),
        ):
            main(["status"])
        out = capsys.readouterr().out
        assert "mitmweb inspector: not running" in out
        assert "?token=" not in out
        assert "stale-token" not in out

    def test_status_headless_container_reports_inspector_not_running(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("holon_coherence.commands.docker_ops.is_container_running", return_value=True),
            patch("holon_coherence.commands.endpoints.is_container_running", return_value=True),
            patch(
                "holon_coherence.commands.endpoints.get_container_mapped_port",
                side_effect=self._mapped_ports({8080: 8080}),
            ),
            patch("holon_coherence.commands.web_token.get_active_web_token", return_value="stale-token"),
            patch("subprocess.run", return_value=MagicMock(returncode=0)),
            patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")),
        ):
            main(["status"])
        out = capsys.readouterr().out
        assert "Proxy Listen Address         : 127.0.0.1:8080" in out
        assert "mitmweb Req/Resp Inspector   : not running (headless; enable with --web or HOLON_COHERENCE_WEB=1)" in (
            out
        )
        assert "stale-token" not in out

    @staticmethod
    def _empty_metrics_response() -> MagicMock:
        # Transport fixture only: zero counters exercise the table layout, no figures are asserted.
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({}).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        return mock_resp

    def test_metrics_table_prints_all_endpoints(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("urllib.request.urlopen", return_value=self._empty_metrics_response()),
            patch("holon_coherence.commands.endpoints.is_container_running", return_value=True),
            patch(
                "holon_coherence.commands.endpoints.get_container_mapped_port",
                side_effect=self._mapped_ports({8080: 8080, 8081: 8083}),
            ),
            patch("holon_coherence.commands.endpoints.get_container_web_token", return_value="tok"),
        ):
            assert handle_metrics(port=9000) == 0
        out = capsys.readouterr().out
        # An explicit --port is honoured for the proxy rows; the inspector comes from the container.
        assert "Proxy Listen Address         : 127.0.0.1:9000" in out
        assert "Coherence Live Dashboard     : http://127.0.0.1:9000/holon/" in out
        assert "mitmweb Req/Resp Inspector   : http://127.0.0.1:8083/?token=tok" in out

    def test_metrics_json_does_not_include_token(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("urllib.request.urlopen", return_value=self._empty_metrics_response()),
            patch("holon_coherence.commands.endpoints.is_container_running", return_value=True),
            patch(
                "holon_coherence.commands.endpoints.get_container_mapped_port",
                side_effect=self._mapped_ports({8080: 8080, 8081: 8081}),
            ),
            patch("holon_coherence.commands.endpoints.get_container_web_token", return_value="tok-secret"),
        ):
            assert handle_metrics(port=8080, json_output=True) == 0
        out = capsys.readouterr().out
        assert "tok-secret" not in out
        assert json.loads(out) == {}

    def test_metrics_down_reports_inspector_not_running(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")),
            patch("holon_coherence.commands.web_token.get_active_web_token", return_value="stale-token"),
        ):
            assert handle_metrics(port=8080) == 1
        out = capsys.readouterr().out
        assert "PROXY STATUS: DOWN" in out
        assert "mitmweb inspector: not running" in out
        assert "stale-token" not in out

    def test_web_token_prints_resolved_inspector_url(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("holon_coherence.commands.web_token.get_container_web_token", return_value="tok"),
            patch("holon_coherence.commands.web_token.is_container_running", return_value=True),
            patch(
                "holon_coherence.commands.web_token.get_container_mapped_port",
                side_effect=self._mapped_ports({8081: 8084}),
            ),
            pytest.raises(SystemExit) as exc,
        ):
            main(["web-token"])
        assert exc.value.code == 0
        assert "mitmweb Req/Resp Inspector: http://127.0.0.1:8084/?token=tok" in capsys.readouterr().out

    @pytest.mark.parametrize("command", ["web-token", "web-key"])
    def test_web_token_name_selects_container(self, command: str, capsys: pytest.CaptureFixture[str]) -> None:
        ports = {"a": {8081: 8081}, "b": {8081: 8091}}
        tokens = {"a": "tok-a", "b": "tok-b"}
        with (
            patch("holon_coherence.commands.web_token.is_container_running", return_value=True),
            patch(
                "holon_coherence.commands.web_token.get_container_mapped_port",
                side_effect=lambda name, port: ports[name][port],
            ),
            patch("holon_coherence.commands.web_token.get_container_web_token", side_effect=lambda name: tokens[name]),
            pytest.raises(SystemExit) as exc,
        ):
            main([command, "--name", "b"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "http://127.0.0.1:8091/?token=tok-b" in out
        assert "tok-a" not in out

    def test_web_token_unavailable_names_recovery_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("holon_coherence.commands.web_token.is_container_running", return_value=True),
            patch(
                "holon_coherence.commands.web_token.get_container_mapped_port",
                side_effect=self._mapped_ports({8081: 8081}),
            ),
            patch("holon_coherence.commands.web_token.get_container_web_token", return_value=None),
            pytest.raises(SystemExit) as exc,
        ):
            main(["web-token", "--name", "manual-proxy"])
        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "token unavailable for container 'manual-proxy'" in out
        assert "docker exec manual-proxy sh -c 'cat \"$HOME/.holon/web-token\"'" in out
        assert "?token=" not in out

    def test_two_named_containers_each_report_their_own_token(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # ``start --name a`` then ``start --name b``: the shared file holds b's token, but a's inspector accepts a's.
        ports = {"a": {8080: 8080, 8081: 8081}, "b": {8080: 8090, 8081: 8091}}
        tokens = {"a": "tok-a", "b": "tok-b"}
        with (
            patch("holon_coherence.commands.docker_ops.is_container_running", return_value=True),
            patch("holon_coherence.commands.endpoints.is_container_running", return_value=True),
            patch("holon_coherence.commands.web_token.is_container_running", return_value=True),
            patch(
                "holon_coherence.commands.endpoints.get_container_mapped_port",
                side_effect=lambda name, port: ports[name][port],
            ),
            patch(
                "holon_coherence.commands.web_token.get_container_mapped_port",
                side_effect=lambda name, port: ports[name][port],
            ),
            patch("holon_coherence.commands.endpoints.get_container_web_token", side_effect=lambda name: tokens[name]),
            patch("holon_coherence.commands.web_token.get_container_web_token", side_effect=lambda name: tokens[name]),
            patch("holon_coherence.commands.web_token.get_active_web_token", return_value="tok-b"),
            patch("subprocess.run", return_value=MagicMock(returncode=0)),
            patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")),
        ):
            main(["status", "--name", "a"])
            out_a = capsys.readouterr().out
            main(["status", "--name", "b"])
            out_b = capsys.readouterr().out
            monkeypatch.setenv("HOLON_CONTAINER_NAME", "a")
            with pytest.raises(SystemExit) as exc:
                main(["web-token"])
            out_web_a = capsys.readouterr().out
        assert "mitmweb Req/Resp Inspector   : http://127.0.0.1:8081/?token=tok-a" in out_a
        assert "tok-b" not in out_a
        assert "mitmweb Req/Resp Inspector   : http://127.0.0.1:8091/?token=tok-b" in out_b
        assert exc.value.code == 0
        assert "mitmweb Req/Resp Inspector: http://127.0.0.1:8081/?token=tok-a" in out_web_a
        assert "tok-b" not in out_web_a

    def test_web_token_running_inspector_without_container_token_gives_no_stale_url(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with (
            patch("holon_coherence.commands.web_token.is_container_running", return_value=True),
            patch(
                "holon_coherence.commands.web_token.get_container_mapped_port",
                side_effect=self._mapped_ports({8081: 8081}),
            ),
            patch("holon_coherence.commands.web_token.get_container_web_token", return_value=None),
            patch("holon_coherence.commands.web_token.get_active_web_token", return_value="stale-token"),
            pytest.raises(SystemExit) as exc,
        ):
            main(["web-token"])
        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "token unavailable for container 'holon-coherence-proxy'" in out
        assert "stale-token" not in out
        assert "?token=" not in out

    def test_get_container_web_token_reads_container_env(self) -> None:
        env = '["PATH=/usr/bin","HOLON_COHERENCE_WEB_PASSWORD=tok-from-env","OTHER=x"]\n'
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout=env)) as mock_run:
            assert get_container_web_token("a") == "tok-from-env"
        assert mock_run.call_args[0][0] == ["docker", "inspect", "-f", "{{json .Config.Env}}", "a"]
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout='["PATH=/usr/bin"]')):
            assert get_container_web_token("a") is None
        with patch("subprocess.run", return_value=MagicMock(returncode=1, stdout="")):
            assert get_container_web_token("a") is None
        with patch("subprocess.run", side_effect=FileNotFoundError("docker")):
            assert get_container_web_token("a") is None
