"""Unit tests for agent discovery, runner flags extraction, and execution orchestration."""

from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

import pytest

from holon_coherence.commands.agents import (
    SUPPORTED_AGENTS,
    build_agent_env,
    extract_runner_flags,
    handle,
    register,
    resolve_agent_binary,
    run_agent,
)
from holon_coherence.commands.docker_ops import CONTAINER_NAME, stop_proxy_container


class TestRunnerFlagsExtractionSuite:
    """Tests for runner CLI flag parsing."""

    def test_default_flags(self) -> None:
        flags = extract_runner_flags(["arg1", "arg2"])
        assert flags.ephemeral is False
        assert flags.port is None
        assert flags.agent_args == ["arg1", "arg2"]

    def test_ephemeral_and_port(self) -> None:
        flags = extract_runner_flags(["--ephemeral", "--port", "9090", "main.py"])
        assert flags.ephemeral is True
        assert flags.port == 9090
        assert flags.agent_args == ["main.py"]

    def test_local_llm_base_flag(self) -> None:
        flags = extract_runner_flags(["--local-llm-base=localhost:8081", "-p", "fix issue"])
        assert flags.local_llm_base == "localhost:8081"
        assert flags.agent_args == ["-p", "fix issue"]


class TestAgentBinaryResolutionSuite:
    """Tests for locating agent binaries on PATH."""

    def test_resolve_existing_binary(self) -> None:
        with patch("shutil.which", side_effect=lambda x: f"/usr/local/bin/{x}"):
            assert resolve_agent_binary("agy") == "/usr/local/bin/agy"
            assert resolve_agent_binary("claude") == "/usr/local/bin/claude"
            assert resolve_agent_binary("pi") == "/usr/local/bin/pi"


class TestBuildAgentEnvSuite:
    """Tests for environment variable mapping and credential propagation."""

    def test_credential_mapping_claude(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_AGENT_KEY", "secret-key-123")
        env = build_agent_env("claude", port=8080)
        assert env["ANTHROPIC_API_KEY"] == "secret-key-123"

    def test_credential_mapping_agy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_AGENT_KEY", "secret-key-123")
        env = build_agent_env("agy", port=8080)
        assert env["GEMINI_API_KEY"] == "secret-key-123"
        assert env["AGY_USER_TOKEN"] == "secret-key-123"


class TestRunAgentSuite:
    """Tests for run_agent lifecycle and subprocess invocation."""

    def test_run_agent_missing_binary(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("holon_coherence.commands.agents.resolve_agent_binary", return_value=None):
            code = run_agent("claude", [])
            assert code == 1
            assert "not found on PATH" in capsys.readouterr().err

    def test_run_agent_success(self) -> None:
        with (
            patch("holon_coherence.commands.agents.resolve_agent_binary", return_value="/bin/claude"),
            patch("holon_coherence.commands.agents.ensure_proxy_running", return_value=True),
            patch("holon_coherence.commands.agents.build_agent_env", return_value={}),
            patch("holon_coherence.commands.agents.execute_interactive_process", return_value=0),
            patch("holon_coherence.commands.agents.stop_proxy_container") as mock_stop,
        ):
            code = run_agent("claude", ["arg1"], ephemeral=True)
            assert code == 0
            mock_stop.assert_called_once()


class TestAgentsRegistrationAndDispatch:
    """Tests for run-agent and alias subparser registration and command handling."""

    def test_register_and_defaults(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        parsers = register(subparsers)
        assert len(parsers) == 1 + len(set(SUPPORTED_AGENTS))

        args_run_agent = parser.parse_args(["run-agent", "--port", "9090", "claude", "task.py"])
        assert args_run_agent.command == "run-agent"
        assert args_run_agent.agent == "claude"
        assert args_run_agent.port == 9090
        assert args_run_agent.agent_args == ["task.py"]
        assert args_run_agent.handler == handle
        assert getattr(args_run_agent, "propagates_exit", False) is False

        args_alias = parser.parse_args(["claude", "--port", "9090"])
        assert args_alias.command == "claude"
        assert args_alias.port == 9090
        assert args_alias.handler == handle

    def test_handle_dispatch(self) -> None:
        args = argparse.Namespace(
            command="run-agent",
            agent="claude",
            agent_args=["arg1"],
            ephemeral=False,
            port=None,
            local_llm_base=None,
            model=None,
        )
        with patch("holon_coherence.commands.agents.run_agent", return_value=0) as mock_run:
            res = handle(args)
            assert res == 0
            mock_run.assert_called_once_with(
                "claude", ["arg1"], ephemeral=False, port=None, local_llm_base=None, model=None
            )


class TestExtractRunnerFlags:
    """Tests for CLI runner flag extraction."""

    def test_default_flags(self) -> None:
        flags = extract_runner_flags(["arg1", "arg2"])
        assert flags.ephemeral is False
        assert flags.port is None
        assert flags.agent_args == ["arg1", "arg2"]

    def test_ephemeral_flag(self) -> None:
        flags = extract_runner_flags(["--ephemeral", "-p", "hello"])
        assert flags.ephemeral is True
        assert flags.port is None
        assert flags.agent_args == ["-p", "hello"]

    def test_port_flag_separated(self) -> None:
        flags = extract_runner_flags(["--port", "9090", "--model", "flash"])
        assert flags.ephemeral is False
        assert flags.port == 9090
        assert flags.agent_args == ["--model", "flash"]

    def test_port_flag_equals(self) -> None:
        flags = extract_runner_flags(["--port=9090", "--ephemeral", "task.py"])
        assert flags.ephemeral is True
        assert flags.port == 9090
        assert flags.agent_args == ["task.py"]

    def test_double_dash_delimiter(self) -> None:
        flags = extract_runner_flags(["--ephemeral", "--", "--port", "1234"])
        assert flags.ephemeral is True
        assert flags.port is None
        assert flags.agent_args == ["--port", "1234"]

    def test_invalid_port_value(self) -> None:
        with pytest.raises(SystemExit):
            extract_runner_flags(["--port", "abc"])

    def test_missing_port_argument(self) -> None:
        with pytest.raises(SystemExit):
            extract_runner_flags(["--port"])

    def test_missing_port_before_delimiter_exits(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc:
            extract_runner_flags(["--port", "--"])
        assert exc.value.code == 1
        assert "Option --port requires an argument." in capsys.readouterr().err

    def test_empty_port_equals_exits(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc:
            extract_runner_flags(["--port="])
        assert exc.value.code == 1
        assert "Option --port requires an argument." in capsys.readouterr().err

    @pytest.mark.parametrize("invalid_port", ["0", "70000"])
    def test_port_out_of_range_separated(self, invalid_port: str, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc:
            extract_runner_flags(["--port", invalid_port])
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert f"Error: Port must be between 1 and 65535, got {invalid_port}." in captured.err

    @pytest.mark.parametrize("invalid_port", ["0", "70000"])
    def test_port_out_of_range_equals(self, invalid_port: str, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc:
            extract_runner_flags([f"--port={invalid_port}"])
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert f"Error: Port must be between 1 and 65535, got {invalid_port}." in captured.err

    def test_port_valid_boundary_values(self) -> None:
        assert extract_runner_flags(["--port", "1"]).port == 1
        assert extract_runner_flags(["--port=65535"]).port == 65535


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
            if agent == "agy":
                assert "GEMINI_API_KEY" not in env or env["GEMINI_API_KEY"] != "secret-test-key-123"
            elif agent == "claude":
                assert "ANTHROPIC_API_KEY" not in env or env["ANTHROPIC_API_KEY"] != "secret-test-key-123"
            elif agent == "codex":
                assert "OPENAI_API_KEY" not in env or env["OPENAI_API_KEY"] != "secret-test-key-123"
            elif agent == "opencode":
                assert "OPENCODE_API_KEY" not in env or env["OPENCODE_API_KEY"] != "secret-test-key-123"
            elif agent == "pi":
                assert "PI_API_KEY" not in env or env["PI_API_KEY"] != "secret-test-key-123"


class TestProxyLifecycleAndStopCommand:
    """Tests for daemon mode vs --ephemeral proxy lifecycle and stop command."""

    def test_daemon_mode_leaves_proxy_running(self) -> None:
        with (
            patch("holon_coherence.commands.agents.resolve_agent_binary", return_value="/bin/dummy-agent"),
            patch("holon_coherence.commands.agents.ensure_proxy_running") as mock_ensure,
            patch("holon_coherence.commands.agents.execute_interactive_process", return_value=0),
            patch("holon_coherence.commands.agents.stop_proxy_container") as mock_stop,
        ):
            code = run_agent("agy", ["-p", "test"], ephemeral=False)
            assert code == 0
            mock_ensure.assert_called_once()
            mock_stop.assert_not_called()

    def test_ephemeral_mode_tears_down_proxy(self) -> None:
        with (
            patch("holon_coherence.commands.agents.resolve_agent_binary", return_value="/bin/dummy-agent"),
            patch("holon_coherence.commands.agents.ensure_proxy_running", return_value=True) as mock_ensure,
            patch("holon_coherence.commands.agents.execute_interactive_process", return_value=0),
            patch("holon_coherence.commands.agents.stop_proxy_container") as mock_stop,
        ):
            code = run_agent("agy", ["-p", "test"], ephemeral=True)
            assert code == 0
            mock_ensure.assert_called_once()
            mock_stop.assert_called_once()

    def test_ephemeral_mode_does_not_tear_down_reused_proxy(self) -> None:
        with (
            patch("holon_coherence.commands.agents.resolve_agent_binary", return_value="/bin/dummy-agent"),
            patch("holon_coherence.commands.agents.ensure_proxy_running", return_value=False) as mock_ensure,
            patch("holon_coherence.commands.agents.execute_interactive_process", return_value=0),
            patch("holon_coherence.commands.agents.stop_proxy_container") as mock_stop,
        ):
            code = run_agent("agy", ["-p", "test"], ephemeral=True)
            assert code == 0
            mock_ensure.assert_called_once()
            mock_stop.assert_not_called()

    def test_run_agent_missing_binary_returns_exit_code_1(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("holon_coherence.commands.agents.resolve_agent_binary", return_value=None):
            code = run_agent("agy", [])
            assert code == 1
            captured = capsys.readouterr()
            assert "Agent CLI binary 'agy' not found on PATH" in captured.err

    def test_run_agent_invalid_port_returns_one(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert run_agent("agy", [], port=0) == 1
        captured = capsys.readouterr()
        assert "Error: Port must be between 1 and 65535, got 0." in captured.err

        assert run_agent("agy", [], port=70000) == 1
        captured = capsys.readouterr()
        assert "Error: Port must be between 1 and 65535, got 70000." in captured.err

        assert run_agent("agy", [], port=-1) == 1
        captured = capsys.readouterr()
        assert "Error: Port must be between 1 and 65535, got -1." in captured.err

    def test_stop_proxy_container_invokes_docker_rm(self, capsys: pytest.CaptureFixture[str]) -> None:
        mock_res = MagicMock(returncode=0, stderr="")
        with patch("subprocess.run", return_value=mock_res) as mock_run:
            stop_proxy_container()
            mock_run.assert_called_once_with(
                ["docker", "rm", "-f", CONTAINER_NAME],
                capture_output=True,
                text=True,
            )
        captured = capsys.readouterr()
        assert "✅ holon-coherence container stopped and removed." in captured.out

    def test_stop_proxy_container_failure(self, capsys: pytest.CaptureFixture[str]) -> None:
        mock_res = MagicMock(returncode=1, stderr="daemon is not running")
        with patch("subprocess.run", return_value=mock_res):
            stop_proxy_container()
        captured = capsys.readouterr()
        assert "⚠️  Failed to remove container: daemon is not running" in captured.out

    def test_stop_proxy_container_no_such_container(self, capsys: pytest.CaptureFixture[str]) -> None:
        mock_res = MagicMock(returncode=1, stderr="Error response from daemon: No such container: holon-coherence\n")
        with patch("subprocess.run", return_value=mock_res):
            stop_proxy_container()
        captured = capsys.readouterr()
        assert "✅ No active holon-coherence container found." in captured.out
        assert "Failed to remove container" not in captured.out

    def test_stop_proxy_container_suppresses_os_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError("docker not found")):
            # Should not raise exception
            stop_proxy_container()
        captured = capsys.readouterr()
        assert "⚠️  Failed to remove container: docker not found" in captured.out


class TestLocalLlmRunnerFlagsAndEnvs:
    """Tests for --model and local LLM runner flags/environments."""

    def test_extract_runner_flags_model(self) -> None:
        flags = extract_runner_flags(["--model", "qwen2.5-coder", "run.py"])
        assert flags.model == "qwen2.5-coder"
        assert "--model" in flags.agent_args
        assert "qwen2.5-coder" in flags.agent_args
        assert "run.py" in flags.agent_args

    def test_extract_runner_flags_local_llm_endpoint(self) -> None:
        flags = extract_runner_flags(["--local-llm-endpoint", "localhost:11434", "task.py"])
        assert flags.local_llm_base == "localhost:11434"
        assert flags.agent_args == ["task.py"]

    def test_build_agent_env_claude_local(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_AGENT_KEY", "test-claude-key")
        monkeypatch.delenv("USER", raising=False)
        env = build_agent_env("claude", port=8080, model="claude-3-5-sonnet", local_llm_base="localhost:8081")
        assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8080"
        assert env["ANTHROPIC_AUTH_TOKEN"] == "test-claude-key"
        assert env["ANTHROPIC_API_KEY"] == "test-claude-key"
        assert env["ANTHROPIC_MODEL"] == "claude-3-5-sonnet"
        assert env["ANTHROPIC_DISABLE_TELEMETRY"] == "1"
        assert env["CLAUDE_SUPPRESS_FALLBACK"] == "1"
        assert env["USER"] == "holon"

    def test_build_agent_env_agy_local_gateway_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_AGENT_KEY", "test-agy-key")
        monkeypatch.delenv("USER", raising=False)
        env = build_agent_env("agy", port=8080, model="gemini-flash", local_llm_base="localhost:11434")
        # Local LLM runner sets AGY_GATEWAY_URL with non-loopback alias (NOT GOOGLE_GEMINI_BASE_URL)
        assert env["AGY_GATEWAY_URL"] == "http://127.0.0.1.nip.io:8080"
        assert "GOOGLE_GEMINI_BASE_URL" not in env
        assert env["AGY_MODEL"] == "gemini-flash"
        assert env["GEMINI_API_KEY"] == "test-agy-key"
        assert env["AGY_USER_TOKEN"] == "test-agy-key"
        assert env["USER"] == "holon"

    def test_build_agent_env_agy_local_dummy_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HOLON_AGENT_KEY", raising=False)
        monkeypatch.delenv("USER", raising=False)
        env = build_agent_env("agy", port=8080, model="gemini-flash", local_llm_base="localhost:11434")
        assert env["AGY_GATEWAY_URL"] == "http://127.0.0.1.nip.io:8080"
        assert env["GEMINI_API_KEY"] == "dummy-local-key"
        assert env["AGY_USER_TOKEN"] == "dummy-local-key"
        assert env["USER"] == "holon"

    def test_build_agent_env_cloud_preservation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HOLON_LOCAL_LLM_BASE", raising=False)
        monkeypatch.setenv("HOLON_AGENT_KEY", "test-key")
        # When local_llm_base is None, local override env vars must NOT be present
        claude_env = build_agent_env("claude", port=8080)
        assert "ANTHROPIC_BASE_URL" not in claude_env
        assert "CLAUDE_SUPPRESS_FALLBACK" not in claude_env

        agy_env = build_agent_env("agy", port=8080)
        assert "AGY_GATEWAY_URL" not in agy_env
        assert "AGY_MODEL" not in agy_env
