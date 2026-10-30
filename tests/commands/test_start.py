"""Unit tests for start command, container orchestration, route planning, and readiness checks."""

from __future__ import annotations

import argparse
import email.message
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from holon_coherence.commands.start import (
    DEFAULT_PROXY_PORT,
    DEFAULT_WEB_PORT,
    PROXY_READY_TIMEOUT_SECONDS,
    docker_host_alias_args,
    ensure_proxy_running,
    handle,
    handle_start,
    host_local_container_args,
    host_local_covered,
    is_port_in_use,
    plan_local_llm_route,
    probe_host_local_reachable,
    register,
    report_local_llm_route,
    wait_for_proxy_ready,
)


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
        start_parser = register(subparsers)

        args = parser.parse_args(["start", "-d", "--port", "8888"])
        assert args.command == "start"
        assert args.detach is True
        assert args.port == 8888
        assert getattr(args, "handler") == handle

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
