"""Unit tests for start command, container orchestration, route planning, and readiness checks."""

from __future__ import annotations

import argparse
import email.message
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from holon_coherence.cli import main
from holon_coherence.commands.agents import build_agent_env
from holon_coherence.commands.docker_ops import (
    CONTAINER_NAME,
    check_docker_daemon,
    is_container_bound_to_port,
    is_container_running,
)
from holon_coherence.commands.runner import build_proxy_env, merge_no_proxy_values
from holon_coherence.commands.start import (
    container_host_local_spec,
    docker_host_alias_args,
    ensure_proxy_running,
    handle,
    host_local_container_args,
    host_local_covered,
    plan_local_llm_route,
    probe_host_local_reachable,
    register,
    report_local_llm_route,
    wait_for_proxy_ready,
)
from holon_coherence.host_local import HOST_LOCAL_ENV_VAR


class TestWaitForProxyReadySuite:
    """Tests for wait_for_proxy_ready HTTP polling."""

    def test_wait_for_proxy_ready_immediate_success(self) -> None:
        mock_resp = MagicMock(status=200)
        with (
            patch("holon_coherence.commands.start.is_container_running", return_value=True),
            patch("holon_coherence.commands.start._urlopen_no_proxy", return_value=mock_resp),
        ):
            assert wait_for_proxy_ready(8080) is True

    def test_wait_for_proxy_ready_fail_fast_when_container_exits(self) -> None:
        with (
            patch("holon_coherence.commands.start.is_container_running", side_effect=[True, False]),
            patch(
                "holon_coherence.commands.start._urlopen_no_proxy",
                side_effect=urllib.error.URLError(ConnectionRefusedError()),
            ),
            patch("time.sleep"),
        ):
            assert wait_for_proxy_ready(8080, timeout=15.0) is False


class TestPlanAndReportLocalLlmRouteSuite:
    """Tests for local LLM routing plan and reachability reporting."""

    def test_plan_local_llm_route_valid(self) -> None:
        with patch("holon_coherence.commands.start.detect_host_addresses", return_value=("192.168.2.13",)):
            route = plan_local_llm_route("localhost:8081")
            assert route is not None
            assert route.target.canonical == "localhost:8081"
            assert route.target.port == 8081

    def test_plan_local_llm_route_invalid(self) -> None:
        assert plan_local_llm_route("localhost:") is None
        assert plan_local_llm_route("localhost:notaport") is None

    def test_report_local_llm_route_reachable(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("holon_coherence.commands.start.detect_host_addresses", return_value=("192.168.2.13",)):
            route = plan_local_llm_route("localhost:8081")
            assert route is not None
            dropped = report_local_llm_route(route, reachable=True, detail="ok")
            assert len(dropped) > 0
            captured = capsys.readouterr()
            assert "Removing" in captured.out


class TestEnsureProxyRunningSuite:
    """Tests for ensure_proxy_running background sidecar launch."""

    def test_reuse_existing_healthy_container(self) -> None:
        with (
            patch("holon_coherence.commands.start.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.commands.start.is_port_in_use", return_value=True),
            patch("holon_coherence.commands.start.is_container_running", return_value=True),
            patch("holon_coherence.commands.start.is_container_bound_to_port", return_value=True),
            patch("subprocess.run") as mock_run,
        ):
            started = ensure_proxy_running(port=8080)
            assert started is False
            mock_run.assert_not_called()

    def test_ensure_proxy_running_launches_new_container(self) -> None:
        with (
            patch("holon_coherence.commands.start.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.commands.start.is_port_in_use", return_value=False),
            patch("holon_coherence.commands.start.is_container_running", return_value=False),
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch("subprocess.run", return_value=MagicMock(returncode=0)),
            patch("holon_coherence.commands.start.wait_for_proxy_ready", return_value=True),
        ):
            started = ensure_proxy_running(port=8080)
            assert started is True


class TestStartCommandRegistrationAndDispatch:
    """Tests for start subparser registration and argument dispatch."""

    def test_register_and_defaults(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)

        args = parser.parse_args(["start", "-d", "--port", "8888"])
        assert args.command == "start"
        assert args.detach is True
        assert args.port == 8888
        assert args.handler == handle

    def test_handle_start_dispatch(self) -> None:
        args = argparse.Namespace(
            command="start",
            port=8080,
            detach=True,
            image="holon-coherence:latest",
            passive=False,
            build=False,
            local_llm_base=None,
            web=False,
            name=None,
        )
        with (
            patch("holon_coherence.commands.start.is_in_container", return_value=False),
            patch("holon_coherence.commands.start.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.commands.start.is_port_in_use", return_value=False),
            patch("holon_coherence.commands.start.ensure_docker_image"),
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch("subprocess.run", return_value=MagicMock(returncode=0)),
        ):
            res = handle(args)
            assert res == 0


class TestDockerDiagnosticsAndPortConflicts:
    """Tests for Docker daemon diagnostic handling and port conflict detection."""

    def test_docker_cli_missing(self) -> None:
        with patch("shutil.which", return_value=None):
            ok, err = check_docker_daemon()
            assert ok is False
            assert "Docker CLI is not installed" in err

    def test_docker_daemon_not_running(self) -> None:
        mock_res = MagicMock()
        mock_res.returncode = 1
        with (
            patch("shutil.which", return_value="/usr/local/bin/docker"),
            patch("subprocess.run", return_value=mock_res) as mock_run,
        ):
            ok, err = check_docker_daemon()
            assert ok is False
            assert "Docker daemon is not running" in err
            mock_run.assert_called_once_with(
                ["docker", "info"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5.0,
            )

    def test_docker_daemon_timeout(self) -> None:
        timeout_err = subprocess.TimeoutExpired(cmd=["docker", "info"], timeout=5.0)
        with (
            patch("shutil.which", return_value="/usr/local/bin/docker"),
            patch("subprocess.run", side_effect=timeout_err) as mock_run,
        ):
            ok, err = check_docker_daemon()
            assert ok is False
            assert "timed out" in err
            mock_run.assert_called_once_with(
                ["docker", "info"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5.0,
            )

    def test_port_conflict_detection_when_container_not_running(self) -> None:
        with (
            patch("holon_coherence.commands.start.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.commands.start.is_port_in_use", return_value=True),
            patch("holon_coherence.commands.start.is_container_running", return_value=False),
            pytest.raises(SystemExit) as exc_info,
        ):
            ensure_proxy_running(port=8080)
        assert exc_info.value.code == 1

    def test_reuse_existing_healthy_container(self) -> None:
        with (
            patch("holon_coherence.commands.start.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.commands.start.is_port_in_use", return_value=True),
            patch("holon_coherence.commands.start.is_container_running", return_value=True),
            patch("holon_coherence.commands.start.is_container_bound_to_port", return_value=True),
            patch("subprocess.run") as mock_run,
        ):
            started = ensure_proxy_running(port=8080)
            assert started is False
            # Should return immediately without docker run
            mock_run.assert_not_called()

    def test_ensure_proxy_running_launches_new_container_returns_true(self) -> None:
        with (
            patch("holon_coherence.commands.start.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.commands.start.is_port_in_use", return_value=False),
            patch("holon_coherence.commands.start.is_container_running", return_value=False),
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch(
                "subprocess.run",
                side_effect=[
                    MagicMock(returncode=0),  # inspect image
                    MagicMock(returncode=0),  # rm -f
                    MagicMock(returncode=0),  # docker run
                ],
            ) as mock_run,
            patch("holon_coherence.commands.start.wait_for_proxy_ready", return_value=True),
        ):
            started = ensure_proxy_running(port=8080)
            assert started is True
            docker_cmd = mock_run.call_args_list[2][0][0]
            assert "--init" in docker_cmd

    def test_container_already_running_on_different_port_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("holon_coherence.commands.start.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.commands.start.is_port_in_use", return_value=False),
            patch("holon_coherence.commands.start.is_container_running", return_value=True),
            patch("holon_coherence.commands.start.is_container_bound_to_port", return_value=False),
            pytest.raises(SystemExit) as exc_info,
        ):
            ensure_proxy_running(port=9090)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error: A holon-coherence proxy container is already running on a different port." in captured.err
        assert "Stop it first using 'holon-coherence stop' before launching on port 9090." in captured.err

    def test_container_unresponsive_diagnostic(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("holon_coherence.commands.start.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.commands.start.is_port_in_use", return_value=False),
            patch("holon_coherence.commands.start.is_container_running", return_value=True),
            patch("holon_coherence.commands.start.is_container_bound_to_port", return_value=True),
            patch("holon_coherence.commands.start.wait_for_proxy_ready", return_value=False) as mock_wait,
            pytest.raises(SystemExit) as exc_info,
        ):
            ensure_proxy_running(port=9090)
        assert exc_info.value.code == 1
        mock_wait.assert_called_once_with(9090)
        captured = capsys.readouterr()
        assert (
            "Error: A holon-coherence proxy container is running for port 9090, but is not responding." in captured.err
        )
        assert "Please restart it using 'holon-coherence stop' and retry." in captured.err

    def test_ensure_proxy_running_bound_container_becomes_ready(self) -> None:
        with (
            patch("holon_coherence.commands.start.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.commands.start.is_port_in_use", return_value=False),
            patch("holon_coherence.commands.start.is_container_running", return_value=True),
            patch("holon_coherence.commands.start.is_container_bound_to_port", return_value=True),
            patch("holon_coherence.commands.start.wait_for_proxy_ready", return_value=True) as mock_wait,
        ):
            result = ensure_proxy_running(port=9090)
        assert result is False
        mock_wait.assert_called_once_with(9090)

    def test_port_conflict_when_container_running_on_different_port(self) -> None:
        with (
            patch("holon_coherence.commands.start.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.commands.start.is_port_in_use", return_value=True),
            patch("holon_coherence.commands.start.is_container_running", return_value=True),
            patch("holon_coherence.commands.start.is_container_bound_to_port", return_value=False),
            pytest.raises(SystemExit) as exc_info,
        ):
            ensure_proxy_running(port=8080)
        assert exc_info.value.code == 1

    def test_is_container_bound_to_port_direct_match(self) -> None:
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = "127.0.0.1:8080\n"
        with patch("subprocess.run", return_value=mock_res):
            assert is_container_bound_to_port(8080) is True
            assert is_container_bound_to_port(9090) is False

    def test_is_container_bound_to_port_fallback(self) -> None:
        failed_res = MagicMock(returncode=1, stdout="")
        fallback_res = MagicMock(returncode=0, stdout="8080/tcp -> 127.0.0.1:9090\n")
        with patch("subprocess.run", side_effect=[failed_res, fallback_res]):
            assert is_container_bound_to_port(9090) is True

    def test_is_container_bound_to_port_failure(self) -> None:
        failed_res = MagicMock(returncode=1, stdout="")
        with patch("subprocess.run", return_value=failed_res):
            assert is_container_bound_to_port(8080) is False

    def test_is_container_running_timeout_returns_false(self) -> None:
        """is_container_running returns False when docker inspect times out."""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["docker"], timeout=5.0)):
            assert is_container_running() is False

    def test_is_container_running_oserror_returns_false(self) -> None:
        """is_container_running returns False when docker binary is missing (OSError)."""
        with patch("subprocess.run", side_effect=OSError("docker not found")):
            assert is_container_running() is False

    def test_is_container_bound_to_port_primary_timeout_returns_false(self) -> None:
        """is_container_bound_to_port returns False if primary docker port call times out."""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["docker", "port"], timeout=5.0)):
            assert is_container_bound_to_port(8080) is False

    def test_is_container_bound_to_port_fallback_timeout_returns_false(self) -> None:
        """is_container_bound_to_port returns False if fallback docker port call times out."""
        failed_res = MagicMock(returncode=1, stdout="")
        with patch(
            "subprocess.run",
            side_effect=[failed_res, subprocess.TimeoutExpired(cmd=["docker", "port"], timeout=5.0)],
        ):
            assert is_container_bound_to_port(8080) is False

    def test_is_container_bound_to_port_oserror_returns_false(self) -> None:
        """is_container_bound_to_port returns False when OSError raised on primary call."""
        with patch("subprocess.run", side_effect=OSError("no docker")):
            assert is_container_bound_to_port(8080) is False

    def test_ensure_proxy_running_timeout_combines_logs(self, capsys: pytest.CaptureFixture[str]) -> None:
        logs_res = MagicMock(returncode=0, stdout="out msg\n", stderr="err traceback\n")
        with (
            patch("holon_coherence.commands.start.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.commands.start.is_port_in_use", return_value=False),
            patch("holon_coherence.commands.start.is_container_running", return_value=False),
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch(
                "subprocess.run",
                side_effect=[
                    MagicMock(returncode=0),  # inspect image
                    MagicMock(returncode=0),  # rm -f
                    MagicMock(returncode=0),  # docker run
                    logs_res,  # docker logs
                ],
            ),
            patch("holon_coherence.commands.start.wait_for_proxy_ready", return_value=False),
            patch("holon_coherence.commands.start.stop_proxy_container") as mock_stop,
            pytest.raises(SystemExit) as exc_info,
        ):
            ensure_proxy_running(port=8080)
        assert exc_info.value.code == 1
        mock_stop.assert_called_once()
        captured = capsys.readouterr()
        assert "out msg" in captured.err
        assert "err traceback" in captured.err

    def test_ensure_proxy_running_build_failure(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("holon_coherence.commands.start.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.commands.start.is_port_in_use", return_value=False),
            patch("holon_coherence.commands.start.is_container_running", return_value=False),
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch(
                "subprocess.run",
                side_effect=[
                    MagicMock(returncode=1),  # inspect image fails
                    MagicMock(returncode=1),  # docker build fails
                ],
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            ensure_proxy_running(port=8080)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Failed to build Docker image" in captured.err

    def test_ensure_proxy_running_ghcr_pull_failure(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("holon_coherence.commands.start.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.commands.start.is_port_in_use", return_value=False),
            patch("holon_coherence.commands.start.is_container_running", return_value=False),
            patch("os.makedirs"),
            patch("os.path.exists", side_effect=lambda p: not str(p).endswith("Dockerfile")),
            patch(
                "subprocess.run",
                side_effect=[
                    MagicMock(returncode=1),  # inspect image fails
                    MagicMock(returncode=1),  # docker pull image fails
                    MagicMock(returncode=1),  # docker pull ghcr fails
                ],
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            ensure_proxy_running(port=8080)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Could not find or pull Docker image" in captured.err


class TestWaitForProxyReady:
    """Tests for wait_for_proxy_ready HTTP metrics polling and fail-fast container exit handling."""

    def test_wait_for_proxy_ready_immediate_success(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status = 200
        with (
            patch("holon_coherence.commands.start.is_container_running", return_value=True),
            patch("holon_coherence.commands.start._urlopen_no_proxy", return_value=mock_resp) as mock_urlopen,
            patch("time.sleep") as mock_sleep,
        ):
            assert wait_for_proxy_ready(8080) is True
            assert mock_urlopen.call_count == 1
            mock_sleep.assert_not_called()

    def test_wait_for_proxy_ready_retry_success(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status = 200
        side_effects = [
            urllib.error.URLError(ConnectionRefusedError("Connection refused")),
            urllib.error.URLError(ConnectionRefusedError("Connection refused")),
            mock_resp,
        ]
        with (
            patch("holon_coherence.commands.start.is_container_running", return_value=True),
            patch("holon_coherence.commands.start._urlopen_no_proxy", side_effect=side_effects) as mock_urlopen,
            patch("time.sleep") as mock_sleep,
        ):
            assert wait_for_proxy_ready(8080) is True
            assert mock_urlopen.call_count == 3
            assert mock_sleep.call_count == 2

    def test_wait_for_proxy_ready_fallback_endpoint_on_404(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status = 200
        http_404 = urllib.error.HTTPError(
            url="http://127.0.0.1:8080/holon/api/metrics",
            code=404,
            msg="Not Found",
            hdrs=email.message.Message(),
            fp=None,
        )
        with (
            patch("holon_coherence.commands.start.is_container_running", return_value=True),
            patch(
                "holon_coherence.commands.start._urlopen_no_proxy", side_effect=[http_404, mock_resp]
            ) as mock_urlopen,
            patch("time.sleep"),
        ):
            assert wait_for_proxy_ready(8080) is True
            assert mock_urlopen.call_count == 2
            first_url = mock_urlopen.call_args_list[0][0][0].full_url
            second_url = mock_urlopen.call_args_list[1][0][0].full_url
            assert first_url == "http://127.0.0.1:8080/holon/api/metrics"
            assert second_url == "http://127.0.0.1:8080/_holon/metrics"

    def test_wait_for_proxy_ready_fail_fast_when_container_exits(self) -> None:
        with (
            patch("holon_coherence.commands.start.is_container_running", side_effect=[True, False]),
            patch(
                "holon_coherence.commands.start._urlopen_no_proxy",
                side_effect=urllib.error.URLError(ConnectionRefusedError()),
            ),
            patch("time.sleep"),
        ):
            assert wait_for_proxy_ready(8080, timeout=15.0) is False

    def test_wait_for_proxy_ready_timeout(self) -> None:
        clock = [0.0]
        fake_time = MagicMock()
        fake_time.monotonic.side_effect = lambda: clock[0]
        fake_time.sleep.side_effect = lambda s: clock.__setitem__(0, clock[0] + 1.0)
        with (
            patch("holon_coherence.commands.start.is_container_running", return_value=True),
            patch(
                "holon_coherence.commands.start._urlopen_no_proxy",
                side_effect=urllib.error.URLError(ConnectionRefusedError()),
            ) as mock_urlopen,
            patch("holon_coherence.commands.start.time", fake_time),
        ):
            assert wait_for_proxy_ready(8080, timeout=3.0) is False
            assert mock_urlopen.call_count == 3
            assert fake_time.sleep.call_count == 3

    def test_wait_for_proxy_ready_non_404_http_error_retries_without_fallback(self) -> None:
        http_503 = urllib.error.HTTPError(
            url="http://127.0.0.1:8080/holon/api/metrics",
            code=503,
            msg="Service Unavailable",
            hdrs=email.message.Message(),
            fp=None,
        )
        mock_resp = MagicMock()
        mock_resp.status = 200
        with (
            patch("holon_coherence.commands.start.is_container_running", return_value=True),
            patch(
                "holon_coherence.commands.start._urlopen_no_proxy", side_effect=[http_503, mock_resp]
            ) as mock_urlopen,
            patch("time.sleep") as mock_sleep,
        ):
            assert wait_for_proxy_ready(8080) is True
            assert mock_urlopen.call_count == 2
            assert mock_urlopen.call_args_list[1][0][0].full_url == "http://127.0.0.1:8080/holon/api/metrics"
            assert mock_sleep.call_count == 1

    def test_wait_for_proxy_ready_ignores_env_proxy(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_opener = MagicMock()
        mock_opener.open.return_value = mock_resp
        with (
            patch("holon_coherence.commands.start.is_container_running", return_value=True),
            patch("urllib.request.build_opener", return_value=mock_opener) as mock_build,
            patch("time.sleep"),
        ):
            assert wait_for_proxy_ready(8080) is True
        handler = mock_build.call_args[0][0]
        assert isinstance(handler, urllib.request.ProxyHandler)
        assert handler.proxies == {}

    @staticmethod
    def _stepping_clock(wall_step: float) -> tuple[MagicMock, list[float], list[float]]:
        """Fake ``time`` module whose wall clock jumps by ``wall_step`` on the first sleep.

        Both clocks advance 0.25s per poll, as real clocks would; only the wall clock is stepped.
        A quarter-second tick keeps the monotonic arithmetic exact in binary floating point.
        """
        wall = [1_000_000.0]
        mono = [0.0]
        fake_time = MagicMock()
        fake_time.time.side_effect = lambda: wall[0]
        fake_time.monotonic.side_effect = lambda: mono[0]

        def fake_sleep(_seconds: float) -> None:
            if fake_time.sleep.call_count == 1:
                wall[0] += wall_step
            wall[0] += 0.25
            mono[0] += 0.25

        fake_time.sleep.side_effect = fake_sleep
        return fake_time, wall, mono

    def test_wait_for_proxy_ready_backwards_wall_step_does_not_extend(self) -> None:
        fake_time, _wall, _mono = self._stepping_clock(-3600.0)
        with (
            patch("holon_coherence.commands.start.is_container_running", return_value=True),
            patch(
                "holon_coherence.commands.start._urlopen_no_proxy",
                side_effect=urllib.error.URLError(ConnectionRefusedError()),
            ) as mock_urlopen,
            patch("holon_coherence.commands.start.time", fake_time),
        ):
            assert wait_for_proxy_ready(8080, timeout=1.0) is False
        # 1.0s budget at 0.25s per poll: exactly four attempts, regardless of the wall-clock step.
        assert mock_urlopen.call_count == 4
        assert fake_time.time.call_count == 0

    def test_wait_for_proxy_ready_forwards_wall_step_does_not_short_circuit(self) -> None:
        fake_time, _wall, _mono = self._stepping_clock(+3600.0)
        with (
            patch("holon_coherence.commands.start.is_container_running", return_value=True),
            patch(
                "holon_coherence.commands.start._urlopen_no_proxy",
                side_effect=urllib.error.URLError(ConnectionRefusedError()),
            ) as mock_urlopen,
            patch("holon_coherence.commands.start.time", fake_time),
        ):
            assert wait_for_proxy_ready(8080, timeout=1.0) is False
        assert mock_urlopen.call_count == 4
        assert fake_time.time.call_count == 0

    def test_wait_for_proxy_ready_returns_on_first_200_despite_wall_steps(self) -> None:
        fake_time, wall, _mono = self._stepping_clock(+3600.0)
        mock_resp = MagicMock()
        mock_resp.status = 200
        refused = urllib.error.URLError(ConnectionRefusedError("Connection refused"))

        attempts = [0]

        def flaky_open(_req: urllib.request.Request, timeout: float) -> Any:
            # Step the wall clock backwards on every attempt as well.
            wall[0] -= 7200.0
            attempts[0] += 1
            if attempts[0] <= 2:
                raise refused
            return mock_resp

        with (
            patch("holon_coherence.commands.start.is_container_running", return_value=True),
            patch("holon_coherence.commands.start._urlopen_no_proxy", side_effect=flaky_open) as mock_urlopen,
            patch("holon_coherence.commands.start.time", fake_time),
        ):
            assert wait_for_proxy_ready(8080, timeout=15.0) is True
        assert mock_urlopen.call_count == 3
        assert fake_time.sleep.call_count == 2
        assert fake_time.time.call_count == 0


class TestHostLocalContainerWiring:
    """The container must be able to resolve the host and know which authorities to reroute."""

    def test_add_host_flag_shape(self) -> None:
        assert docker_host_alias_args() == ["--add-host", "host.docker.internal:host-gateway"]

    def test_allow_list_env_flag_shape(self) -> None:
        assert host_local_container_args("localhost:8081") == ["-e", f"{HOST_LOCAL_ENV_VAR}=localhost:8081"]
        assert host_local_container_args("") == []

    def test_docker_run_includes_add_host_and_allow_list(self) -> None:
        with (
            patch("holon_coherence.commands.start.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.commands.start.is_port_in_use", return_value=False),
            patch("holon_coherence.commands.start.is_container_running", return_value=False),
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch(
                "subprocess.run",
                side_effect=[
                    MagicMock(returncode=0),  # image inspect
                    MagicMock(returncode=0),  # rm -f
                    MagicMock(returncode=0),  # docker run
                ],
            ) as mock_run,
            patch("holon_coherence.commands.start.wait_for_proxy_ready", return_value=True),
        ):
            assert ensure_proxy_running(port=8080, host_local_spec="localhost:8081") is True

        docker_cmd = mock_run.call_args_list[2][0][0]
        assert "--add-host" in docker_cmd
        assert "host.docker.internal:host-gateway" in docker_cmd
        assert "-e" in docker_cmd
        assert f"{HOST_LOCAL_ENV_VAR}=localhost:8081" in docker_cmd

    def test_start_command_also_adds_host_alias(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(HOST_LOCAL_ENV_VAR, raising=False)
        with (
            patch("holon_coherence.commands.start.is_in_container", return_value=False),
            patch("holon_coherence.commands.start.check_docker_daemon", return_value=(True, "")),
            patch("os.makedirs"),
            patch("holon_coherence.commands.start.generate_root_ca", return_value=("/tmp/ca.pem", "/tmp/ca.key")),
            patch("holon_coherence.commands.start.ensure_docker_image"),
            patch("subprocess.run") as mock_run,
        ):
            main(["start", "-d"])

        docker_cmd = mock_run.call_args_list[-1][0][0]
        assert docker_cmd[:2] == ["docker", "run"]
        assert "host.docker.internal:host-gateway" in docker_cmd

    def test_start_command_forwards_host_local_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(HOST_LOCAL_ENV_VAR, "localhost:11434")
        monkeypatch.delenv("HOLON_PROXY_PORT", raising=False)
        with (
            patch("holon_coherence.commands.start.is_in_container", return_value=False),
            patch("holon_coherence.commands.start.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.commands.start.is_port_in_use", return_value=False),
            patch("os.makedirs"),
            patch("holon_coherence.commands.start.generate_root_ca", return_value=("/tmp/ca.pem", "/tmp/ca.key")),
            patch("holon_coherence.commands.start.ensure_docker_image"),
            patch("subprocess.run") as mock_run,
        ):
            main(["start", "-d"])

        docker_cmd = mock_run.call_args_list[-1][0][0]
        assert f"{HOST_LOCAL_ENV_VAR}=localhost:11434" in docker_cmd
        # The container only knows its own listen port, so the published port has to be handed over
        # for the addon to refuse rewriting a client straight back into the proxy.
        assert "HOLON_PROXY_PORT=8080" in docker_cmd

    def test_running_container_env_is_read_back(self) -> None:
        stdout = f"HOLON_IN_CONTAINER=1\n{HOST_LOCAL_ENV_VAR}=localhost:8081,127.0.0.1:8081\nPATH=/usr/bin\n"
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout=stdout, stderr="")):
            assert container_host_local_spec() == "localhost:8081,127.0.0.1:8081"

    def test_running_container_env_missing_is_empty(self) -> None:
        with patch("subprocess.run", side_effect=OSError("docker missing")):
            assert container_host_local_spec() == ""

    def test_coverage_checks(self) -> None:
        assert host_local_covered("", "anything:1") is True
        assert host_local_covered("localhost:8081", "localhost:8081,127.0.0.1:8081") is True
        assert host_local_covered("localhost:8081", "localhost:11434") is False
        assert host_local_covered("localhost:8081", "") is False
        assert host_local_covered("localhost:8081", "localhost") is True

    def test_unfit_running_container_is_recreated(self) -> None:
        with (
            patch("holon_coherence.commands.start.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.commands.start.is_port_in_use", side_effect=[True, False, False]),
            patch("holon_coherence.commands.start.is_container_running", return_value=True),
            patch("holon_coherence.commands.start.is_container_bound_to_port", return_value=True),
            patch("holon_coherence.commands.start.container_host_local_spec", return_value="localhost:11434"),
            patch("holon_coherence.commands.start.stop_proxy_container") as mock_stop,
            patch("holon_coherence.commands.start.detect_host_addresses", return_value=()),
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch(
                "subprocess.run",
                side_effect=[
                    MagicMock(returncode=0),  # image inspect
                    MagicMock(returncode=0),  # rm -f
                    MagicMock(returncode=0),  # docker run
                ],
            ) as mock_subproc,
            patch("holon_coherence.commands.start.wait_for_proxy_ready", return_value=True),
        ):
            assert ensure_proxy_running(port=8080, host_local_spec="localhost:8081") is False
        mock_stop.assert_called_once()
        docker_run_cmd = mock_subproc.call_args_list[2][0][0]
        assert "HOLON_HOST_LOCAL_HOSTS=localhost:11434,localhost:8081" in docker_run_cmd
        assert "HOLON_PROXY_PORT=8080" in docker_run_cmd

    def test_merged_no_proxy_keeps_defaults_and_caller_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NO_PROXY", "internal.example")
        merged = merge_no_proxy_values()
        assert "localhost" in merged
        assert "internal.example" in merged

    def test_build_proxy_env_drops_pruned_entries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NO_PROXY", raising=False)
        monkeypatch.delenv("no_proxy", raising=False)
        env = build_proxy_env("http://127.0.0.1:8080", drop_no_proxy=("localhost", "127.0.0.1", "::1"))
        entries = {entry.strip() for entry in env["NO_PROXY"].split(",") if entry.strip()}
        assert {"localhost", "127.0.0.1", "::1"}.isdisjoint(entries)
        assert {"github.com", "169.254.169.254"} <= entries
        assert env["NO_PROXY"] == env["no_proxy"]

    def test_unfit_running_container_fails_if_port_cannot_be_freed(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("holon_coherence.commands.start.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.commands.start.is_port_in_use", return_value=True),
            patch("holon_coherence.commands.start.is_container_running", return_value=True),
            patch("holon_coherence.commands.start.is_container_bound_to_port", return_value=True),
            patch("holon_coherence.commands.start.container_host_local_spec", return_value="localhost:11434"),
            patch("holon_coherence.commands.start.stop_proxy_container") as mock_stop,
            patch("time.sleep"),
            pytest.raises(SystemExit) as exc_info,
        ):
            ensure_proxy_running(port=8080, host_local_spec="localhost:8081")

        assert exc_info.value.code == 1
        mock_stop.assert_called_once()
        captured = capsys.readouterr()
        assert "could not be freed after stopping container" in captured.err

    def test_build_agent_env_forwards_pruning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NO_PROXY", raising=False)
        monkeypatch.delenv("no_proxy", raising=False)
        env = build_agent_env("pi", 8080, drop_no_proxy=("localhost",))
        assert "localhost" not in {entry.strip() for entry in env["NO_PROXY"].split(",")}


class TestProbeHostLocalReachable:
    """Tests for probe_host_local_reachable() container execution and fallback."""

    def test_probe_python3_success(self) -> None:
        with patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            ok, detail = probe_host_local_reachable(8081)
            assert ok is True
            assert detail == ""
            cmd = mock_run.call_args[0][0]
            assert cmd[:4] == ["docker", "exec", CONTAINER_NAME, "python3"]

    def test_probe_python3_missing_falls_back_to_python(self) -> None:
        missing_proc = MagicMock(
            returncode=127,
            stderr='OCI runtime exec failed: exec: "python3": executable file not found in $PATH',
            stdout="",
        )
        success_proc = MagicMock(returncode=0, stderr="", stdout="")
        with patch("subprocess.run", side_effect=[missing_proc, success_proc]) as mock_run:
            ok, detail = probe_host_local_reachable(8081)
            assert ok is True
            assert detail == ""
            assert mock_run.call_count == 2
            assert mock_run.call_args_list[0][0][0][3] == "python3"
            assert mock_run.call_args_list[1][0][0][3] == "python"

    def test_probe_both_interpreters_missing(self) -> None:
        missing_proc = MagicMock(
            returncode=126,
            stderr='OCI runtime exec failed: unable to start container process: exec: "python": not found',
            stdout="",
        )
        with patch("subprocess.run", return_value=missing_proc) as mock_run:
            ok, detail = probe_host_local_reachable(8081)
            assert ok is False
            assert detail == "unreachable"
            assert mock_run.call_count == 2

    def test_probe_target_refused(self) -> None:
        fail_proc = MagicMock(
            returncode=1,
            stderr="Traceback (most recent call last):\nConnectionRefusedError: [Errno 111] Connection refused\n",
            stdout="",
        )
        with patch("subprocess.run", return_value=fail_proc) as mock_run:
            ok, detail = probe_host_local_reachable(8081)
            assert ok is False
            assert "ConnectionRefusedError" in detail
            mock_run.assert_called_once()

    def test_probe_timeout(self) -> None:
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="docker", timeout=15.0)):
            ok, detail = probe_host_local_reachable(8081)
            assert ok is False
            assert detail == "probe timed out"

    def test_probe_oserror(self) -> None:
        with patch("subprocess.run", side_effect=OSError("docker daemon not found")):
            ok, detail = probe_host_local_reachable(8081)
            assert ok is False
            assert "docker daemon not found" in detail

    def test_probe_parameterized_container_name(self) -> None:
        with patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            ok, _ = probe_host_local_reachable(8081, container_name="custom-container")
            assert ok is True
            assert mock_run.call_args[0][0][2] == "custom-container"

    def test_container_gateway_probe_filters_loopback_and_bracket_strips(self) -> None:
        from holon_coherence.cli import _CONTAINER_GATEWAY_PROBE

        assert "strip('[]')" in _CONTAINER_GATEWAY_PROBE
        assert "127." in _CONTAINER_GATEWAY_PROBE
        assert "::1" in _CONTAINER_GATEWAY_PROBE
        assert "fallback" in _CONTAINER_GATEWAY_PROBE
        assert "gateway name does not resolve" in _CONTAINER_GATEWAY_PROBE
        assert "no non-loopback gateway IP found" in _CONTAINER_GATEWAY_PROBE

    def test_container_gateway_probe_handles_gaierror(self) -> None:
        from holon_coherence.cli import _CONTAINER_GATEWAY_PROBE

        wrapper = (
            "import sys, unittest.mock as mock\n"
            "with mock.patch('socket.getaddrinfo', side_effect=OSError('mock DNS fail')):\n"
            f"    exec({_CONTAINER_GATEWAY_PROBE!r})\n"
        )
        res = subprocess.run([sys.executable, "-c", wrapper, "8081"], capture_output=True, text=True)
        assert res.returncode == 3
        assert "gateway name does not resolve" in res.stderr

    def test_container_gateway_probe_iterates_and_connects(self) -> None:
        from holon_coherence.cli import _CONTAINER_GATEWAY_PROBE

        wrapper = (
            "import sys, unittest.mock as mock, socket\n"
            "mock_infos = [\n"
            "    (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('192.168.65.1', 0)),\n"
            "    (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('192.168.65.2', 0)),\n"
            "]\n"
            "calls = []\n"
            "def mock_conn(addr, timeout=3):\n"
            "    assert timeout == 3\n"
            "    calls.append(addr)\n"
            "    if addr[0] == '192.168.65.1':\n"
            "        raise OSError('Connection refused')\n"
            "    return mock.MagicMock()\n"
            "with (\n"
            "    mock.patch('socket.getaddrinfo', return_value=mock_infos),\n"
            "    mock.patch('socket.create_connection', side_effect=mock_conn),\n"
            "):\n"
            f"    exec({_CONTAINER_GATEWAY_PROBE!r})\n"
        )
        res = subprocess.run([sys.executable, "-c", wrapper, "8081"], capture_output=True, text=True)
        assert res.returncode == 0


class TestPlanAndReportLocalLlmRoute:
    """Unit tests for plan_local_llm_route and report_local_llm_route."""

    @pytest.fixture(autouse=True)
    def _mock_host_addrs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("holon_coherence.commands.start.detect_host_addresses", lambda: ("192.168.2.13",))

    def test_plan_local_llm_route_valid_and_invalid(self) -> None:
        route = plan_local_llm_route("localhost:8081")
        assert route is not None
        assert route.target.canonical == "localhost:8081"
        assert route.target.port == 8081
        assert "localhost:8081" in route.container_env_value

        route_portless = plan_local_llm_route("localhost")
        assert route_portless is not None
        assert route_portless.target.canonical == "localhost"
        assert route_portless.target.port is None

        assert plan_local_llm_route("localhost:") is None
        assert plan_local_llm_route("localhost:notaport") is None
        assert plan_local_llm_route("://x") is None

    def test_report_local_llm_route_reachable_with_pruning(self, capsys: pytest.CaptureFixture[str]) -> None:
        route = plan_local_llm_route("localhost:8081")
        assert route is not None
        dropped = report_local_llm_route(route, reachable=True, detail="ok")
        assert len(dropped) > 0
        captured = capsys.readouterr()
        assert "Removing" in captured.out
        assert "is intercepted" in captured.out

    def test_report_local_llm_route_unreachable_with_pruning(self, capsys: pytest.CaptureFixture[str]) -> None:
        route = plan_local_llm_route("localhost:8081")
        assert route is not None
        dropped = report_local_llm_route(route, reachable=False, detail="connection refused")
        assert dropped == ()
        captured = capsys.readouterr()
        assert "Container cannot reach localhost:8081" in captured.err
        assert "Keeping NO_PROXY as-is" in captured.err
        assert "retained" in captured.err

    def test_report_local_llm_route_unreachable_without_pruning(self, capsys: pytest.CaptureFixture[str]) -> None:
        # 192.168.2.13:8081 is not in default NO_PROXY, so plan.remove is empty
        route = plan_local_llm_route("192.168.2.13:8081")
        assert route is not None
        dropped = report_local_llm_route(route, reachable=False, detail="gateway name does not resolve")
        assert dropped == ()
        captured = capsys.readouterr()
        assert "Container cannot reach 192.168.2.13:8081" in captured.err
        assert "retained" not in captured.err
        assert "already intercepted" not in captured.out

    def test_report_local_llm_route_reachable_without_pruning(self, capsys: pytest.CaptureFixture[str]) -> None:
        route = plan_local_llm_route("192.168.2.13:8081")
        assert route is not None
        dropped = report_local_llm_route(route, reachable=True, detail="ok")
        assert dropped == ()
        captured = capsys.readouterr()
        assert "already intercepted" in captured.out

    def test_report_local_llm_route_wildcard_blocked(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("NO_PROXY", "*")
        route = plan_local_llm_route("localhost:8081")
        assert route is not None
        dropped = report_local_llm_route(route, reachable=True, detail="ok")
        assert dropped == ()
        captured = capsys.readouterr()
        assert "NO_PROXY contains '*'" in captured.err


def _free_ports(port: int, host: str = "127.0.0.1") -> bool:
    return False


class TestMitmwebInspectorDefault:
    """The mitmweb inspector is opt-in (``--web`` or ``HOLON_COHERENCE_WEB``); a plain ``start`` stays headless.

    mitmweb keeps every flow in memory with no retention cap, so a long-running default proxy must not run it.
    """

    @staticmethod
    def _host_start(
        argv: list[str],
        in_use: Any = _free_ports,
        token: str = "tok123",
    ) -> tuple[list[str], MagicMock, MagicMock]:
        with (
            patch("holon_coherence.commands.start.is_in_container", return_value=False),
            patch("holon_coherence.commands.start.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.commands.start.is_port_in_use", side_effect=in_use),
            patch("holon_coherence.commands.start.resolve_web_password", return_value=token) as mock_resolve,
            patch("holon_coherence.commands.start.save_web_token") as mock_save,
            patch("holon_coherence.commands.start.ensure_docker_image"),
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch("subprocess.run") as mock_run,
        ):
            main(argv)
        return mock_run.call_args_list[-1][0][0], mock_resolve, mock_save

    @staticmethod
    def _in_container_start(argv: list[str], monkeypatch: pytest.MonkeyPatch) -> list[str]:
        launched: list[list[str]] = []

        def fake_run(cmd: list[str], *args: Any, **kwargs: Any) -> MagicMock:
            launched.append(list(cmd))
            return MagicMock(returncode=0)

        monkeypatch.setattr("holon_coherence.commands.start.is_in_container", lambda: True)
        with (
            patch("holon_coherence.commands.start.resolve_web_password", return_value="tok123"),
            patch("subprocess.run", side_effect=fake_run),
        ):
            main(argv)
        assert len(launched) == 1, "no Docker command may run inside the container"
        return launched[0]

    def test_start_web_selects_mitmweb_and_passes_token(self) -> None:
        docker_cmd, mock_resolve, mock_save = self._host_start(["start", "-d", "--web"])

        assert "127.0.0.1:8081:8081" in docker_cmd
        assert "HOLON_COHERENCE_WEB_PASSWORD=tok123" in docker_cmd
        tail = docker_cmd[docker_cmd.index("holon-coherence:latest") :]
        assert tail == ["holon-coherence:latest", "start", "--port", "8080", "--web", "--web-port", "8081"]
        mock_resolve.assert_called_once_with(None)
        mock_save.assert_called_once_with("tok123")

    def test_start_web_binds_inspector_to_loopback_only(self) -> None:
        docker_cmd, _resolve, _save = self._host_start(["start", "-d", "--web"])
        mappings = [docker_cmd[i + 1] for i, arg in enumerate(docker_cmd) if arg == "-p"]
        assert mappings and all(mapping.startswith("127.0.0.1:") for mapping in mappings)

    @pytest.mark.parametrize("argv", [["start", "-d"], ["start", "-d", "--no-web"]])
    def test_start_default_and_no_web_select_mitmdump(self, argv: list[str]) -> None:
        docker_cmd, mock_resolve, mock_save = self._host_start(argv)

        assert not any(arg.endswith(":8081") for arg in docker_cmd)
        assert not any(arg.startswith("HOLON_COHERENCE_WEB_PASSWORD=") for arg in docker_cmd)
        tail = docker_cmd[docker_cmd.index("holon-coherence:latest") :]
        assert tail == ["holon-coherence:latest", "start", "--port", "8080"]
        mock_resolve.assert_not_called()
        mock_save.assert_not_called()

    @pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
    def test_start_env_opt_in_selects_mitmweb(self, value: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_COHERENCE_WEB", value)
        docker_cmd, _resolve, mock_save = self._host_start(["start", "-d"])
        assert "127.0.0.1:8081:8081" in docker_cmd
        assert docker_cmd[-3:] == ["--web", "--web-port", "8081"]
        mock_save.assert_called_once_with("tok123")

    @pytest.mark.parametrize("value", ["", "0", "false", "off"])
    def test_start_env_falsy_stays_headless(self, value: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_COHERENCE_WEB", value)
        docker_cmd, _resolve, _save = self._host_start(["start", "-d"])
        assert "--web" not in docker_cmd

    def test_start_no_web_overrides_env_opt_in(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_COHERENCE_WEB", "1")
        docker_cmd, mock_resolve, _save = self._host_start(["start", "-d", "--no-web"])
        assert "--web" not in docker_cmd
        mock_resolve.assert_not_called()

    @pytest.mark.parametrize("env_value", [None, "0"])
    def test_start_web_password_alone_implies_inspector(
        self, env_value: str | None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        if env_value is not None:
            monkeypatch.setenv("HOLON_COHERENCE_WEB", env_value)
        docker_cmd, mock_resolve, mock_save = self._host_start(["start", "-d", "--web-password", "pw-secret"])

        assert "127.0.0.1:8081:8081" in docker_cmd
        assert docker_cmd[-3:] == ["--web", "--web-port", "8081"]
        mock_resolve.assert_called_once_with("pw-secret")
        mock_save.assert_called_once_with("tok123")
        assert "pw-secret" not in capsys.readouterr().err

    def test_start_no_web_with_web_password_warns_without_leaking(self, capsys: pytest.CaptureFixture[str]) -> None:
        docker_cmd, mock_resolve, mock_save = self._host_start(
            ["start", "-d", "--no-web", "--web-password", "pw-secret"]
        )

        assert "--web" not in docker_cmd
        assert not any(arg.startswith("HOLON_COHERENCE_WEB_PASSWORD=") for arg in docker_cmd)
        mock_resolve.assert_not_called()
        mock_save.assert_not_called()
        captured = capsys.readouterr()
        assert "--web-password is ignored because --no-web disables the mitmweb inspector" in captured.err
        assert "pw-secret" not in captured.out + captured.err

    def test_in_container_web_password_alone_runs_mitmweb(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cmd = self._in_container_start(["start", "--port", "8080", "--web-password", "pw-secret"], monkeypatch)
        assert cmd[0].endswith("mitmweb")

    def test_web_password_env_var_does_not_imply_inspector(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_COHERENCE_WEB_PASSWORD", "env-secret")
        docker_cmd, mock_resolve, _save = self._host_start(["start", "-d"])
        assert "--web" not in docker_cmd
        mock_resolve.assert_not_called()

    def test_start_web_inspector_port_falls_back(self, capsys: pytest.CaptureFixture[str]) -> None:
        docker_cmd, _resolve, _save = self._host_start(
            ["start", "-d", "--web"], in_use=lambda port, host="127.0.0.1": port == 8081
        )

        assert "127.0.0.1:8082:8081" in docker_cmd
        assert "127.0.0.1:8080:8080" in docker_cmd
        out = capsys.readouterr().out
        assert "Mapping mitmweb inspector to host port 8082 instead." in out
        assert "http://127.0.0.1:8082/?token=tok123" in out

    def test_start_custom_inspector_port_falls_back(self) -> None:
        docker_cmd, _resolve, _save = self._host_start(
            ["start", "-d", "--web", "--web-port", "9090"], in_use=lambda port, host="127.0.0.1": port == 9090
        )
        assert "127.0.0.1:9091:8081" in docker_cmd

    def test_start_inspector_fallback_skips_local_llm_port(self) -> None:
        docker_cmd, _resolve, _save = self._host_start(
            ["start", "-d", "--web", "--local-llm-base", "localhost:8082"],
            in_use=lambda port, host="127.0.0.1": port == 8081,
        )
        assert "127.0.0.1:8083:8081" in docker_cmd
        assert not any(arg == "127.0.0.1:8082:8081" for arg in docker_cmd)

    def test_start_inspector_never_lands_on_the_requested_local_llm_port(self) -> None:
        docker_cmd, _resolve, _save = self._host_start(["start", "-d", "--web", "--local-llm-base", "localhost:8081"])
        assert "127.0.0.1:8082:8081" in docker_cmd

    def test_start_prints_all_endpoints(self, capsys: pytest.CaptureFixture[str]) -> None:
        self._host_start(["start", "-d", "--web"])
        out = capsys.readouterr().out
        assert "Proxy Listen Address         : 127.0.0.1:8080" in out
        assert "Coherence Live Dashboard     : http://127.0.0.1:8080/holon/" in out
        assert "mitmweb Req/Resp Inspector   : http://127.0.0.1:8081/?token=tok123" in out
        assert "Web API Key" not in out

    @pytest.mark.parametrize("argv", [["start", "-d"], ["start", "-d", "--no-web"]])
    def test_start_headless_reports_inspector_not_running(
        self, argv: list[str], capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._host_start(argv)
        out = capsys.readouterr().out
        assert "Proxy Listen Address         : 127.0.0.1:8080" in out
        assert "mitmweb Req/Resp Inspector   : not running (headless; enable with --web or HOLON_COHERENCE_WEB=1)" in (
            out
        )
        assert "?token=" not in out

    def test_in_container_web_runs_mitmweb_with_password_without_printing_it(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cmd = self._in_container_start(["start", "--port", "8080", "--web", "--web-port", "8081"], monkeypatch)

        assert cmd[0].endswith("mitmweb")
        assert cmd[cmd.index("--web-host") + 1] == "0.0.0.0"
        assert cmd[cmd.index("--web-port") + 1] == "8081"
        set_values = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "--set"]
        assert "web_password=tok123" in set_values
        assert "web_open_browser=false" in set_values
        # In-container stdout is kept by `docker logs`; the raw token must never reach it.
        out = capsys.readouterr().out
        assert "tok123" not in out
        assert "mitmweb inspector listening on container port 8081" in out
        # A manual `docker run ... start --web` has no host-side token; the message names the recovery path.
        assert "docker exec <container> sh -c 'cat \"$HOME/.holon/web-token\"'" in out

    def test_in_container_no_web_runs_mitmdump(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cmd = self._in_container_start(["start", "--port", "8080", "--no-web"], monkeypatch)
        assert cmd[0].endswith("mitmdump")
        assert not any("web_password" in arg for arg in cmd)

    def test_in_container_default_stays_headless(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The Dockerfile CMD and run/run-agent containers publish no inspector port."""
        cmd = self._in_container_start(["start", "--port", "8080"], monkeypatch)
        assert cmd[0].endswith("mitmdump")
        assert "--web-port" not in cmd

    def test_in_container_ignores_env_opt_in(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The env opt-in is a host preference; only an explicit --web turns on an in-container mitmweb."""
        monkeypatch.setenv("HOLON_COHERENCE_WEB", "1")
        cmd = self._in_container_start(["start", "--port", "8080"], monkeypatch)
        assert cmd[0].endswith("mitmdump")

    def test_ensure_proxy_running_stays_headless(self) -> None:
        with (
            patch("holon_coherence.commands.start.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.commands.start.is_port_in_use", return_value=False),
            patch("holon_coherence.commands.start.is_container_running", return_value=False),
            patch("holon_coherence.commands.start.resolve_web_password") as mock_resolve,
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run,
            patch("holon_coherence.commands.start.wait_for_proxy_ready", return_value=True),
        ):
            assert ensure_proxy_running(port=8080) is True
        docker_cmd = mock_run.call_args_list[-1][0][0]
        assert "--web" not in docker_cmd
        assert not any(arg.endswith(":8081") for arg in docker_cmd)
        assert not any(arg.startswith("HOLON_COHERENCE_WEB_PASSWORD=") for arg in docker_cmd)
        mock_resolve.assert_not_called()
