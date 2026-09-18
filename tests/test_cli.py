"""Unit and integration tests for holon-coherence CLI and coding agent runners."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from holon_coherence.cli import (
    CONTAINER_NAME,
    NO_PROXY_HOSTS,
    SUPPORTED_AGENTS,
    build_agent_env,
    check_docker_daemon,
    ensure_proxy_running,
    execute_interactive_process,
    extract_runner_flags,
    get_or_create_merged_ca_bundle,
    main,
    resolve_agent_binary,
    run_agent,
    stop_proxy_container,
)


class TestExtractRunnerFlags:
    """Tests for CLI runner flag extraction."""

    def test_default_flags(self) -> None:
        ephemeral, port, agent_args = extract_runner_flags(["arg1", "arg2"])
        assert ephemeral is False
        assert port is None
        assert agent_args == ["arg1", "arg2"]

    def test_ephemeral_flag(self) -> None:
        ephemeral, port, agent_args = extract_runner_flags(["--ephemeral", "-p", "hello"])
        assert ephemeral is True
        assert port is None
        assert agent_args == ["-p", "hello"]

    def test_port_flag_separated(self) -> None:
        ephemeral, port, agent_args = extract_runner_flags(["--port", "9090", "--model", "flash"])
        assert ephemeral is False
        assert port == 9090
        assert agent_args == ["--model", "flash"]

    def test_port_flag_equals(self) -> None:
        ephemeral, port, agent_args = extract_runner_flags(["--port=9090", "--ephemeral", "task.py"])
        assert ephemeral is True
        assert port == 9090
        assert agent_args == ["task.py"]

    def test_double_dash_delimiter(self) -> None:
        ephemeral, port, agent_args = extract_runner_flags(["--ephemeral", "--", "--port", "1234"])
        assert ephemeral is True
        assert port is None
        assert agent_args == ["--port", "1234"]

    def test_invalid_port_value(self) -> None:
        with pytest.raises(SystemExit):
            extract_runner_flags(["--port", "abc"])

    def test_missing_port_argument(self) -> None:
        with pytest.raises(SystemExit):
            extract_runner_flags(["--port"])


class TestResolveAgentBinary:
    """Tests for resolving agent binaries on PATH."""

    def test_resolve_existing_binary(self) -> None:
        with patch("shutil.which", side_effect=lambda x: f"/usr/local/bin/{x}"):
            assert resolve_agent_binary("agy") == "/usr/local/bin/agy"
            assert resolve_agent_binary("claude") == "/usr/local/bin/claude"
            assert resolve_agent_binary("codex") == "/usr/local/bin/codex"
            assert resolve_agent_binary("opencode") == "/usr/local/bin/opencode"
            assert resolve_agent_binary("pi") == "/usr/local/bin/pi"

    def test_resolve_antigravity_fallback_for_agy(self) -> None:
        def fake_which(x: str) -> str | None:
            if x == "antigravity":
                return "/opt/bin/antigravity"
            return None

        with patch("shutil.which", side_effect=fake_which):
            assert resolve_agent_binary("agy") == "/opt/bin/antigravity"

    def test_resolve_missing_binary(self) -> None:
        with patch("shutil.which", return_value=None):
            assert resolve_agent_binary("nonexistent-agent") is None


class TestCredentialMappingAndNativeAuth:
    """Tests for HOLON_AGENT_KEY mapping and native auth fallback."""

    def test_credential_mapping_agy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_AGENT_KEY", "secret-test-key-123")
        env = build_agent_env("agy", port=8080)
        assert env["GEMINI_API_KEY"] == "secret-test-key-123"
        assert env["AGY_USER_TOKEN"] == "secret-test-key-123"

    def test_credential_mapping_antigravity_alias(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_AGENT_KEY", "secret-test-key-123")
        env = build_agent_env("antigravity", port=8080)
        assert env["GEMINI_API_KEY"] == "secret-test-key-123"
        assert env["AGY_USER_TOKEN"] == "secret-test-key-123"

    def test_credential_mapping_claude(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_AGENT_KEY", "secret-test-key-123")
        env = build_agent_env("claude", port=8080)
        assert env["ANTHROPIC_API_KEY"] == "secret-test-key-123"

    def test_credential_mapping_codex(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_AGENT_KEY", "secret-test-key-123")
        env = build_agent_env("codex", port=8080)
        assert env["OPENAI_API_KEY"] == "secret-test-key-123"

    def test_credential_mapping_opencode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_AGENT_KEY", "secret-test-key-123")
        env = build_agent_env("opencode", port=8080)
        assert env["OPENCODE_API_KEY"] == "secret-test-key-123"

    def test_credential_mapping_pi(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_AGENT_KEY", "secret-test-key-123")
        env = build_agent_env("pi", port=8080)
        assert env["PI_API_KEY"] == "secret-test-key-123"

    def test_native_auth_fallback_when_holon_key_omitted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HOLON_AGENT_KEY", raising=False)
        monkeypatch.setenv("EXISTING_HOST_SESSION", "present")

        for agent in SUPPORTED_AGENTS:
            env = build_agent_env(agent, port=8080)
            assert "HOLON_AGENT_KEY" not in env
            assert env.get("EXISTING_HOST_SESSION") == "present"
            # No vendor keys forced
            if agent in ("agy", "antigravity"):
                assert "GEMINI_API_KEY" not in env or env["GEMINI_API_KEY"] != "secret-test-key-123"
            elif agent == "claude":
                assert "ANTHROPIC_API_KEY" not in env or env["ANTHROPIC_API_KEY"] != "secret-test-key-123"


class TestProxyEnvironmentInjectionAndMergedCA:
    """Tests for proxy environment routing and merged CA bundle generation."""

    def test_proxy_routing_variables_injected(self) -> None:
        with (
            patch("os.path.exists", return_value=True),
            patch("holon_coherence.cli.get_or_create_merged_ca_bundle", return_value="/mock/merged.crt"),
        ):
            env = build_agent_env("claude", port=9090)
            expected_url = "http://127.0.0.1:9090"
            assert env["HTTP_PROXY"] == expected_url
            assert env["HTTPS_PROXY"] == expected_url
            assert env["ALL_PROXY"] == expected_url
            assert env["http_proxy"] == expected_url
            assert env["https_proxy"] == expected_url
            assert env["all_proxy"] == expected_url
            assert env["NO_PROXY"] == NO_PROXY_HOSTS
            assert env["no_proxy"] == NO_PROXY_HOSTS
            assert env["SSL_CERT_FILE"] == "/mock/merged.crt"
            assert env["REQUESTS_CA_BUNDLE"] == "/mock/merged.crt"
            assert env["CURL_CA_BUNDLE"] == "/mock/merged.crt"
            assert "NODE_EXTRA_CA_CERTS" in env

    def test_proxy_routing_preserves_existing_no_proxy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NO_PROXY", "internal.corp.com,*.local")
        env = build_agent_env("claude", port=9090)
        assert env["NO_PROXY"] == f"{NO_PROXY_HOSTS},internal.corp.com,*.local"
        assert env["no_proxy"] == f"{NO_PROXY_HOSTS},internal.corp.com,*.local"

    def test_ca_cert_missing_diagnostic_warning(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("os.path.exists", return_value=False):
            env = build_agent_env("claude", port=9090)
            assert "SSL_CERT_FILE" not in env
            assert "REQUESTS_CA_BUNDLE" not in env
            assert "CURL_CA_BUNDLE" not in env
            assert "NODE_EXTRA_CA_CERTS" not in env
            captured = capsys.readouterr()
            assert "Warning: CA certificate not found" in captured.err
            assert "Ensure 'holon-coherence start' has been run at least once" in captured.err
            assert "initialize CA with 'holon-coherence init-ca'" in captured.err

    def test_merged_ca_bundle_generation(self, tmp_path: Path) -> None:
        holon_ca = tmp_path / "mitmproxy-ca-cert.pem"
        holon_ca.write_text("-----BEGIN CERTIFICATE-----\nHOLON_ROOT_CA\n-----END CERTIFICATE-----")

        sys_ca = tmp_path / "system-ca.pem"
        sys_ca.write_text("-----BEGIN CERTIFICATE-----\nSYSTEM_ROOT_CA\n-----END CERTIFICATE-----")

        with patch("holon_coherence.cli.find_system_ca_bundle", return_value=str(sys_ca)):
            merged_path = get_or_create_merged_ca_bundle(str(holon_ca))
            assert os.path.isfile(merged_path)
            with open(merged_path, encoding="utf-8") as f:
                content = f.read()
            assert "SYSTEM_ROOT_CA" in content
            assert "HOLON_ROOT_CA" in content


class TestChildProcessExecutionAndExitCodes:
    """Tests for child process exit code propagation, stdio passthrough, and signal handling."""

    def test_exit_code_propagation_success(self) -> None:
        mock_proc = MagicMock()
        mock_proc.poll.side_effect = [None, 0]
        mock_proc.returncode = 0

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            code = execute_interactive_process(["test-cmd"], {"ENV": "val"})
            assert code == 0
            mock_popen.assert_called_once_with(
                ["test-cmd"],
                env={"ENV": "val"},
                stdin=sys.stdin,
                stdout=sys.stdout,
                stderr=sys.stderr,
            )

    def test_exit_code_propagation_nonzero(self) -> None:
        mock_proc = MagicMock()
        mock_proc.poll.side_effect = [None, 42]
        mock_proc.returncode = 42

        with patch("subprocess.Popen", return_value=mock_proc):
            code = execute_interactive_process(["test-cmd"], {})
            assert code == 42

    def test_signal_exit_code_propagation(self) -> None:
        mock_proc = MagicMock()
        mock_proc.poll.side_effect = [None, -signal.SIGINT]
        mock_proc.returncode = -signal.SIGINT

        with patch("subprocess.Popen", return_value=mock_proc):
            code = execute_interactive_process(["test-cmd"], {})
            assert code == 128 + signal.SIGINT

    def test_signal_forwarding(self) -> None:
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None

        captured_handler: dict[int, Any] = {}

        def mock_signal(sig: int, handler: Any) -> Any:
            captured_handler[sig] = handler
            return MagicMock()

        with patch("subprocess.Popen", return_value=mock_proc), patch("signal.signal", side_effect=mock_signal):
            # Start process in mock
            mock_proc.poll.side_effect = [None, None, 0]
            mock_proc.returncode = 0

            # Trigger signal handler
            if signal.SIGINT in captured_handler:
                captured_handler[signal.SIGINT](signal.SIGINT, None)
                mock_proc.send_signal.assert_called_with(signal.SIGINT)


class TestDockerDiagnosticsAndPortConflicts:
    """Tests for Docker daemon diagnostic handling and port conflict detection."""

    def test_docker_cli_missing(self) -> None:
        with patch("shutil.which", return_value=None):
            ok, err = check_docker_daemon()
            assert ok is False
            assert "Docker CLI is not installed" in err

    def test_docker_daemon_not_running(self) -> None:
        mock_res = MagicMock()
        with (
            patch("shutil.which", return_value="/usr/local/bin/docker"),
            patch("subprocess.run", return_value=mock_res),
        ):
            ok, err = check_docker_daemon()
            assert ok is False
            assert "Docker daemon is not running" in err

    def test_port_conflict_detection_when_container_not_running(self) -> None:
        with (
            patch("holon_coherence.cli.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.cli.is_port_in_use", return_value=True),
            patch("holon_coherence.cli.is_container_running", return_value=False),
            pytest.raises(SystemExit) as exc_info,
        ):
            ensure_proxy_running(port=8080)
        assert exc_info.value.code == 1

    def test_reuse_existing_healthy_container(self) -> None:
        with (
            patch("holon_coherence.cli.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.cli.is_port_in_use", return_value=True),
            patch("holon_coherence.cli.is_container_running", return_value=True),
            patch("subprocess.run") as mock_run,
        ):
            ensure_proxy_running(port=8080)
            # Should return immediately without docker run
            mock_run.assert_not_called()


class TestProxyLifecycleAndStopCommand:
    """Tests for daemon mode vs --ephemeral proxy lifecycle and stop command."""

    def test_daemon_mode_leaves_proxy_running(self) -> None:
        with (
            patch("holon_coherence.cli.resolve_agent_binary", return_value="/bin/dummy-agent"),
            patch("holon_coherence.cli.ensure_proxy_running") as mock_ensure,
            patch("holon_coherence.cli.execute_interactive_process", return_value=0),
            patch("holon_coherence.cli.stop_proxy_container") as mock_stop,
        ):
            code = run_agent("agy", ["-p", "test"], ephemeral=False)
            assert code == 0
            mock_ensure.assert_called_once()
            mock_stop.assert_not_called()

    def test_ephemeral_mode_tears_down_proxy(self) -> None:
        with (
            patch("holon_coherence.cli.resolve_agent_binary", return_value="/bin/dummy-agent"),
            patch("holon_coherence.cli.ensure_proxy_running") as mock_ensure,
            patch("holon_coherence.cli.execute_interactive_process", return_value=0),
            patch("holon_coherence.cli.stop_proxy_container") as mock_stop,
        ):
            code = run_agent("agy", ["-p", "test"], ephemeral=True)
            assert code == 0
            mock_ensure.assert_called_once()
            mock_stop.assert_called_once()

    def test_run_agent_missing_binary_returns_exit_code_1(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("holon_coherence.cli.resolve_agent_binary", return_value=None):
            code = run_agent("agy", [])
            assert code == 1
            captured = capsys.readouterr()
            assert "Agent CLI binary 'agy' not found on PATH" in captured.err

    def test_stop_proxy_container_invokes_docker_rm(self) -> None:
        with patch("subprocess.run") as mock_run:
            stop_proxy_container()
            mock_run.assert_called_once_with(
                ["docker", "rm", "-f", CONTAINER_NAME],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def test_stop_proxy_container_suppresses_os_error(self) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError("docker not found")):
            # Should not raise exception
            stop_proxy_container()


class TestCLIDispatchAndMain:
    """Tests for direct aliases and run-agent CLI dispatch."""

    def test_direct_alias_dispatch(self) -> None:
        with patch("holon_coherence.cli.run_agent", return_value=0) as mock_run_agent, pytest.raises(SystemExit) as exc:
            main(["agy", "--ephemeral", "--port", "9090", "-p", "fix issue"])
        assert exc.value.code == 0
        mock_run_agent.assert_called_once_with("agy", ["-p", "fix issue"], ephemeral=True, port=9090)

    def test_run_agent_dispatch(self) -> None:
        with patch("holon_coherence.cli.run_agent", return_value=0) as mock_run_agent, pytest.raises(SystemExit) as exc:
            main(["run-agent", "claude", "--port", "8085", "src/main.py"])
        assert exc.value.code == 0
        mock_run_agent.assert_called_once_with("claude", ["src/main.py"], ephemeral=False, port=8085)

    def test_run_agent_unsupported_agent(self) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["run-agent", "unknown-agent"])
        assert exc.value.code == 1

    def test_stop_subcommand_dispatch(self) -> None:
        with patch("holon_coherence.cli.stop_proxy_container") as mock_stop:
            main(["stop"])
            mock_stop.assert_called_once()

    def test_port_configuration_from_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_PROXY_PORT", "9999")
        with (
            patch("holon_coherence.cli.resolve_agent_binary", return_value="/bin/dummy-agent"),
            patch("holon_coherence.cli.ensure_proxy_running") as mock_ensure,
            patch("holon_coherence.cli.execute_interactive_process", return_value=0),
        ):
            run_agent("codex", [])
            mock_ensure.assert_called_once_with(port=9999)

    def test_port_flag_overrides_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_PROXY_PORT", "9999")
        with (
            patch("holon_coherence.cli.resolve_agent_binary", return_value="/bin/dummy-agent"),
            patch("holon_coherence.cli.ensure_proxy_running") as mock_ensure,
            patch("holon_coherence.cli.execute_interactive_process", return_value=0),
        ):
            run_agent("codex", [], port=7777)
            mock_ensure.assert_called_once_with(port=7777)

    def test_run_agent_flexible_argument_ordering(self) -> None:
        with patch("holon_coherence.cli.run_agent", return_value=0) as mock_run_agent, pytest.raises(SystemExit) as exc:
            main(["run-agent", "--ephemeral", "claude", "-p", "fix issue"])
        assert exc.value.code == 0
        mock_run_agent.assert_called_once_with("claude", ["-p", "fix issue"], ephemeral=True, port=None)

    def test_run_agent_flexible_ordering_with_port(self) -> None:
        with patch("holon_coherence.cli.run_agent", return_value=0) as mock_run_agent, pytest.raises(SystemExit) as exc:
            main(["run-agent", "--port", "9090", "--ephemeral", "claude"])
        assert exc.value.code == 0
        mock_run_agent.assert_called_once_with("claude", [], ephemeral=True, port=9090)

    def test_direct_alias_help_passthrough_after_delimiter(self) -> None:
        with patch("holon_coherence.cli.run_agent", return_value=0) as mock_run_agent, pytest.raises(SystemExit) as exc:
            main(["claude", "--", "--help"])
        assert exc.value.code == 0
        mock_run_agent.assert_called_once_with("claude", ["--help"], ephemeral=False, port=None)

    def test_run_agent_help_passthrough_after_delimiter(self) -> None:
        with patch("holon_coherence.cli.run_agent", return_value=0) as mock_run_agent, pytest.raises(SystemExit) as exc:
            main(["run-agent", "--ephemeral", "claude", "--", "--help"])
        assert exc.value.code == 0
        mock_run_agent.assert_called_once_with("claude", ["--help"], ephemeral=True, port=None)

    def test_direct_alias_runner_help_intercept(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["claude", "--help"])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "usage: holon-coherence claude" in captured.out

    def test_run_agent_runner_help_intercept(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["run-agent", "claude", "--help"])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "usage: holon-coherence claude" in captured.out

    def test_run_agent_general_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["run-agent", "--help"])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "usage: holon-coherence run-agent" in captured.out
