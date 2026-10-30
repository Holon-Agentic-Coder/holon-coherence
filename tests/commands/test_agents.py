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

        args_run_agent = parser.parse_args(["run-agent", "claude", "--port", "9090", "task.py"])
        assert args_run_agent.command == "run-agent"
        assert args_run_agent.agent == "claude"
        assert args_run_agent.port == 9090
        assert getattr(args_run_agent, "handler") == handle

        args_alias = parser.parse_args(["claude", "--port", "9090", "task.py"])
        assert args_alias.command == "claude"
        assert args_alias.port == 9090
        assert getattr(args_alias, "handler") == handle

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
