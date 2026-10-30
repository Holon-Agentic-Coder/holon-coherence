"""Unit and integration tests for holon-coherence CLI and coding agent runners."""

from __future__ import annotations

import os
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest

from holon_coherence.cli import (
    DEFAULT_PROXY_PORT,
    extract_runner_flags,
    main,
    run_agent,
)
from holon_coherence.host_local import HOST_LOCAL_ENV_VAR, decode_targets


@pytest.fixture(autouse=True)
def _never_persist_real_web_token() -> Iterator[MagicMock]:
    """A ``start --web`` resolves an inspector token; keep it out of the real ~/.holon/web-token.

    ``HOLON_COHERENCE_WEB`` is cleared so a developer's shell opt-in cannot flip the headless default under test.
    """
    with (
        patch.dict(os.environ, {}, clear=False),
        patch("holon_coherence.commands.start.save_web_token") as mock_save,
    ):
        os.environ.pop("HOLON_COHERENCE_WEB", None)
        yield mock_save


class TestCLIDispatchAndMain:
    """Tests for direct aliases and run-agent CLI dispatch."""

    def test_direct_alias_dispatch(self) -> None:
        with patch("holon_coherence.cli.run_agent", return_value=0) as mock_run_agent, pytest.raises(SystemExit) as exc:
            main(["agy", "--ephemeral", "--port", "9090", "-p", "fix issue"])
        assert exc.value.code == 0
        mock_run_agent.assert_called_once_with(
            "agy", ["-p", "fix issue"], ephemeral=True, port=9090, local_llm_base=None
        )

    def test_run_agent_dispatch(self) -> None:
        with patch("holon_coherence.cli.run_agent", return_value=0) as mock_run_agent, pytest.raises(SystemExit) as exc:
            main(["run-agent", "claude", "--port", "8085", "src/main.py"])
        assert exc.value.code == 0
        mock_run_agent.assert_called_once_with(
            "claude", ["src/main.py"], ephemeral=False, port=8085, local_llm_base=None
        )

    def test_run_agent_unsupported_agent(self) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["run-agent", "unknown-agent"])
        assert exc.value.code == 1

    def test_stop_subcommand_dispatch(self) -> None:
        with patch("holon_coherence.commands.docker_ops.stop_proxy_container") as mock_stop:
            main(["stop"])
            mock_stop.assert_called_once_with("holon-coherence-proxy")

        with patch("holon_coherence.commands.docker_ops.stop_proxy_container") as mock_stop:
            main(["stop", "--name", "sandbox-custom"])
            mock_stop.assert_called_once_with("sandbox-custom")

    def test_status_and_logs_subcommand_dispatch_with_name(self) -> None:
        with patch("holon_coherence.commands.docker_ops.handle_status") as mock_status:
            main(["status", "--name", "sandbox-custom"])
            assert mock_status.call_count == 1
            assert mock_status.call_args[0][0].name == "sandbox-custom"

        with patch("holon_coherence.commands.docker_ops.handle_logs") as mock_logs:
            main(["logs", "--name", "sandbox-custom", "-f"])
            assert mock_logs.call_count == 1
            assert mock_logs.call_args[0][0].name == "sandbox-custom"
            assert mock_logs.call_args[0][0].follow is True

    def test_port_configuration_from_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_PROXY_PORT", "9999")
        with (
            patch("holon_coherence.commands.agents.resolve_agent_binary", return_value="/bin/dummy-agent"),
            patch("holon_coherence.commands.agents.ensure_proxy_running") as mock_ensure,
            patch("holon_coherence.commands.agents.execute_interactive_process", return_value=0),
        ):
            run_agent("codex", [])
            mock_ensure.assert_called_once_with(port=9999, host_local_spec="")

    def test_port_flag_overrides_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_PROXY_PORT", "9999")
        with (
            patch("holon_coherence.commands.agents.resolve_agent_binary", return_value="/bin/dummy-agent"),
            patch("holon_coherence.commands.agents.ensure_proxy_running") as mock_ensure,
            patch("holon_coherence.commands.agents.execute_interactive_process", return_value=0),
        ):
            run_agent("codex", [], port=7777)
            mock_ensure.assert_called_once_with(port=7777, host_local_spec="")

    @pytest.mark.parametrize("invalid_port", ["0", "70000", "abc"])
    def test_run_agent_invalid_env_port_fallback(
        self, invalid_port: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("HOLON_PROXY_PORT", invalid_port)
        with (
            patch("holon_coherence.commands.agents.resolve_agent_binary", return_value="/bin/dummy-agent"),
            patch("holon_coherence.commands.agents.ensure_proxy_running") as mock_ensure,
            patch("holon_coherence.commands.agents.execute_interactive_process", return_value=0),
        ):
            run_agent("codex", [])
            mock_ensure.assert_called_once_with(port=DEFAULT_PROXY_PORT, host_local_spec="")
            captured = capsys.readouterr()
            expected_warning = f"⚠️  Invalid HOLON_PROXY_PORT '{invalid_port}', falling back to {DEFAULT_PROXY_PORT}."
            assert expected_warning in captured.err

    def test_run_agent_flexible_argument_ordering(self) -> None:
        with patch("holon_coherence.cli.run_agent", return_value=0) as mock_run_agent, pytest.raises(SystemExit) as exc:
            main(["run-agent", "--ephemeral", "claude", "-p", "fix issue"])
        assert exc.value.code == 0
        mock_run_agent.assert_called_once_with(
            "claude", ["-p", "fix issue"], ephemeral=True, port=None, local_llm_base=None
        )

    def test_run_agent_flexible_ordering_with_port(self) -> None:
        with patch("holon_coherence.cli.run_agent", return_value=0) as mock_run_agent, pytest.raises(SystemExit) as exc:
            main(["run-agent", "--port", "9090", "--ephemeral", "claude"])
        assert exc.value.code == 0
        mock_run_agent.assert_called_once_with("claude", [], ephemeral=True, port=9090, local_llm_base=None)

    def test_direct_alias_help_passthrough_after_delimiter(self) -> None:
        with patch("holon_coherence.cli.run_agent", return_value=0) as mock_run_agent, pytest.raises(SystemExit) as exc:
            main(["claude", "--", "--help"])
        assert exc.value.code == 0
        mock_run_agent.assert_called_once_with("claude", ["--help"], ephemeral=False, port=None, local_llm_base=None)

    def test_run_agent_help_passthrough_after_delimiter(self) -> None:
        with patch("holon_coherence.cli.run_agent", return_value=0) as mock_run_agent, pytest.raises(SystemExit) as exc:
            main(["run-agent", "--ephemeral", "claude", "--", "--help"])
        assert exc.value.code == 0
        mock_run_agent.assert_called_once_with("claude", ["--help"], ephemeral=True, port=None, local_llm_base=None)

    def test_direct_alias_runner_help_intercept(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["claude", "--help"])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "usage: holon-coherence claude" in captured.out
        assert "[--local-llm-base BASE]" in captured.out

    def test_run_agent_runner_help_intercept(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["run-agent", "claude", "--help"])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "usage: holon-coherence claude" in captured.out
        assert "[--local-llm-base BASE]" in captured.out

    def test_run_agent_general_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["run-agent", "--help"])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "usage: holon-coherence run-agent" in captured.out
        assert "[--local-llm-base BASE]" in captured.out

    def test_run_agent_parameterless_exits_one(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["run-agent"])
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "usage: holon-coherence run-agent" in captured.out
        assert "[--local-llm-base BASE]" in captured.out

    def test_parameterless_cli_prints_usage_to_stderr_and_exits_one(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc:
            main([])
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "usage: holon-coherence" in captured.err

    def test_runner_help_mentions_delimiter_note(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["claude", "--help"])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "note:" in captured.out
        assert "Use '--' to pass flags directly to the underlying agent" in captured.out

    def test_run_command_deduplicates_no_proxy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NO_PROXY", "127.0.0.1,api.github.com,internal.corp.com,127.0.0.1")
        captured_env: dict[str, str] = {}

        def fake_execute(cmd: list[str], env: dict[str, str]) -> int:
            captured_env.update(env)
            return 0

        with (
            patch("os.path.exists", return_value=False),
            patch("holon_coherence.commands.runner.execute_interactive_process", side_effect=fake_execute),
            pytest.raises(SystemExit) as exc,
        ):
            main(["run", "--", "echo", "hello"])
        assert exc.value.code == 0
        entries = captured_env["NO_PROXY"].split(",")
        assert len(entries) == len(set(entries))
        assert "internal.corp.com" in entries
        assert "127.0.0.1" in entries
        assert captured_env["no_proxy"] == captured_env["NO_PROXY"]

    def test_run_command_sets_merged_ca_in_node_extra_ca_certs(self) -> None:
        captured_env: dict[str, str] = {}

        def fake_execute(cmd: list[str], env: dict[str, str]) -> int:
            captured_env.update(env)
            return 0

        with (
            patch("os.path.exists", return_value=True),
            patch("holon_coherence.commands.runner.get_or_create_merged_ca_bundle", return_value="/mock/merged.crt"),
            patch("holon_coherence.commands.runner.execute_interactive_process", side_effect=fake_execute),
            pytest.raises(SystemExit) as exc,
        ):
            main(["run", "--", "echo", "hello"])
        assert exc.value.code == 0
        assert captured_env["NODE_EXTRA_CA_CERTS"] == "/mock/merged.crt"
        assert captured_env["SSL_CERT_FILE"] == "/mock/merged.crt"
        assert captured_env["GIT_SSL_CAINFO"] == "/mock/merged.crt"

    def test_run_command_uses_execute_interactive_process(self) -> None:
        """run subcommand delegates to execute_interactive_process, not subprocess.run."""
        with (
            patch("os.path.exists", return_value=False),
            patch("holon_coherence.commands.runner.execute_interactive_process", return_value=42) as mock_exec,
            pytest.raises(SystemExit) as exc,
        ):
            main(["run", "--", "my-tool", "--flag"])
        assert exc.value.code == 42
        mock_exec.assert_called_once()
        cmd_arg = mock_exec.call_args[0][0]
        assert cmd_arg == ["my-tool", "--flag"]

    def test_start_command_defaults_port_to_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_PROXY_PORT", "9191")
        with (
            patch("holon_coherence.commands.start.is_in_container", return_value=False),
            patch("holon_coherence.commands.start.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.commands.start.ensure_docker_image"),
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch("subprocess.run") as mock_run,
        ):
            main(["start", "-d"])
            assert mock_run.call_count == 2
            docker_cmd = mock_run.call_args_list[1][0][0]
            assert "--init" in docker_cmd
            port_index = docker_cmd.index("-p") + 1
            assert docker_cmd[port_index] == "127.0.0.1:9191:8080"

    def test_start_command_default_port_fallback_on_invalid_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_PROXY_PORT", "invalid_port")
        with (
            patch("holon_coherence.commands.start.is_in_container", return_value=False),
            patch("holon_coherence.commands.start.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.commands.start.is_port_in_use", return_value=False),
            patch("holon_coherence.commands.start.ensure_docker_image"),
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch("subprocess.run") as mock_run,
        ):
            main(["start", "-d"])
            docker_cmd = mock_run.call_args_list[1][0][0]
            assert "--init" in docker_cmd
            port_index = docker_cmd.index("-p") + 1
            assert docker_cmd[port_index] == f"127.0.0.1:{DEFAULT_PROXY_PORT}:8080"

    def test_start_command_interactive_includes_init_flag(self) -> None:
        with (
            patch("holon_coherence.commands.start.is_in_container", return_value=False),
            patch("holon_coherence.commands.start.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.commands.start.ensure_docker_image"),
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch("subprocess.run") as mock_run,
        ):
            main(["start"])
            assert mock_run.call_count == 2
            docker_cmd = mock_run.call_args_list[1][0][0]
            assert "--init" in docker_cmd
            assert "--rm" in docker_cmd

    def test_start_command_rejects_removed_native_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        """The host-mitmproxy escape hatch was removed; it must not be silently accepted."""
        with pytest.raises(SystemExit) as exc_info:
            main(["start", "--native"])
        assert exc_info.value.code == 2
        assert "--native" in capsys.readouterr().err

    def test_in_container_start_still_launches_mitmproxy_directly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The Dockerfile ENTRYPOINT runs `holon-coherence start --port 8080` inside the container.

        That is the only reason the direct-mitmproxy branch exists now that --native is gone, so it
        must keep working without touching Docker.
        """
        launched: list[list[str]] = []

        def fake_run(cmd, *args, **kwargs):
            launched.append(list(cmd))
            return MagicMock(returncode=0)

        monkeypatch.setattr("holon_coherence.commands.start.is_in_container", lambda: True)
        with patch("subprocess.run", side_effect=fake_run):
            main(["start", "--port", "8080"])

        assert len(launched) == 1, "no Docker command may run inside the container"
        cmd = launched[0]
        assert cmd[0].endswith("mitmdump")
        assert "-s" in cmd
        assert cmd[-2:] == ["--listen-port", "8080"]
        assert "mitm_addon.py" in cmd[cmd.index("-s") + 1]

    def test_start_command_with_web_flag(self) -> None:
        with (
            patch("holon_coherence.commands.start.is_in_container", return_value=False),
            patch("holon_coherence.commands.start.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.commands.start.is_port_in_use", return_value=False),
            patch("holon_coherence.commands.start.save_web_token"),
            patch("holon_coherence.commands.start.ensure_docker_image"),
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch("subprocess.run") as mock_run,
        ):
            main(["start", "-d", "--web"])
            assert mock_run.call_count == 2
            docker_cmd = mock_run.call_args_list[1][0][0]
            # Verify port mapping for web dashboard
            assert "-p" in docker_cmd
            web_port_mapping = "127.0.0.1:8081:8081"
            assert web_port_mapping in docker_cmd
            # Verify internal start args
            assert "--web" in docker_cmd
            web_port_idx = docker_cmd.index("--web-port") + 1
            assert docker_cmd[web_port_idx] == "8081"

    def test_start_command_proxy_port_conflict_fallback(self) -> None:
        def fake_in_use(port: int, host: str = "127.0.0.1") -> bool:
            return port == 8080

        with (
            patch("holon_coherence.commands.start.is_in_container", return_value=False),
            patch("holon_coherence.commands.start.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.commands.start.is_port_in_use", side_effect=fake_in_use),
            patch("holon_coherence.commands.start.ensure_docker_image"),
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch("subprocess.run") as mock_run,
        ):
            main(["start", "-d"])
            docker_cmd = mock_run.call_args_list[1][0][0]
            port_index = docker_cmd.index("-p") + 1
            assert docker_cmd[port_index] == "127.0.0.1:8081:8080"
            assert "HOLON_PROXY_PORT=8081" in docker_cmd

    def test_start_command_web_port_conflict_fallback(self) -> None:
        def fake_in_use(port: int, host: str = "127.0.0.1") -> bool:
            return port == 8081

        with (
            patch("holon_coherence.commands.start.is_in_container", return_value=False),
            patch("holon_coherence.commands.start.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.commands.start.is_port_in_use", side_effect=fake_in_use),
            patch("holon_coherence.commands.start.save_web_token"),
            patch("holon_coherence.commands.start.ensure_docker_image"),
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch("subprocess.run") as mock_run,
        ):
            main(["start", "-d", "--web"])
            docker_cmd = mock_run.call_args_list[1][0][0]
            assert "127.0.0.1:8082:8081" in docker_cmd

    def test_start_command_proxy_and_web_port_conflict_prevents_collision(self) -> None:
        def fake_in_use(port: int, host: str = "127.0.0.1") -> bool:
            return port in (8080, 8081)

        with (
            patch("holon_coherence.commands.start.is_in_container", return_value=False),
            patch("holon_coherence.commands.start.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.commands.start.is_port_in_use", side_effect=fake_in_use),
            patch("holon_coherence.commands.start.save_web_token"),
            patch("holon_coherence.commands.start.ensure_docker_image"),
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch("subprocess.run") as mock_run,
        ):
            main(["start", "-d", "--web"])
            docker_cmd = mock_run.call_args_list[1][0][0]
            # Proxy was 8080 (in use) -> falls back to 8082
            assert "127.0.0.1:8082:8080" in docker_cmd
            # Web was 8081 (in use) -> candidate 8082 collides with proxy -> falls back to 8083
            assert "127.0.0.1:8083:8081" in docker_cmd

    def test_start_command_with_custom_web_port(self) -> None:
        with (
            patch("holon_coherence.commands.start.is_in_container", return_value=False),
            patch("holon_coherence.commands.start.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.commands.start.is_port_in_use", return_value=False),
            patch("holon_coherence.commands.start.save_web_token"),
            patch("holon_coherence.commands.start.ensure_docker_image"),
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch("subprocess.run") as mock_run,
        ):
            main(["start", "-d", "--web", "--web-port", "9090"])
            assert mock_run.call_count == 2
            docker_cmd = mock_run.call_args_list[1][0][0]
            assert "127.0.0.1:9090:8081" in docker_cmd
            assert "--web" in docker_cmd
            web_port_idx = docker_cmd.index("--web-port") + 1
            assert docker_cmd[web_port_idx] == "8081"

    def test_start_command_with_no_web_flag_omits_web_port(self) -> None:
        with (
            patch("holon_coherence.commands.start.is_in_container", return_value=False),
            patch("holon_coherence.commands.start.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.commands.start.is_port_in_use", return_value=False),
            patch("holon_coherence.commands.start.ensure_docker_image"),
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch("subprocess.run") as mock_run,
        ):
            main(["start", "-d", "--no-web"])
            assert mock_run.call_count == 2
            docker_cmd = mock_run.call_args_list[1][0][0]
            assert "--web" not in docker_cmd
            assert "--web-port" not in docker_cmd
            assert not any("8081" in arg for arg in docker_cmd)

    def test_in_container_start_with_web_passes_web_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        launched: list[list[str]] = []

        def fake_run(cmd, *args, **kwargs):
            launched.append(list(cmd))
            return MagicMock(returncode=0)

        monkeypatch.setattr("holon_coherence.commands.start.is_in_container", lambda: True)
        with (
            patch("holon_coherence.commands.start.save_web_token"),
            patch("subprocess.run", side_effect=fake_run),
        ):
            main(["start", "--web", "--web-port", "8081"])

        assert len(launched) == 1
        cmd = launched[0]
        assert cmd[0].endswith("mitmweb")
        assert "--web-host" in cmd
        host_idx = cmd.index("--web-host") + 1
        assert cmd[host_idx] == "0.0.0.0"
        assert "--web-port" in cmd
        port_idx = cmd.index("--web-port") + 1
        assert cmd[port_idx] == "8081"


class TestEndToEndDispatch:
    """End-to-end integration tests for CLI dispatch paths through main()."""

    def test_main_agent_missing_binary_exits_one(self, capsys: pytest.CaptureFixture[str]) -> None:
        """main(['agy']) with no agy binary on PATH should print an error and exit 1."""
        with (
            patch("shutil.which", return_value=None),
            pytest.raises(SystemExit) as exc_info,
        ):
            main(["agy"])
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "not found on PATH" in captured.err

    def test_main_run_agent_missing_binary_exits_one(self, capsys: pytest.CaptureFixture[str]) -> None:
        """main(['run-agent', 'claude']) with no claude binary should print an error and exit 1."""
        with (
            patch("shutil.which", return_value=None),
            pytest.raises(SystemExit) as exc_info,
        ):
            main(["run-agent", "claude"])
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "not found on PATH" in captured.err


class TestLocalLlmRunnerFlag:
    """`--local-llm-base` must intercept a host-local model server instead of bypassing the proxy."""

    HOST_IPS = ("192.168.2.13",)

    def test_flag_extraction_equals_form(self) -> None:
        flags = extract_runner_flags(["--local-llm-base=localhost:8081", "-p", "fix issue"])
        assert flags.local_llm_base == "localhost:8081"
        assert flags.agent_args == ["-p", "fix issue"]

    def test_flag_extraction_separated_form_before_delimiter(self) -> None:
        flags = extract_runner_flags(["--local-llm-base", "127.0.0.1:8081", "--", "--model", "qwen"])
        assert flags.local_llm_base == "127.0.0.1:8081"
        assert flags.agent_args == ["--model", "qwen"]

    def test_flag_is_not_forwarded_to_the_agent(self) -> None:
        flags = extract_runner_flags(["--local-llm-base", "localhost:8081"])
        assert flags.agent_args == []

    def test_base_url_value_is_accepted(self) -> None:
        flags = extract_runner_flags(["--local-llm-base=http://localhost:11434/v1"])
        assert flags.local_llm_base == "http://localhost:11434/v1"

    def test_missing_argument_exits(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc_info:
            extract_runner_flags(["--local-llm-base"])
        assert exc_info.value.code == 1
        assert "--local-llm-base requires an argument" in capsys.readouterr().err

    def test_missing_argument_before_delimiter_exits(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc_info:
            extract_runner_flags(["--local-llm-base", "--", "-p", "hi"])
        assert exc_info.value.code == 1
        assert "--local-llm-base requires an argument" in capsys.readouterr().err

    def test_empty_equals_argument_exits(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc_info:
            extract_runner_flags(["--local-llm-base="])
        assert exc_info.value.code == 1
        assert "--local-llm-base requires an argument" in capsys.readouterr().err

    def test_main_dispatch_passes_flag_through(self) -> None:
        with patch("holon_coherence.cli.run_agent", return_value=0) as mock_run_agent, pytest.raises(SystemExit):
            main(["pi", "--local-llm-base", "localhost:8081", "-p", "hi"])
        assert mock_run_agent.call_args.kwargs["local_llm_base"] == "localhost:8081"

    def test_invalid_endpoint_fails_before_proxy_starts(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("holon_coherence.commands.agents.resolve_agent_binary", return_value="/bin/pi"),
            patch("holon_coherence.commands.agents.ensure_proxy_running") as mock_ensure,
        ):
            code = run_agent("pi", [], local_llm_base="localhost:notaport")
        assert code == 1
        mock_ensure.assert_not_called()
        assert "--local-llm-base" in capsys.readouterr().err

    def test_route_is_passed_to_container_and_pruned_from_no_proxy(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv("NO_PROXY", raising=False)
        monkeypatch.delenv("no_proxy", raising=False)
        monkeypatch.delenv("HOLON_PROXY_PORT", raising=False)
        with (
            patch("holon_coherence.commands.agents.resolve_agent_binary", return_value="/bin/pi"),
            patch("holon_coherence.commands.start.detect_host_addresses", return_value=self.HOST_IPS),
            patch("holon_coherence.commands.agents.ensure_proxy_running", return_value=False) as mock_ensure,
            patch("holon_coherence.commands.agents.probe_host_local_reachable", return_value=(True, "")),
            patch("holon_coherence.commands.agents.build_agent_env", return_value={}) as mock_env,
            patch("holon_coherence.commands.agents.execute_interactive_process", return_value=0),
        ):
            assert run_agent("pi", [], local_llm_base="localhost:8081") == 0

        spec = decode_targets(mock_ensure.call_args.kwargs["host_local_spec"])
        assert {target.host for target in spec} == {"localhost", "127.0.0.1", "::1", *self.HOST_IPS}
        assert {target.port for target in spec} == {8081}

        dropped = set(mock_env.call_args.kwargs["drop_no_proxy"])
        assert {"localhost", "127.0.0.1", "::1"} <= dropped
        assert "github.com" not in dropped
        assert "169.254.169.254" not in dropped
        assert "intercepted" in capsys.readouterr().out

    def test_unreachable_host_keeps_the_bypass(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Pruning a working direct route into a broken proxied one is worse than bypassing."""
        monkeypatch.delenv("NO_PROXY", raising=False)
        monkeypatch.delenv("no_proxy", raising=False)
        monkeypatch.delenv("HOLON_PROXY_PORT", raising=False)
        with (
            patch("holon_coherence.commands.agents.resolve_agent_binary", return_value="/bin/pi"),
            patch("holon_coherence.commands.start.detect_host_addresses", return_value=self.HOST_IPS),
            patch("holon_coherence.commands.agents.ensure_proxy_running", return_value=False),
            patch(
                "holon_coherence.commands.agents.probe_host_local_reachable",
                return_value=(False, "Connection refused"),
            ),
            patch("holon_coherence.commands.agents.build_agent_env", return_value={}) as mock_env,
            patch("holon_coherence.commands.agents.execute_interactive_process", return_value=0),
        ):
            assert run_agent("pi", [], local_llm_base="localhost:8081") == 0

        assert mock_env.call_args.kwargs["drop_no_proxy"] == ()
        captured = capsys.readouterr()
        assert "Keeping NO_PROXY as-is" in captured.err
        assert "NOT intercepted" in captured.err

    def test_host_ip_declaration_leaves_loopback_bypass_alone(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv("NO_PROXY", raising=False)
        monkeypatch.delenv("no_proxy", raising=False)
        monkeypatch.delenv("HOLON_PROXY_PORT", raising=False)
        with (
            patch("holon_coherence.commands.agents.resolve_agent_binary", return_value="/bin/pi"),
            patch("holon_coherence.commands.start.detect_host_addresses", return_value=self.HOST_IPS),
            patch("holon_coherence.commands.agents.ensure_proxy_running", return_value=False),
            patch("holon_coherence.commands.agents.probe_host_local_reachable", return_value=(True, "")),
            patch("holon_coherence.commands.agents.build_agent_env", return_value={}) as mock_env,
            patch("holon_coherence.commands.agents.execute_interactive_process", return_value=0),
        ):
            run_agent("pi", [], local_llm_base="192.168.2.13:8081")

        assert mock_env.call_args.kwargs["drop_no_proxy"] == ()
        assert "already intercepted" in capsys.readouterr().out

    def test_wildcard_no_proxy_is_refused_not_rewritten(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("NO_PROXY", "*")
        monkeypatch.delenv("HOLON_PROXY_PORT", raising=False)
        with (
            patch("holon_coherence.commands.agents.resolve_agent_binary", return_value="/bin/pi"),
            patch("holon_coherence.commands.start.detect_host_addresses", return_value=self.HOST_IPS),
            patch("holon_coherence.commands.agents.ensure_proxy_running", return_value=False),
            patch("holon_coherence.commands.agents.probe_host_local_reachable", return_value=(True, "")),
            patch("holon_coherence.commands.agents.build_agent_env", return_value={}) as mock_env,
            patch("holon_coherence.commands.agents.execute_interactive_process", return_value=0),
        ):
            run_agent("pi", [], local_llm_base="localhost:8081")

        assert mock_env.call_args.kwargs["drop_no_proxy"] == ()
        assert "refusing to rewrite" in capsys.readouterr().err

    def test_unreachable_lan_ip_reports_warning_not_success(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When reaching a LAN IP fails, report failure even if it wasn't in NO_PROXY."""
        monkeypatch.delenv("NO_PROXY", raising=False)
        monkeypatch.delenv("no_proxy", raising=False)
        monkeypatch.delenv("HOLON_PROXY_PORT", raising=False)
        with (
            patch("holon_coherence.commands.agents.resolve_agent_binary", return_value="/bin/pi"),
            patch("holon_coherence.commands.start.detect_host_addresses", return_value=self.HOST_IPS),
            patch("holon_coherence.commands.agents.ensure_proxy_running", return_value=False),
            patch("holon_coherence.commands.agents.probe_host_local_reachable", return_value=(False, "exit code 3")),
            patch("holon_coherence.commands.agents.build_agent_env", return_value={}) as mock_env,
            patch("holon_coherence.commands.agents.execute_interactive_process", return_value=0),
        ):
            run_agent("pi", [], local_llm_base="192.168.2.13:8081")

        assert mock_env.call_args.kwargs["drop_no_proxy"] == ()
        captured = capsys.readouterr()
        assert "Container cannot reach 192.168.2.13:8081" in captured.err
        assert "traffic will still be sent to the proxy" in captured.err
        assert "already intercepted" not in captured.out

    def test_local_llm_base_port_collision_with_proxy_port_fails(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("HOLON_PROXY_PORT", "8080")
        with (
            patch("holon_coherence.commands.agents.resolve_agent_binary", return_value="/bin/pi"),
            patch("holon_coherence.commands.start.detect_host_addresses", return_value=self.HOST_IPS),
        ):
            exit_code = run_agent("pi", [], local_llm_base="localhost:8080", port=8080)
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "cannot be the same as proxy port" in captured.err

    def test_portless_local_llm_base_skips_reachability_probe(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv("NO_PROXY", raising=False)
        monkeypatch.delenv("no_proxy", raising=False)
        monkeypatch.delenv("HOLON_PROXY_PORT", raising=False)
        with (
            patch("holon_coherence.commands.agents.resolve_agent_binary", return_value="/bin/pi"),
            patch("holon_coherence.commands.start.detect_host_addresses", return_value=self.HOST_IPS),
            patch("holon_coherence.commands.agents.ensure_proxy_running", return_value=False),
            patch("holon_coherence.commands.agents.probe_host_local_reachable") as mock_probe,
            patch("holon_coherence.commands.agents.build_agent_env", return_value={}) as mock_env,
            patch("holon_coherence.commands.agents.execute_interactive_process", return_value=0),
        ):
            run_agent("pi", [], local_llm_base="localhost")

        mock_probe.assert_not_called()
        captured = capsys.readouterr()
        assert "without a port skips the container reachability preflight" in captured.err
        assert "localhost" in mock_env.call_args.kwargs["drop_no_proxy"]

    def test_local_llm_base_fallback_from_env_var(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("HOLON_LOCAL_LLM_BASE", "localhost:8081")
        monkeypatch.delenv("NO_PROXY", raising=False)
        monkeypatch.delenv("no_proxy", raising=False)
        monkeypatch.delenv("HOLON_PROXY_PORT", raising=False)
        with (
            patch("holon_coherence.commands.agents.resolve_agent_binary", return_value="/bin/pi"),
            patch("holon_coherence.commands.start.detect_host_addresses", return_value=self.HOST_IPS),
            patch("holon_coherence.commands.agents.ensure_proxy_running", return_value=False) as mock_ensure,
            patch("holon_coherence.commands.agents.probe_host_local_reachable", return_value=(True, "")),
            patch("holon_coherence.commands.agents.build_agent_env", return_value={}),
            patch("holon_coherence.commands.agents.execute_interactive_process", return_value=0),
        ):
            run_agent("pi", [])

        assert "localhost:8081" in mock_ensure.call_args.kwargs["host_local_spec"]

    def test_start_command_supports_local_llm_base_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with (
            patch("holon_coherence.commands.start.is_in_container", return_value=False),
            patch("holon_coherence.commands.start.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.commands.start.is_port_in_use", return_value=False),
            patch("holon_coherence.commands.start.ensure_docker_image"),
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch("subprocess.run") as mock_subproc,
        ):
            main(["start", "--local-llm-base", "localhost:11434", "-d"])

        cmd = mock_subproc.call_args_list[-1][0][0]
        assert any("HOLON_HOST_LOCAL_HOSTS=" in arg and "localhost:11434" in arg for arg in cmd)
        assert any("HOLON_PROXY_PORT=8080" in arg for arg in cmd)

    def test_start_command_rejects_matching_proxy_and_local_llm_port(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(["start", "--port", "8080", "--local-llm-base", "localhost:8080"])
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error: --local-llm-base port (8080) cannot be the same as proxy port (8080)." in captured.err

    def test_start_command_does_not_mutate_host_os_environ(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(HOST_LOCAL_ENV_VAR, raising=False)
        with (
            patch("holon_coherence.commands.start.is_in_container", return_value=False),
            patch("holon_coherence.commands.start.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.commands.start.ensure_docker_image"),
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch("subprocess.run"),
        ):
            main(["start", "--local-llm-base", "localhost:11434", "-d"])
        assert HOST_LOCAL_ENV_VAR not in os.environ
