"""Unit tests for the ProxyLifecycle domain class (CA material, readiness, start and teardown)."""

from __future__ import annotations

import ast
import os
import stat
import subprocess
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from holon_coherence.container.lifecycle import (
    CA_CERT_FILENAME,
    CA_PEM_FILENAME,
    ProxyLifecycle,
    ProxyLifecycleConfig,
)
from holon_coherence.host_local import HOST_LOCAL_ENV_VAR

LIFECYCLE = "holon_coherence.container.lifecycle"


def _config(tmp_path: Path, **overrides: object) -> ProxyLifecycleConfig:
    dirs = {
        "ca_dir": str(tmp_path / "proxy-ca"),
        "cache_dir": str(tmp_path / "cache"),
        "logs_dir": str(tmp_path / "logs"),
    }
    return ProxyLifecycleConfig(**{**dirs, **overrides})  # type: ignore[arg-type]


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


class TestProxyLifecycleCA:
    """ensure_ca(): mounted directories and root CA generation."""

    def test_creates_private_directories(self, tmp_path: Path) -> None:
        lifecycle = ProxyLifecycle(_config(tmp_path))
        with patch(f"{LIFECYCLE}.generate_root_ca"):
            lifecycle.ensure_ca()
        for name in ("proxy-ca", "cache", "logs"):
            assert (tmp_path / name).is_dir()
            assert _mode(tmp_path / name) == 0o700

    def test_shared_mounts_are_world_accessible(self, tmp_path: Path) -> None:
        lifecycle = ProxyLifecycle(_config(tmp_path, world_accessible_mounts=True))
        ca_dir = tmp_path / "proxy-ca"
        ca_dir.mkdir()
        (ca_dir / CA_CERT_FILENAME).write_text("cert")
        (ca_dir / CA_PEM_FILENAME).write_text("pem")
        lifecycle.ensure_ca()
        assert _mode(ca_dir) == 0o777
        assert _mode(tmp_path / "cache") == 0o777
        assert _mode(ca_dir / CA_PEM_FILENAME) == 0o666

    def test_skips_generation_when_ca_files_exist(self, tmp_path: Path) -> None:
        ca_dir = tmp_path / "proxy-ca"
        ca_dir.mkdir()
        (ca_dir / CA_CERT_FILENAME).write_text("cert")
        (ca_dir / CA_PEM_FILENAME).write_text("pem")
        with patch(f"{LIFECYCLE}.generate_root_ca") as mock_gen:
            cert, pem = ProxyLifecycle(_config(tmp_path)).ensure_ca()
        mock_gen.assert_not_called()
        assert cert == str(ca_dir / CA_CERT_FILENAME)
        assert pem == str(ca_dir / CA_PEM_FILENAME)

    def test_generates_ca_when_files_missing(self, tmp_path: Path) -> None:
        ca_dir = tmp_path / "proxy-ca"
        ca_dir.mkdir()
        (ca_dir / CA_CERT_FILENAME).write_text("cert")  # key half missing
        with patch(f"{LIFECYCLE}.generate_root_ca") as mock_gen:
            ProxyLifecycle(_config(tmp_path)).ensure_ca()
        mock_gen.assert_called_once_with(output_dir=str(ca_dir))

    def test_ca_dir_override(self, tmp_path: Path) -> None:
        other = tmp_path / "other-ca"
        with patch(f"{LIFECYCLE}.generate_root_ca") as mock_gen:
            cert, _pem = ProxyLifecycle(_config(tmp_path, ca_dir=str(other))).ensure_ca()
        mock_gen.assert_called_once_with(output_dir=str(other))
        assert cert == str(other / CA_CERT_FILENAME)

    def test_generation_failure_is_not_fatal(self, tmp_path: Path) -> None:
        with patch(f"{LIFECYCLE}.generate_root_ca", side_effect=RuntimeError("no openssl")):
            cert, _pem = ProxyLifecycle(_config(tmp_path)).ensure_ca()
        assert cert.endswith(CA_CERT_FILENAME)


class TestProxyLifecycleWaitUntilReady:
    """wait_until_ready(): HTTP readiness polling with container fail-fast."""

    def test_immediate_200(self) -> None:
        with (
            patch(f"{LIFECYCLE}.is_container_running", return_value=True),
            patch(f"{LIFECYCLE}._urlopen_no_proxy", return_value=MagicMock(status=200)) as mock_open,
            patch("time.sleep") as mock_sleep,
        ):
            assert ProxyLifecycle(ProxyLifecycleConfig(port=9191)).wait_until_ready() is True
        assert mock_open.call_args[0][0].full_url == "http://127.0.0.1:9191/holon/api/metrics"
        mock_sleep.assert_not_called()

    def test_fails_fast_when_container_stops(self) -> None:
        with (
            patch(f"{LIFECYCLE}.is_container_running", side_effect=[True, False]) as mock_running,
            patch(f"{LIFECYCLE}._urlopen_no_proxy", side_effect=urllib.error.URLError(ConnectionRefusedError())),
            patch("time.sleep"),
        ):
            assert ProxyLifecycle(ProxyLifecycleConfig(container_name="box")).wait_until_ready() is False
        assert mock_running.call_args_list[0][0][0] == "box"

    def test_retries_transient_errors_until_deadline(self) -> None:
        clock = [0.0]
        fake_time = MagicMock()
        fake_time.monotonic.side_effect = lambda: clock[0]
        fake_time.sleep.side_effect = lambda s: clock.__setitem__(0, clock[0] + s)
        with (
            patch(f"{LIFECYCLE}.is_container_running", return_value=True),
            patch(
                f"{LIFECYCLE}._urlopen_no_proxy", side_effect=urllib.error.URLError(ConnectionRefusedError())
            ) as mock_open,
            patch(f"{LIFECYCLE}.time", fake_time),
        ):
            assert ProxyLifecycle().wait_until_ready(timeout_seconds=1.0, poll_interval=0.25) is False
        assert mock_open.call_count == 4
        assert fake_time.sleep.call_count == 4

    def test_retry_then_success(self) -> None:
        responses = [urllib.error.URLError(ConnectionRefusedError()), MagicMock(status=200)]
        with (
            patch(f"{LIFECYCLE}.is_container_running", return_value=True),
            patch(f"{LIFECYCLE}._urlopen_no_proxy", side_effect=responses),
            patch("time.sleep") as mock_sleep,
        ):
            assert ProxyLifecycle().wait_until_ready() is True
        assert mock_sleep.call_count == 1


class TestProxyLifecycleStart:
    """start(): managed background container start, reuse and recreation."""

    def test_docker_unavailable_exits(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch(f"{LIFECYCLE}.check_docker_daemon", return_value=(False, "Error: Docker daemon is not running.")),
            pytest.raises(SystemExit) as exc_info,
        ):
            ProxyLifecycle().start()
        assert exc_info.value.code == 1
        assert "Docker daemon is not running" in capsys.readouterr().err

    def test_launches_fresh_container(self, tmp_path: Path) -> None:
        lifecycle = ProxyLifecycle(_config(tmp_path, port=9292, container_name="box", host_local_spec="localhost:8081"))
        with (
            patch(f"{LIFECYCLE}.check_docker_daemon", return_value=(True, "")),
            patch(f"{LIFECYCLE}.is_port_in_use", return_value=False),
            patch(f"{LIFECYCLE}.is_container_running", return_value=False),
            patch(f"{LIFECYCLE}.generate_root_ca"),
            patch("holon_coherence.container.lifecycle.ensure_docker_image") as mock_image,
            patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run,
            patch.object(ProxyLifecycle, "wait_until_ready", return_value=True),
        ):
            assert lifecycle.start() is True
        mock_image.assert_called_once_with("holon-coherence:latest", rebuild=False)
        assert mock_run.call_args_list[0][0][0] == ["docker", "rm", "-f", "box"]
        docker_cmd = mock_run.call_args_list[1][0][0]
        assert docker_cmd[:4] == ["docker", "run", "-d", "--init"]
        assert "127.0.0.1:9292:8080" in docker_cmd
        assert f"{tmp_path / 'proxy-ca'}:/home/mitmproxy/.mitmproxy" in docker_cmd
        assert f"{HOST_LOCAL_ENV_VAR}=localhost:8081" in docker_cmd
        assert "HOLON_PROXY_PORT=9292" in docker_cmd
        assert docker_cmd[-4:] == ["holon-coherence:latest", "start", "--port", "8080"]

    def test_reuses_healthy_bound_container(self) -> None:
        with (
            patch(f"{LIFECYCLE}.check_docker_daemon", return_value=(True, "")),
            patch(f"{LIFECYCLE}.is_port_in_use", return_value=True),
            patch(f"{LIFECYCLE}.is_container_running", return_value=True),
            patch(f"{LIFECYCLE}.is_container_bound_to_port", return_value=True),
            patch("subprocess.run") as mock_run,
        ):
            assert ProxyLifecycle().start() is False
        mock_run.assert_not_called()

    def test_port_held_by_foreign_process_exits(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch(f"{LIFECYCLE}.check_docker_daemon", return_value=(True, "")),
            patch(f"{LIFECYCLE}.is_port_in_use", return_value=True),
            patch(f"{LIFECYCLE}.is_container_running", return_value=False),
            pytest.raises(SystemExit) as exc_info,
        ):
            ProxyLifecycle(ProxyLifecycleConfig(port=9393)).start()
        assert exc_info.value.code == 1
        assert "Port 9393 is already in use by another process" in capsys.readouterr().err

    def test_named_container_on_other_port_names_it(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch(f"{LIFECYCLE}.check_docker_daemon", return_value=(True, "")),
            patch(f"{LIFECYCLE}.is_port_in_use", return_value=False),
            patch(f"{LIFECYCLE}.is_container_running", return_value=True),
            patch(f"{LIFECYCLE}.is_container_bound_to_port", return_value=False),
            pytest.raises(SystemExit),
        ):
            ProxyLifecycle(ProxyLifecycleConfig(port=9494, container_name="box")).start()
        assert "proxy container 'box' is already running on a different port" in capsys.readouterr().err

    def test_recreates_container_missing_host_local_target(self, tmp_path: Path) -> None:
        lifecycle = ProxyLifecycle(_config(tmp_path, host_local_spec="localhost:8081"))
        with (
            patch(f"{LIFECYCLE}.check_docker_daemon", return_value=(True, "")),
            patch(f"{LIFECYCLE}.is_port_in_use", side_effect=[True, False, False]),
            patch(f"{LIFECYCLE}.is_container_running", return_value=True),
            patch(f"{LIFECYCLE}.is_container_bound_to_port", return_value=True),
            patch(f"{LIFECYCLE}.container_host_local_spec", return_value="localhost:11434"),
            patch(f"{LIFECYCLE}.generate_root_ca"),
            patch("holon_coherence.container.lifecycle.ensure_docker_image"),
            patch.object(ProxyLifecycle, "stop") as mock_stop,
            patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run,
            patch.object(ProxyLifecycle, "wait_until_ready", return_value=True),
        ):
            assert lifecycle.start() is False
        mock_stop.assert_called_once_with("holon-coherence-proxy")
        assert f"{HOST_LOCAL_ENV_VAR}=localhost:11434,localhost:8081" in mock_run.call_args_list[-1][0][0]
        assert lifecycle.config.host_local_spec == "localhost:11434,localhost:8081"

    def test_mismatch_reused_when_recreation_disabled(self) -> None:
        with (
            patch(f"{LIFECYCLE}.check_docker_daemon", return_value=(True, "")),
            patch(f"{LIFECYCLE}.is_port_in_use", return_value=True),
            patch(f"{LIFECYCLE}.is_container_running", return_value=True),
            patch(f"{LIFECYCLE}.is_container_bound_to_port", return_value=True),
            patch(f"{LIFECYCLE}.container_host_local_spec", return_value="localhost:11434"),
            patch.object(ProxyLifecycle, "stop") as mock_stop,
        ):
            lifecycle = ProxyLifecycle(ProxyLifecycleConfig(host_local_spec="localhost:8081"))
            assert lifecycle.start(recreate_if_mismatch=False) is False
        mock_stop.assert_not_called()

    def test_docker_run_failure_exits_with_its_code(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch(f"{LIFECYCLE}.check_docker_daemon", return_value=(True, "")),
            patch(f"{LIFECYCLE}.is_port_in_use", return_value=False),
            patch(f"{LIFECYCLE}.is_container_running", return_value=False),
            patch(f"{LIFECYCLE}.generate_root_ca"),
            patch("holon_coherence.container.lifecycle.ensure_docker_image"),
            patch("subprocess.run", side_effect=[MagicMock(returncode=0), MagicMock(returncode=125, stderr="boom\n")]),
            pytest.raises(SystemExit) as exc_info,
        ):
            ProxyLifecycle(_config(tmp_path)).start()
        assert exc_info.value.code == 125
        assert "Error starting proxy container: boom" in capsys.readouterr().err

    def test_unready_container_dumps_logs_and_is_removed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        logs = MagicMock(returncode=0, stdout="addon loaded\n", stderr="Traceback: bind failed\n")
        with (
            patch(f"{LIFECYCLE}.check_docker_daemon", return_value=(True, "")),
            patch(f"{LIFECYCLE}.is_port_in_use", return_value=False),
            patch(f"{LIFECYCLE}.is_container_running", return_value=False),
            patch(f"{LIFECYCLE}.generate_root_ca"),
            patch("holon_coherence.container.lifecycle.ensure_docker_image"),
            patch("subprocess.run", side_effect=[MagicMock(returncode=0), MagicMock(returncode=0), logs]),
            patch.object(ProxyLifecycle, "wait_until_ready", return_value=False),
            patch.object(ProxyLifecycle, "stop") as mock_stop,
            pytest.raises(SystemExit) as exc_info,
        ):
            ProxyLifecycle(_config(tmp_path, container_name="box")).start()
        assert exc_info.value.code == 1
        mock_stop.assert_called_once_with("box")
        err = capsys.readouterr().err
        assert "did not become ready" in err
        assert "addon loaded" in err
        assert "Traceback: bind failed" in err


class TestProxyLifecycleLaunchAndServe:
    """launch() for `holon-coherence start` and serve_in_container() inside the image."""

    def test_launch_attached_with_inspector(self, tmp_path: Path) -> None:
        config = _config(tmp_path, port=8080, web_port=8090, web_password="tok", detach=False, passive=True)
        with patch("subprocess.run") as mock_run:
            ProxyLifecycle(config).launch()
        docker_cmd = mock_run.call_args[0][0]
        assert docker_cmd[:3] == ["docker", "run", "--rm"]
        assert "127.0.0.1:8090:8081" in docker_cmd
        assert "HOLON_COHERENCE_WEB_PASSWORD=tok" in docker_cmd
        assert "COHERENCE_TOKEN_REDUCTION=0" in docker_cmd
        assert "HOLON_PASSIVE_MONITORING=1" in docker_cmd
        assert docker_cmd[-3:] == ["--web", "--web-port", "8081"]

    def test_launch_detached_failure_reports_ports(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        error = subprocess.CalledProcessError(125, ["docker", "run"])
        with patch("subprocess.run", side_effect=error), pytest.raises(SystemExit) as exc_info:
            ProxyLifecycle(_config(tmp_path, port=8085)).launch()
        assert exc_info.value.code == 1
        assert "(proxy=8085, web=N/A)" in capsys.readouterr().err

    def test_launch_attached_interrupt_stops_container(self, tmp_path: Path) -> None:
        with patch("subprocess.run", side_effect=[KeyboardInterrupt(), MagicMock(returncode=0)]) as mock_run:
            ProxyLifecycle(_config(tmp_path, detach=False, container_name="box")).launch()
        assert mock_run.call_args_list[1][0][0] == ["docker", "stop", "box"]

    @pytest.mark.parametrize(("web_port", "tool"), [(None, "mitmdump"), (8081, "mitmweb")])
    def test_serve_in_container_selects_tool(
        self, web_port: int | None, tool: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv(HOST_LOCAL_ENV_VAR, raising=False)
        config = ProxyLifecycleConfig(port=8080, web_port=web_port, web_password="tok", host_local_spec="localhost:1")
        with patch("subprocess.run") as mock_run:
            ProxyLifecycle(config).serve_in_container(banner="inspector banner" if web_port else None)
        cmd = mock_run.call_args[0][0]
        assert cmd[0].endswith(tool)
        assert cmd[cmd.index("-s") + 1].endswith("mitm_addon.py")
        assert os.environ[HOST_LOCAL_ENV_VAR] == "localhost:1"
        assert ("web_password=tok" in cmd) is (web_port is not None)
        out = capsys.readouterr().out
        assert f"via {tool} on port 8080" in out
        assert "tok" not in out


class TestProxyLifecycleStop:
    """stop(): docker rm -f teardown."""

    def test_clean_removal(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            assert ProxyLifecycle(ProxyLifecycleConfig(container_name="box")).stop() is True
        mock_run.assert_called_once_with(["docker", "rm", "-f", "box"], capture_output=True, text=True)
        assert "box container stopped and removed" in capsys.readouterr().out

    def test_missing_container_is_success(self, capsys: pytest.CaptureFixture[str]) -> None:
        res = MagicMock(returncode=1, stderr="Error: No such container: holon-coherence-proxy")
        with patch("subprocess.run", return_value=res):
            assert ProxyLifecycle().stop() is True
        assert "No active holon-coherence container found" in capsys.readouterr().out

    def test_docker_error_is_reported(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("subprocess.run", return_value=MagicMock(returncode=1, stderr="permission denied\n")):
            assert ProxyLifecycle().stop("other") is False
        assert "Failed to remove container: permission denied" in capsys.readouterr().out

    def test_missing_docker_binary(self) -> None:
        with patch("subprocess.run", side_effect=OSError("docker not found")):
            assert ProxyLifecycle().stop() is False


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def test_commands_and_container_do_not_import_proxy_engine() -> None:
    """CLI commands and the container lifecycle must not depend on the ``proxy`` engine package."""
    src = Path(__file__).resolve().parents[1] / "src" / "holon_coherence"
    files = [*sorted((src / "commands").glob("*.py")), *sorted((src / "container").glob("*.py")), src / "cli.py"]
    offenders = {
        f"{path.relative_to(src)}: {module}"
        for path in files
        for module in _imported_modules(path)
        if module == "holon_coherence.proxy" or module.startswith("holon_coherence.proxy.")
    }
    assert not offenders, sorted(offenders)
