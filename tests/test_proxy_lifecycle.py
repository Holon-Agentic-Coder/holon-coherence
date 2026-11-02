"""Comprehensive unit test suite for ProxyLifecycle domain class."""

from __future__ import annotations

import os
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from holon_coherence.proxy.lifecycle import (
    ProxyLifecycle,
    ProxyLifecycleConfig,
    ProxyLifecycleHooks,
)


class TestProxyLifecycleCA:
    """Tests for CA generation and directory permission management."""

    def test_ensure_ca_creates_directories_with_permissions(self, tmp_path: pytest.TempPathFactory) -> None:
        ca_dir = str(tmp_path / "ca")
        cache_dir = str(tmp_path / "cache")
        logs_dir = str(tmp_path / "logs")

        config = ProxyLifecycleConfig(ca_dir=ca_dir, cache_dir=cache_dir, logs_dir=logs_dir)
        mock_gen_ca = MagicMock()
        hooks = ProxyLifecycleHooks(generate_ca_fn=mock_gen_ca)
        lifecycle = ProxyLifecycle(config, hooks=hooks)

        os.makedirs(ca_dir, exist_ok=True)
        cert_path = os.path.join(ca_dir, "mitmproxy-ca-cert.pem")
        pem_path = os.path.join(ca_dir, "mitmproxy-ca.pem")
        with open(cert_path, "w") as f:
            f.write("DUMMY CERT")
        with open(pem_path, "w") as f:
            f.write("DUMMY KEY")

        res_cert, res_pem = lifecycle.ensure_ca()
        assert res_cert == cert_path
        assert res_pem == pem_path
        assert os.path.isdir(ca_dir)
        assert os.path.isdir(cache_dir)
        assert os.path.isdir(logs_dir)
        mock_gen_ca.assert_not_called()

    def test_ensure_ca_generates_when_missing(self, tmp_path: pytest.TempPathFactory) -> None:
        ca_dir = str(tmp_path / "ca")
        cache_dir = str(tmp_path / "cache")
        logs_dir = str(tmp_path / "logs")

        config = ProxyLifecycleConfig(ca_dir=ca_dir, cache_dir=cache_dir, logs_dir=logs_dir)
        mock_gen_ca = MagicMock()
        hooks = ProxyLifecycleHooks(generate_ca_fn=mock_gen_ca)
        lifecycle = ProxyLifecycle(config, hooks=hooks)

        cert_path, pem_path = lifecycle.ensure_ca()
        assert cert_path == os.path.join(ca_dir, "mitmproxy-ca-cert.pem")
        assert pem_path == os.path.join(ca_dir, "mitmproxy-ca.pem")
        mock_gen_ca.assert_called_once_with(output_dir=ca_dir)


class TestProxyLifecycleWaitUntilReady:
    """Tests for readiness polling across HTTP status responses and timeouts."""

    def test_immediate_healthy_response(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status = 200
        hooks = ProxyLifecycleHooks(
            is_container_running_fn=lambda name: True,
            urlopen_no_proxy_fn=lambda req, timeout: mock_resp,
        )
        lifecycle = ProxyLifecycle(ProxyLifecycleConfig(port=8080), hooks=hooks)
        assert lifecycle.wait_until_ready(timeout_seconds=5.0) is True

    def test_fast_fail_when_container_stops(self) -> None:
        hooks = ProxyLifecycleHooks(
            is_container_running_fn=lambda name: False,
        )
        lifecycle = ProxyLifecycle(ProxyLifecycleConfig(port=8080), hooks=hooks)
        assert lifecycle.wait_until_ready(timeout_seconds=5.0) is False

    def test_retry_on_transient_error(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status = 200
        call_count = [0]

        def flaky_urlopen(req, timeout):
            call_count[0] += 1
            if call_count[0] < 2:
                raise urllib.error.URLError("Connection refused")
            return mock_resp

        hooks = ProxyLifecycleHooks(
            is_container_running_fn=lambda name: True,
            urlopen_no_proxy_fn=flaky_urlopen,
        )
        lifecycle = ProxyLifecycle(ProxyLifecycleConfig(port=8080), hooks=hooks)
        with patch("time.sleep"):
            assert lifecycle.wait_until_ready(timeout_seconds=5.0) is True
        assert call_count[0] == 2


class TestProxyLifecycleStart:
    """Tests for container and in-container start dispatch."""

    def test_in_container_mitmdump_dispatch(self) -> None:
        config = ProxyLifecycleConfig(port=8080, web_port=None)
        lifecycle = ProxyLifecycle(config)
        with (
            patch("holon_coherence.proxy.lifecycle.is_in_container", return_value=True),
            patch("subprocess.run") as mock_run,
        ):
            assert lifecycle.start() is True
            mock_run.assert_called_once()
            cmd = mock_run.call_args[0][0]
            assert "mitmdump" in cmd[0]
            assert "--listen-port" in cmd
            assert "8080" in cmd

    def test_in_container_mitmweb_dispatch(self) -> None:
        config = ProxyLifecycleConfig(port=8080, web_port=8081, web_password="test-token")
        lifecycle = ProxyLifecycle(config)
        with (
            patch("holon_coherence.proxy.lifecycle.is_in_container", return_value=True),
            patch("subprocess.run") as mock_run,
            patch("holon_coherence.commands.web_token.save_web_token"),
        ):
            assert lifecycle.start() is True
            mock_run.assert_called_once()
            cmd = mock_run.call_args[0][0]
            assert "mitmweb" in cmd[0]
            assert "--web-port" in cmd
            assert "8081" in cmd

    def test_daemon_unavailable_exits(self) -> None:
        hooks = ProxyLifecycleHooks(
            check_daemon_fn=lambda: (False, "Docker daemon not running"),
        )
        lifecycle = ProxyLifecycle(ProxyLifecycleConfig(detach=True), hooks=hooks)
        with pytest.raises(SystemExit) as exc_info:
            lifecycle.ensure_running()
        assert exc_info.value.code == 1

    def test_port_conflict_recreation(self) -> None:
        mock_stop = MagicMock()
        hooks = ProxyLifecycleHooks(
            check_daemon_fn=lambda: (True, ""),
            is_port_in_use_fn=MagicMock(side_effect=[True, False, False]),
            is_container_running_fn=lambda name: True,
            is_container_bound_to_port_fn=lambda port, name: True,
            container_host_local_spec_fn=lambda *args: "localhost:11434",
            stop_container_fn=mock_stop,
            ensure_image_fn=MagicMock(),
            wait_ready_fn=lambda *args, **kwargs: True,
        )
        config = ProxyLifecycleConfig(port=8080, host_local_spec="localhost:8081")
        lifecycle = ProxyLifecycle(config, hooks=hooks)

        with (
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run,
        ):
            started = lifecycle.ensure_running()
            assert started is False
            mock_stop.assert_called_once()
            docker_cmd = mock_run.call_args[0][0]
            assert "HOLON_HOST_LOCAL_HOSTS=localhost:11434,localhost:8081" in docker_cmd

    def test_container_launch_failure_logs_and_cleanup(self, capsys: pytest.CaptureFixture[str]) -> None:
        mock_stop = MagicMock()
        hooks = ProxyLifecycleHooks(
            check_daemon_fn=lambda: (True, ""),
            is_port_in_use_fn=lambda port: False,
            is_container_running_fn=lambda name: False,
            ensure_image_fn=MagicMock(),
            wait_ready_fn=lambda *args, **kwargs: False,
            stop_container_fn=mock_stop,
        )
        lifecycle = ProxyLifecycle(ProxyLifecycleConfig(port=8080), hooks=hooks)

        with (
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch(
                "subprocess.run",
                side_effect=[
                    MagicMock(returncode=0),  # rm -f
                    MagicMock(returncode=0),  # docker run
                    MagicMock(stdout="proxy crash log", stderr=""),  # docker logs
                ],
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            lifecycle.ensure_running()
        assert exc_info.value.code == 1
        mock_stop.assert_called_once()
        err = capsys.readouterr().err
        assert "Proxy container did not become ready" in err
        assert "proxy crash log" in err


class TestProxyLifecycleStop:
    """Tests for container teardown."""

    def test_stop_successful_removal(self, capsys: pytest.CaptureFixture[str]) -> None:
        mock_res = MagicMock(returncode=0, stderr="")
        with patch("subprocess.run", return_value=mock_res) as mock_run:
            lifecycle = ProxyLifecycle()
            res = lifecycle.stop("test-proxy")
            assert res is True
            mock_run.assert_called_once_with(["docker", "rm", "-f", "test-proxy"], capture_output=True, text=True)
            assert "test-proxy container stopped and removed" in capsys.readouterr().out

    def test_stop_no_active_container(self, capsys: pytest.CaptureFixture[str]) -> None:
        mock_res = MagicMock(returncode=1, stderr="Error: No such container: test-proxy")
        with patch("subprocess.run", return_value=mock_res):
            lifecycle = ProxyLifecycle()
            res = lifecycle.stop("test-proxy")
            assert res is True
            assert "No active test-proxy container found" in capsys.readouterr().out

    def test_stop_oserror_handling(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("subprocess.run", side_effect=OSError("docker binary missing")):
            lifecycle = ProxyLifecycle()
            res = lifecycle.stop("test-proxy")
            assert res is False
            assert "Failed to remove container: docker binary missing" in capsys.readouterr().out
