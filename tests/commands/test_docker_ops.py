"""Unit tests for Docker container lifecycle management and CLI operations."""

from __future__ import annotations

import argparse
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from holon_coherence.commands.docker_ops import (
    DOCKER_BUILD_TIMEOUT_SECONDS,
    check_docker_daemon,
    ensure_docker_image,
    get_container_mapped_port,
    get_container_web_token,
    handle,
    is_container_bound_to_port,
    is_container_running,
    register,
    stop_proxy_container,
)


class TestDockerDiagnostics:
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
            patch("subprocess.run", side_effect=timeout_err),
        ):
            ok, err = check_docker_daemon()
            assert ok is False
            assert "timed out" in err


class TestContainerStatusAndPortBinding:
    """Tests for checking container running state and port mapping."""

    def test_is_container_running(self) -> None:
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="true\n")):
            assert is_container_running("test-box") is True

        with patch("subprocess.run", return_value=MagicMock(returncode=1, stdout="")):
            assert is_container_running("test-box") is False

    def test_is_container_bound_to_port_direct_match(self) -> None:
        mock_res = MagicMock(returncode=0, stdout="127.0.0.1:8080\n")
        with patch("subprocess.run", return_value=mock_res):
            assert is_container_bound_to_port(8080) is True
            assert is_container_bound_to_port(9090) is False

    def test_is_container_bound_to_port_fallback(self) -> None:
        failed_res = MagicMock(returncode=1, stdout="")
        fallback_res = MagicMock(returncode=0, stdout="8080/tcp -> 127.0.0.1:8080\n")
        with patch("subprocess.run", side_effect=[failed_res, fallback_res]):
            assert is_container_bound_to_port(8080) is True

    def test_get_container_mapped_port(self) -> None:
        mock_res = MagicMock(returncode=0, stdout="127.0.0.1:8080\n")
        with patch("subprocess.run", return_value=mock_res):
            assert get_container_mapped_port("test-box", 8080) == 8080

        with patch("subprocess.run", return_value=MagicMock(returncode=1, stdout="")):
            assert get_container_mapped_port("test-box", 8080) is None

    def test_get_container_web_token_reads_container_env(self) -> None:
        env = '["PATH=/usr/bin","HOLON_COHERENCE_WEB_PASSWORD=tok-from-env","OTHER=x"]\n'
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout=env)) as mock_run:
            assert get_container_web_token("a") == "tok-from-env"
        assert mock_run.call_args[0][0] == ["docker", "inspect", "-f", "{{json .Config.Env}}", "a"]
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout='["PATH=/usr/bin"]')):
            assert get_container_web_token("a") is None
        with patch("subprocess.run", return_value=MagicMock(returncode=1, stdout="")):
            assert get_container_web_token("a") is None


class TestEnsureDockerImageOps:
    """Tests for unified ensure_docker_image helper."""

    def test_image_already_exists(self) -> None:
        with patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            ensure_docker_image("holon-coherence:latest", rebuild=False)
            mock_run.assert_called_once_with(
                ["docker", "image", "inspect", "holon-coherence:latest"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def test_image_builds_when_rebuild_true(self) -> None:
        with (
            patch("os.path.exists", return_value=True),
            patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run,
        ):
            ensure_docker_image("holon-coherence:latest", rebuild=True)
            mock_run.assert_called_once()
            cmd = mock_run.call_args[0][0]
            assert cmd[:4] == ["docker", "build", "-t", "holon-coherence:latest"]


class TestStopProxyContainerOps:
    """Tests for stopping and removing Docker containers."""

    def test_stop_container_success(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            stop_proxy_container("custom-box")
            mock_run.assert_called_once_with(["docker", "rm", "-f", "custom-box"], capture_output=True, text=True)
            assert "custom-box container stopped and removed" in capsys.readouterr().out


class TestDockerOpsRegistrationAndDispatch:
    """Tests for subparsers registration and handle dispatch across build, stop, status, logs."""

    def test_register_and_defaults(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        parsers = register(subparsers)
        assert len(parsers) == 4

        args_build = parser.parse_args(["build", "--tag", "custom:1.0"])
        assert args_build.command == "build"
        assert args_build.tag == "custom:1.0"
        assert args_build.handler == handle

        args_stop = parser.parse_args(["stop", "--name", "my-box"])
        assert args_stop.command == "stop"
        assert args_stop.name == "my-box"

        args_status = parser.parse_args(["status", "--name", "my-box"])
        assert args_status.command == "status"
        assert args_status.name == "my-box"

        args_logs = parser.parse_args(["logs", "-f", "--name", "my-box"])
        assert args_logs.command == "logs"
        assert args_logs.follow is True
        assert args_logs.name == "my-box"

    def test_handle_dispatch(self) -> None:
        with patch("holon_coherence.commands.docker_ops.handle_build", return_value=0) as mock_b:
            assert handle(argparse.Namespace(command="build")) == 0
            mock_b.assert_called_once()

        with patch("holon_coherence.commands.docker_ops.handle_stop", return_value=0) as mock_s:
            assert handle(argparse.Namespace(command="stop")) == 0
            mock_s.assert_called_once()

        with patch("holon_coherence.commands.docker_ops.handle_status", return_value=0) as mock_st:
            assert handle(argparse.Namespace(command="status")) == 0
            mock_st.assert_called_once()

        with patch("holon_coherence.commands.docker_ops.handle_logs", return_value=0) as mock_l:
            assert handle(argparse.Namespace(command="logs")) == 0
            mock_l.assert_called_once()


class TestEnsureDockerImage:
    """Tests for unified ensure_docker_image helper."""

    def test_image_already_exists(self) -> None:
        with patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            ensure_docker_image("holon-coherence:latest", rebuild=False)
            mock_run.assert_called_once_with(
                ["docker", "image", "inspect", "holon-coherence:latest"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def test_image_builds_when_rebuild_true(self) -> None:
        with (
            patch("os.path.exists", return_value=True),
            patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run,
        ):
            ensure_docker_image("holon-coherence:latest", rebuild=True)
            mock_run.assert_called_once()
            cmd = mock_run.call_args[0][0]
            assert cmd[:4] == ["docker", "build", "-t", "holon-coherence:latest"]

    def test_image_pulls_and_ghcr_fallback(self) -> None:
        with (
            patch(
                "subprocess.run",
                side_effect=[
                    MagicMock(returncode=1),  # inspect fails
                    MagicMock(returncode=1),  # docker pull image fails
                    MagicMock(returncode=0),  # docker pull ghcr succeeds
                    MagicMock(returncode=0),  # docker tag succeeds
                ],
            ) as mock_run,
            patch("os.path.exists", side_effect=lambda p: not str(p).endswith("Dockerfile")),
        ):
            ensure_docker_image("holon-coherence:latest", rebuild=False)
            assert mock_run.call_count == 4
            pull_call = mock_run.call_args_list[1]
            assert pull_call[0][0] == ["docker", "pull", "holon-coherence:latest"]
            assert pull_call[1].get("stdout") == subprocess.DEVNULL
            assert pull_call[1].get("stderr") == subprocess.DEVNULL

    def test_image_pull_slash_not_prefixed_to_ghcr(self) -> None:
        with (
            patch(
                "subprocess.run",
                side_effect=[
                    MagicMock(returncode=1),  # inspect fails
                    MagicMock(returncode=1),  # docker pull image fails
                ],
            ) as mock_run,
            patch("os.path.exists", side_effect=lambda p: not str(p).endswith("Dockerfile")),
            pytest.raises(SystemExit) as exc_info,
        ):
            ensure_docker_image("custom-org/custom-img:latest", rebuild=False)
        assert exc_info.value.code == 1
        assert mock_run.call_count == 2

    def test_docker_build_timeout_exits(self, capsys: pytest.CaptureFixture[str]) -> None:
        """ensure_docker_image exits 1 when docker build times out."""
        with (
            patch("os.path.exists", return_value=True),
            patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["docker", "build"], timeout=DOCKER_BUILD_TIMEOUT_SECONDS),
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            ensure_docker_image("holon-coherence:latest", rebuild=True)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert f"timed out after {DOCKER_BUILD_TIMEOUT_SECONDS}s" in captured.err

    def test_docker_pull_timeout_exits(self, capsys: pytest.CaptureFixture[str]) -> None:
        """ensure_docker_image exits 1 when docker pull times out."""
        with (
            patch("os.path.exists", side_effect=lambda p: not str(p).endswith("Dockerfile")),
            patch(
                "subprocess.run",
                side_effect=[
                    MagicMock(returncode=1),  # inspect fails
                    subprocess.TimeoutExpired(cmd=["docker", "pull"], timeout=DOCKER_BUILD_TIMEOUT_SECONDS),
                ],
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            ensure_docker_image("holon-coherence:latest", rebuild=False)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "timed out" in captured.err

    def test_docker_ghcr_pull_timeout_exits(self, capsys: pytest.CaptureFixture[str]) -> None:
        """ensure_docker_image exits 1 when GHCR pull fallback times out."""
        with (
            patch("os.path.exists", side_effect=lambda p: not str(p).endswith("Dockerfile")),
            patch(
                "subprocess.run",
                side_effect=[
                    MagicMock(returncode=1),  # inspect fails
                    MagicMock(returncode=1),  # docker pull primary fails
                    subprocess.TimeoutExpired(cmd=["docker", "pull"], timeout=DOCKER_BUILD_TIMEOUT_SECONDS),
                ],
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            ensure_docker_image("holon-coherence:latest", rebuild=False)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "timed out" in captured.err

    def test_docker_tag_timeout_exits(self, capsys: pytest.CaptureFixture[str]) -> None:
        """ensure_docker_image exits 1 when docker tag times out after successful GHCR pull."""
        with (
            patch("os.path.exists", side_effect=lambda p: not str(p).endswith("Dockerfile")),
            patch(
                "subprocess.run",
                side_effect=[
                    MagicMock(returncode=1),  # inspect fails
                    MagicMock(returncode=1),  # docker pull primary fails
                    MagicMock(returncode=0),  # docker pull ghcr succeeds
                    subprocess.TimeoutExpired(cmd=["docker", "tag"], timeout=30),
                ],
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            ensure_docker_image("holon-coherence:latest", rebuild=False)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "timed out" in captured.err
