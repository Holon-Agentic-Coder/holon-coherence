"""Unit tests for runner command, proxy environment preparation, and interactive process execution."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from holon_coherence.commands.runner import (
    NO_PROXY_HOSTS,
    build_proxy_env,
    execute_interactive_process,
    handle,
    handle_run,
    merge_no_proxy_values,
    register,
)


class TestBuildProxyEnv:
    """Tests for build_proxy_env and NO_PROXY resolution."""

    def test_build_proxy_env_sets_all_proxy_vars_and_node_extra_ca_certs(self) -> None:
        with (
            patch("os.path.exists", return_value=True),
            patch("holon_coherence.commands.runner.get_or_create_merged_ca_bundle", return_value="/path/merged.crt"),
        ):
            env = build_proxy_env("http://127.0.0.1:8888")
            assert env["HTTP_PROXY"] == "http://127.0.0.1:8888"
            assert env["HTTPS_PROXY"] == "http://127.0.0.1:8888"
            assert env["ALL_PROXY"] == "http://127.0.0.1:8888"
            assert env["http_proxy"] == "http://127.0.0.1:8888"
            assert env["https_proxy"] == "http://127.0.0.1:8888"
            assert env["all_proxy"] == "http://127.0.0.1:8888"
            assert env["NO_PROXY"] == NO_PROXY_HOSTS
            assert env["no_proxy"] == NO_PROXY_HOSTS
            assert env["SSL_CERT_FILE"] == "/path/merged.crt"
            assert env["REQUESTS_CA_BUNDLE"] == "/path/merged.crt"
            assert env["CURL_CA_BUNDLE"] == "/path/merged.crt"
            assert env["NODE_EXTRA_CA_CERTS"] == "/path/merged.crt"
            assert env["GIT_SSL_CAINFO"] == "/path/merged.crt"

    def test_build_proxy_env_custom_ca_path_and_alt_fallback(self) -> None:
        def fake_exists(path: str) -> bool:
            return path == "/custom/dir/holon-root-ca.crt"

        with (
            patch("os.path.exists", side_effect=fake_exists),
            patch(
                "holon_coherence.commands.runner.get_or_create_merged_ca_bundle", return_value="/alt/merged.crt"
            ) as mock_merge,
        ):
            env = build_proxy_env("http://127.0.0.1:8888", "/custom/dir/mitmproxy-ca-cert.pem")
            assert env["NODE_EXTRA_CA_CERTS"] == "/alt/merged.crt"
            mock_merge.assert_called_once_with("/custom/dir/holon-root-ca.crt")

    def test_build_proxy_env_default_ca_fallback(self) -> None:
        expected_root_ca = os.path.expanduser("~/.holon/certs/holon-root-ca.crt")

        def fake_exists(path: str) -> bool:
            return path == expected_root_ca

        with (
            patch("os.path.exists", side_effect=fake_exists),
            patch(
                "holon_coherence.commands.runner.get_or_create_merged_ca_bundle", return_value="/root/merged.crt"
            ) as mock_merge,
        ):
            env = build_proxy_env("http://127.0.0.1:8888")
            assert env["NODE_EXTRA_CA_CERTS"] == "/root/merged.crt"
            mock_merge.assert_called_once_with(expected_root_ca)

    def test_build_proxy_env_missing_ca_warning(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("os.path.exists", return_value=False):
            env = build_proxy_env("http://127.0.0.1:8888", "/nonexistent/ca.pem")
            assert "SSL_CERT_FILE" not in env
            assert "NODE_EXTRA_CA_CERTS" not in env
            assert "GIT_SSL_CAINFO" not in env
            captured = capsys.readouterr()
            assert "Warning: CA certificate not found at '/nonexistent/ca.pem'" in captured.err

    def test_build_proxy_env_holon_ca_cert_env_var(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        ca_cert = tmp_path / "custom-ca.pem"
        ca_cert.write_text("custom cert")
        monkeypatch.setenv("HOLON_CA_CERT", str(ca_cert))

        with patch(
            "holon_coherence.commands.runner.get_or_create_merged_ca_bundle", return_value="/merged/custom.crt"
        ) as mock_merge:
            env = build_proxy_env("http://127.0.0.1:8888")
            mock_merge.assert_called_once_with(str(ca_cert))
            assert env["NODE_EXTRA_CA_CERTS"] == "/merged/custom.crt"

    def test_no_proxy_aggregates_upper_and_lower_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NO_PROXY", "internal.corp.com,shared.host")
        monkeypatch.setenv("no_proxy", "local.domain,shared.host")
        env = build_proxy_env("http://127.0.0.1:8888")
        entries = env["NO_PROXY"].split(",")
        assert "internal.corp.com" in entries
        assert "local.domain" in entries
        assert "shared.host" in entries
        assert entries.count("shared.host") == 1
        assert env["no_proxy"] == env["NO_PROXY"]


class TestExecuteInteractiveProcess:
    """Tests for child process exit code propagation, stdio passthrough, and signal handling."""

    def test_exit_code_propagation_success(self) -> None:
        mock_proc = MagicMock()
        mock_proc.poll.side_effect = [None, 0]
        mock_proc.returncode = 0

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            code = execute_interactive_process(["test-cmd"], {"ENV": "val"})
            assert code == 0
            call_kwargs = mock_popen.call_args[1]
            assert call_kwargs["stdout"] is sys.stdout
            assert call_kwargs["stderr"] is sys.stderr
            assert call_kwargs["env"] == {"ENV": "val"}

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

    def test_execute_interactive_process_os_error_returns_126(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("subprocess.Popen", side_effect=PermissionError("Permission denied")):
            code = execute_interactive_process(["/usr/local/bin/nonexecutable"], {})
            assert code == 126
            captured = capsys.readouterr()
            assert "Error: Failed to execute '/usr/local/bin/nonexecutable': Permission denied" in captured.err


class TestRunnerRegistrationAndDispatch:
    """Tests for run subparser registration and argument handling."""

    def test_register_and_defaults(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)

        args = parser.parse_args(["run", "--", "echo", "hello"])
        assert args.command == "run"
        assert args.proxy_url == "http://127.0.0.1:8080"
        assert args.cmd == ["--", "echo", "hello"]
        assert getattr(args, "handler") == handle

    def test_handle_run_delegation(self) -> None:
        args = argparse.Namespace(cmd=["echo", "hi"], proxy_url="http://127.0.0.1:8080", ca_cert="ca.pem")
        with (
            patch("holon_coherence.commands.runner.build_proxy_env", return_value={"HTTP_PROXY": "http://127.0.0.1:8080"}),
            patch("holon_coherence.commands.runner.execute_interactive_process", return_value=0) as mock_exec,
        ):
            code = handle(args)
            assert code == 0
            mock_exec.assert_called_once()
            assert mock_exec.call_args[0][0] == ["echo", "hi"]
