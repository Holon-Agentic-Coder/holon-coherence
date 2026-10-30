"""Unit tests for runner command, proxy environment preparation, and interactive process execution."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from holon_coherence.commands.agents import build_agent_env
from holon_coherence.commands.ca import CA_ENV_VARS, find_system_ca_bundle, get_or_create_merged_ca_bundle
from holon_coherence.commands.runner import (
    NO_PROXY_HOSTS,
    build_proxy_env,
    execute_interactive_process,
    handle,
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
        assert args.handler == handle

    def test_handle_run_delegation(self) -> None:
        args = argparse.Namespace(cmd=["echo", "hi"], proxy_url="http://127.0.0.1:8080", ca_cert="ca.pem")
        with (
            patch(
                "holon_coherence.commands.runner.build_proxy_env", return_value={"HTTP_PROXY": "http://127.0.0.1:8080"}
            ),
            patch("holon_coherence.commands.runner.execute_interactive_process", return_value=0) as mock_exec,
        ):
            code = handle(args)
            assert code == 0
            mock_exec.assert_called_once()
            assert mock_exec.call_args[0][0] == ["echo", "hi"]


class TestProxyEnvironmentInjectionAndMergedCA:
    """Tests for proxy environment routing and merged CA bundle generation."""

    def test_proxy_routing_variables_injected(self) -> None:
        with (
            patch("os.path.exists", return_value=True),
            patch("holon_coherence.commands.runner.get_or_create_merged_ca_bundle", return_value="/mock/merged.crt"),
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
            assert env["NODE_EXTRA_CA_CERTS"] == "/mock/merged.crt"
            assert env["GIT_SSL_CAINFO"] == "/mock/merged.crt"

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
            assert "GIT_SSL_CAINFO" not in env
            captured = capsys.readouterr()
            assert "Warning: CA certificate not found" in captured.err
            assert "Ensure 'holon-coherence start' has been run at least once" in captured.err
            assert "initialize CA with 'holon-coherence init-ca'" in captured.err

    def test_inherited_ca_vars_are_cleared_when_bundle_is_missing(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A missing bundle must not leave an inherited CA path pointing at nothing.

        This is the case the assertion above only catches by accident: it passes on a clean CI
        machine because nothing set the variables, and fails on a developer or agent shell that
        exports them. Either way the child would be told to trust a bundle that does not exist,
        and then git, curl, requests or Node report a certificate error instead of the stale
        environment an earlier setup left behind.
        """
        for var in CA_ENV_VARS:
            monkeypatch.setenv(var, "/nonexistent/stale-bundle.crt")

        with patch("os.path.exists", return_value=False):
            env = build_agent_env("claude", port=9090)

        for var in CA_ENV_VARS:
            assert var not in env, f"{var} still points at a bundle that was reported missing"
        assert "Warning: CA certificate not found" in capsys.readouterr().err

    def test_resolved_bundle_overrides_inherited_ca_vars(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """When a bundle does resolve, it must win over whatever the shell already exported."""
        ca = tmp_path / "mitmproxy-ca-cert.pem"
        ca.write_text("-----BEGIN CERTIFICATE-----\n")
        merged = tmp_path / "holon-merged-ca-bundle.crt"
        monkeypatch.setenv("HOLON_CA_CERT", str(ca))
        for var in CA_ENV_VARS:
            monkeypatch.setenv(var, "/nonexistent/stale-bundle.crt")
        monkeypatch.setattr("holon_coherence.commands.runner.get_or_create_merged_ca_bundle", lambda _p: str(merged))

        env = build_agent_env("claude", port=9090)

        for var in CA_ENV_VARS:
            assert env[var] == str(merged), f"{var} kept the inherited path instead of the resolved bundle"

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
                "holon_coherence.commands.runner.get_or_create_merged_ca_bundle",
                return_value="/alt/merged.crt",
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
                "holon_coherence.commands.runner.get_or_create_merged_ca_bundle",
                return_value="/root/merged.crt",
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
        """HOLON_CA_CERT env var is consulted before falling back to default path."""
        ca_cert = tmp_path / "custom-ca.pem"
        ca_cert.write_text("custom cert")
        monkeypatch.setenv("HOLON_CA_CERT", str(ca_cert))
        monkeypatch.delenv("HOLON_AGENT_KEY", raising=False)

        with patch(
            "holon_coherence.commands.runner.get_or_create_merged_ca_bundle", return_value="/merged/custom.crt"
        ) as mock_merge:
            env = build_proxy_env("http://127.0.0.1:8888")
            mock_merge.assert_called_once_with(str(ca_cert))
            assert env["NODE_EXTRA_CA_CERTS"] == "/merged/custom.crt"

    def test_build_proxy_env_holon_ca_cert_env_var_not_found_falls_back(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If HOLON_CA_CERT points to a non-existent file, build_proxy_env falls back to default path."""
        monkeypatch.setenv("HOLON_CA_CERT", "/nonexistent/env-ca.pem")
        default_ca = os.path.expanduser("~/.holon/proxy-ca/mitmproxy-ca-cert.pem")

        def fake_exists(path: str) -> bool:
            return path == default_ca

        with (
            patch("os.path.exists", side_effect=fake_exists),
            patch(
                "holon_coherence.commands.runner.get_or_create_merged_ca_bundle", return_value="/merged/default.crt"
            ) as mock_merge,
        ):
            env = build_proxy_env("http://127.0.0.1:8888")
            mock_merge.assert_called_once_with(default_ca)
            assert env["NODE_EXTRA_CA_CERTS"] == "/merged/default.crt"

    def test_merged_ca_bundle_generation(self, tmp_path: Path) -> None:
        holon_ca = tmp_path / "mitmproxy-ca-cert.pem"
        holon_ca.write_text("-----BEGIN CERTIFICATE-----\nHOLON_ROOT_CA\n-----END CERTIFICATE-----")

        sys_ca = tmp_path / "system-ca.pem"
        sys_ca.write_text("-----BEGIN CERTIFICATE-----\nSYSTEM_ROOT_CA\n-----END CERTIFICATE-----")

        with patch("holon_coherence.commands.ca.find_system_ca_bundle", return_value=str(sys_ca)):
            merged_path = get_or_create_merged_ca_bundle(str(holon_ca))
            assert os.path.isfile(merged_path)
            with open(merged_path, encoding="utf-8") as f:
                content = f.read()
            assert "SYSTEM_ROOT_CA" in content
            assert "HOLON_ROOT_CA" in content

    def test_merged_ca_bundle_relative_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        holon_ca = tmp_path / "mitmproxy-ca-cert.pem"
        holon_ca.write_text("-----BEGIN CERTIFICATE-----\nHOLON_ROOT_CA\n-----END CERTIFICATE-----")

        sys_ca = tmp_path / "system-ca.pem"
        sys_ca.write_text("-----BEGIN CERTIFICATE-----\nSYSTEM_ROOT_CA\n-----END CERTIFICATE-----")

        monkeypatch.chdir(tmp_path)
        with patch("holon_coherence.commands.ca.find_system_ca_bundle", return_value=str(sys_ca)):
            merged_path = get_or_create_merged_ca_bundle("mitmproxy-ca-cert.pem")
            assert os.path.isabs(merged_path)
            assert os.path.isfile(merged_path)
            assert os.path.basename(merged_path) == "holon-merged-ca-bundle.crt"
            with open(merged_path, encoding="utf-8") as f:
                content = f.read()
            assert "SYSTEM_ROOT_CA" in content
            assert "HOLON_ROOT_CA" in content

    def test_merged_ca_bundle_mtime_caching(self, tmp_path: Path) -> None:
        holon_ca = tmp_path / "mitmproxy-ca-cert.pem"
        holon_ca.write_text("-----BEGIN CERTIFICATE-----\nHOLON_ROOT_CA\n-----END CERTIFICATE-----")

        sys_ca = tmp_path / "system-ca.pem"
        sys_ca.write_text("-----BEGIN CERTIFICATE-----\nSYSTEM_ROOT_CA\n-----END CERTIFICATE-----")

        merged_path = tmp_path / "holon-merged-ca-bundle.crt"
        merged_path.write_text("CACHED_CONTENT")

        t0 = 1000000.0
        os.utime(holon_ca, (t0, t0))
        os.utime(sys_ca, (t0, t0))
        os.utime(merged_path, (t0 + 100, t0 + 100))

        with patch("holon_coherence.commands.ca.find_system_ca_bundle", return_value=str(sys_ca)):
            result = get_or_create_merged_ca_bundle(str(holon_ca))
            assert result == str(merged_path)
            assert merged_path.read_text() == "CACHED_CONTENT"

        # When source ca_cert is newer than merged bundle, it should regenerate
        os.utime(holon_ca, (t0 + 200, t0 + 200))
        with patch("holon_coherence.commands.ca.find_system_ca_bundle", return_value=str(sys_ca)):
            result = get_or_create_merged_ca_bundle(str(holon_ca))
            assert result == str(merged_path)
            content = merged_path.read_text()
            assert "SYSTEM_ROOT_CA" in content
            assert "CACHED_CONTENT" not in content

    def test_find_system_ca_bundle_env_vars(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cert_file = tmp_path / "custom-cert.pem"
        cert_file.write_text("custom")
        monkeypatch.setenv("SSL_CERT_FILE", str(cert_file))
        assert find_system_ca_bundle() == str(cert_file)

        monkeypatch.delenv("SSL_CERT_FILE", raising=False)
        req_cert = tmp_path / "requests-cert.pem"
        req_cert.write_text("requests")
        monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(req_cert))
        assert find_system_ca_bundle() == str(req_cert)

        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
        curl_cert = tmp_path / "curl-cert.pem"
        curl_cert.write_text("curl")
        monkeypatch.setenv("CURL_CA_BUNDLE", str(curl_cert))
        assert find_system_ca_bundle() == str(curl_cert)

    def test_find_system_ca_bundle_env_var_returns_abspath(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """find_system_ca_bundle normalizes env var paths to absolute paths."""
        cert_file = tmp_path / "custom-cert.pem"
        cert_file.write_text("custom")
        monkeypatch.setenv("SSL_CERT_FILE", str(cert_file))
        result = find_system_ca_bundle()
        assert result is not None
        assert os.path.isabs(result), f"Expected abspath, got: {result}"

    def test_find_system_ca_bundle_ssl_paths(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SSL_CERT_FILE", raising=False)
        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
        monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
        ssl_ca = tmp_path / "ssl-ca.pem"
        ssl_ca.write_text("ssl")

        mock_paths = MagicMock(cafile=str(ssl_ca))
        with patch("ssl.get_default_verify_paths", return_value=mock_paths):
            assert find_system_ca_bundle() == str(ssl_ca)

    def test_find_system_ca_bundle_ignores_merged_bundle(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        merged_file = tmp_path / "holon-merged-ca-bundle.crt"
        merged_file.write_text("merged")
        real_sys_ca = tmp_path / "sys-ca.crt"
        real_sys_ca.write_text("sys")

        monkeypatch.setenv("SSL_CERT_FILE", str(merged_file))
        monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(real_sys_ca))
        assert find_system_ca_bundle() == str(real_sys_ca)

    def test_find_system_ca_bundle_ignores_unmerged_holon_certificates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mitm_ca = tmp_path / "mitmproxy-ca-cert.pem"
        mitm_ca.write_text("mitm")
        root_ca = tmp_path / "holon-root-ca.crt"
        root_ca.write_text("root")
        real_sys_ca = tmp_path / "sys-ca.crt"
        real_sys_ca.write_text("sys")

        monkeypatch.setenv("SSL_CERT_FILE", str(mitm_ca))
        monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(real_sys_ca))
        assert find_system_ca_bundle() == str(real_sys_ca)

        monkeypatch.setenv("SSL_CERT_FILE", str(root_ca))
        assert find_system_ca_bundle() == str(real_sys_ca)

    def test_find_system_ca_bundle_ssl_paths_ignores_merged_bundle(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SSL_CERT_FILE", raising=False)
        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
        monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
        merged_file = tmp_path / "holon-merged-ca-bundle.crt"
        merged_file.write_text("merged")
        fallback_ca = tmp_path / "fallback-ca.pem"
        fallback_ca.write_text("fallback")

        mock_paths = MagicMock(cafile=str(merged_file))
        with (
            patch("ssl.get_default_verify_paths", return_value=mock_paths),
            patch("certifi.where", return_value=str(fallback_ca)),
        ):
            assert find_system_ca_bundle() == str(fallback_ca)

    def test_merged_ca_bundle_duplicate_cert_guard(self, tmp_path: Path) -> None:
        holon_ca = tmp_path / "mitmproxy-ca-cert.pem"
        holon_ca.write_text("-----BEGIN CERTIFICATE-----\nHOLON_ROOT_CA\n-----END CERTIFICATE-----")

        sys_ca = tmp_path / "system-ca.pem"
        sys_ca.write_text(
            "-----BEGIN CERTIFICATE-----\nSYSTEM_ROOT_CA\n-----END CERTIFICATE-----\n\n"
            "-----BEGIN CERTIFICATE-----\nHOLON_ROOT_CA\n-----END CERTIFICATE-----"
        )

        with patch("holon_coherence.commands.ca.find_system_ca_bundle", return_value=str(sys_ca)):
            merged_path = get_or_create_merged_ca_bundle(str(holon_ca))
            with open(merged_path, encoding="utf-8") as f:
                content = f.read()
            assert content.count("HOLON_ROOT_CA") == 1

    def test_no_proxy_deduplication(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NO_PROXY", "127.0.0.1,api.github.com,internal.corp.com,127.0.0.1")
        env = build_agent_env("claude", port=9090)
        entries = env["NO_PROXY"].split(",")
        assert len(entries) == len(set(entries))
        assert "internal.corp.com" in entries
        assert "127.0.0.1" in entries

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


class TestChildProcessExecutionAndExitCodes:
    """Tests for child process exit code propagation, stdio passthrough, and signal handling."""

    def test_exit_code_propagation_success(self) -> None:
        mock_proc = MagicMock()
        mock_proc.poll.side_effect = [None, 0]
        mock_proc.returncode = 0

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            code = execute_interactive_process(["test-cmd"], {"ENV": "val"})
            assert code == 0
            # stdin arg is sys.stdin when fileno() succeeds; use ANY to be resilient
            # to CI/test environments where stdin may be a pseudofile
            call_kwargs = mock_popen.call_args[1]
            assert call_kwargs["stdout"] is sys.stdout
            assert call_kwargs["stderr"] is sys.stderr
            assert call_kwargs["env"] == {"ENV": "val"}

    def test_execute_interactive_process_pseudofile_stdin_uses_pipe(self) -> None:
        """When sys.stdin is a pseudofile (no fileno), Popen falls back to subprocess.PIPE."""
        import io

        mock_proc = MagicMock()
        mock_proc.poll.side_effect = [None, 0]
        mock_proc.returncode = 0
        pseudo_stdin = io.StringIO("fake stdin")  # StringIO has no real fileno()

        with (
            patch("subprocess.Popen", return_value=mock_proc) as mock_popen,
            patch("sys.stdin", pseudo_stdin),
        ):
            code = execute_interactive_process(["test-cmd"], {})
            assert code == 0
            call_kwargs = mock_popen.call_args[1]
            assert call_kwargs["stdin"] is subprocess.PIPE

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

    def test_execute_interactive_process_sigint_suppressed_in_tty(self) -> None:
        mock_proc = MagicMock()
        mock_proc.poll.side_effect = [None, 0]
        mock_proc.returncode = 0

        signal_calls: list[tuple[int, Any]] = []

        def mock_signal(sig: int, handler: Any) -> Any:
            signal_calls.append((sig, handler))
            return MagicMock()

        with (
            patch("subprocess.Popen", return_value=mock_proc),
            patch("sys.stdin.isatty", return_value=True),
            patch("signal.signal", side_effect=mock_signal),
        ):
            code = execute_interactive_process(["test-cmd"], {})
            assert code == 0
            assert (signal.SIGINT, signal.SIG_IGN) in signal_calls
            mock_proc.send_signal.assert_not_called()

    def test_execute_interactive_process_sigint_forwarded_when_not_tty(self) -> None:
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.returncode = 0

        captured_handler: dict[int, Any] = {}

        def mock_signal(sig: int, handler: Any) -> Any:
            captured_handler[sig] = handler
            return MagicMock()

        def fake_wait() -> int:
            if signal.SIGINT in captured_handler:
                captured_handler[signal.SIGINT](signal.SIGINT, None)
            mock_proc.poll.return_value = 0
            return 0

        mock_proc.wait.side_effect = fake_wait

        with (
            patch("subprocess.Popen", return_value=mock_proc),
            patch("sys.stdin.isatty", return_value=False),
            patch("signal.signal", side_effect=mock_signal),
        ):
            code = execute_interactive_process(["test-cmd"], {})
            assert code == 0
            mock_proc.send_signal.assert_called_with(signal.SIGINT)

    def test_execute_interactive_process_sighup_forwarded_when_available(self) -> None:
        if not hasattr(signal, "SIGHUP"):
            pytest.skip("SIGHUP not available on this platform")

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.returncode = 0

        captured_handler: dict[int, Any] = {}

        def mock_signal(sig: int, handler: Any) -> Any:
            captured_handler[sig] = handler
            return MagicMock()

        def fake_wait() -> int:
            if signal.SIGHUP in captured_handler:
                captured_handler[signal.SIGHUP](signal.SIGHUP, None)
            mock_proc.poll.return_value = 0
            return 0

        mock_proc.wait.side_effect = fake_wait

        with (
            patch("subprocess.Popen", return_value=mock_proc),
            patch("signal.signal", side_effect=mock_signal),
        ):
            code = execute_interactive_process(["test-cmd"], {})
            assert code == 0
            mock_proc.send_signal.assert_called_with(signal.SIGHUP)

    def test_signal_forwarding_suppresses_lookup_and_os_errors(self) -> None:
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.returncode = 0
        mock_proc.send_signal.side_effect = OSError("Process not found")

        captured_handler: dict[int, Any] = {}

        def mock_signal(sig: int, handler: Any) -> Any:
            captured_handler[sig] = handler
            return MagicMock()

        def fake_wait() -> int:
            if signal.SIGINT in captured_handler:
                captured_handler[signal.SIGINT](signal.SIGINT, None)
            mock_proc.poll.return_value = 0
            return 0

        mock_proc.wait.side_effect = fake_wait

        with (
            patch("subprocess.Popen", return_value=mock_proc),
            patch("sys.stdin.isatty", return_value=False),
            patch("signal.signal", side_effect=mock_signal),
        ):
            code = execute_interactive_process(["test-cmd"], {})
            assert code == 0
            mock_proc.send_signal.assert_called_with(signal.SIGINT)

    def test_execute_interactive_process_os_error_returns_126(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("subprocess.Popen", side_effect=PermissionError("Permission denied")):
            code = execute_interactive_process(["/usr/local/bin/nonexecutable"], {})
            assert code == 126
            captured = capsys.readouterr()
            assert "Error: Failed to execute '/usr/local/bin/nonexecutable': Permission denied" in captured.err
