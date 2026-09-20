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
    DEFAULT_PROXY_PORT,
    DOCKER_BUILD_TIMEOUT_SECONDS,
    NO_PROXY_HOSTS,
    SUPPORTED_AGENTS,
    build_agent_env,
    build_proxy_env,
    check_docker_daemon,
    ensure_docker_image,
    ensure_proxy_running,
    execute_interactive_process,
    extract_runner_flags,
    find_system_ca_bundle,
    get_or_create_merged_ca_bundle,
    is_container_bound_to_port,
    is_container_running,
    main,
    resolve_agent_binary,
    run_agent,
    stop_proxy_container,
    wait_for_proxy_ready,
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
            if agent in ("agy", "antigravity"):
                assert "GEMINI_API_KEY" not in env or env["GEMINI_API_KEY"] != "secret-test-key-123"
            elif agent == "claude":
                assert "ANTHROPIC_API_KEY" not in env or env["ANTHROPIC_API_KEY"] != "secret-test-key-123"
            elif agent == "codex":
                assert "OPENAI_API_KEY" not in env or env["OPENAI_API_KEY"] != "secret-test-key-123"
            elif agent == "opencode":
                assert "OPENCODE_API_KEY" not in env or env["OPENCODE_API_KEY"] != "secret-test-key-123"
            elif agent == "pi":
                assert "PI_API_KEY" not in env or env["PI_API_KEY"] != "secret-test-key-123"


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

    def test_build_proxy_env_sets_all_proxy_vars_and_node_extra_ca_certs(self) -> None:
        with (
            patch("os.path.exists", return_value=True),
            patch("holon_coherence.cli.get_or_create_merged_ca_bundle", return_value="/path/merged.crt"),
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
            patch("holon_coherence.cli.get_or_create_merged_ca_bundle", return_value="/alt/merged.crt") as mock_merge,
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
            patch("holon_coherence.cli.get_or_create_merged_ca_bundle", return_value="/root/merged.crt") as mock_merge,
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
            "holon_coherence.cli.get_or_create_merged_ca_bundle", return_value="/merged/custom.crt"
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
                "holon_coherence.cli.get_or_create_merged_ca_bundle", return_value="/merged/default.crt"
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

        with patch("holon_coherence.cli.find_system_ca_bundle", return_value=str(sys_ca)):
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
        with patch("holon_coherence.cli.find_system_ca_bundle", return_value=str(sys_ca)):
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

        with patch("holon_coherence.cli.find_system_ca_bundle", return_value=str(sys_ca)):
            result = get_or_create_merged_ca_bundle(str(holon_ca))
            assert result == str(merged_path)
            assert merged_path.read_text() == "CACHED_CONTENT"

        # When source ca_cert is newer than merged bundle, it should regenerate
        os.utime(holon_ca, (t0 + 200, t0 + 200))
        with patch("holon_coherence.cli.find_system_ca_bundle", return_value=str(sys_ca)):
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

        with patch("holon_coherence.cli.find_system_ca_bundle", return_value=str(sys_ca)):
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


class TestDockerDiagnosticsAndPortConflicts:
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
            patch("subprocess.run", side_effect=timeout_err) as mock_run,
        ):
            ok, err = check_docker_daemon()
            assert ok is False
            assert "timed out" in err
            mock_run.assert_called_once_with(
                ["docker", "info"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5.0,
            )

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
            patch("holon_coherence.cli.is_container_bound_to_port", return_value=True),
            patch("subprocess.run") as mock_run,
        ):
            started = ensure_proxy_running(port=8080)
            assert started is False
            # Should return immediately without docker run
            mock_run.assert_not_called()

    def test_ensure_proxy_running_launches_new_container_returns_true(self) -> None:
        with (
            patch("holon_coherence.cli.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.cli.is_port_in_use", return_value=False),
            patch("holon_coherence.cli.is_container_running", return_value=False),
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch(
                "subprocess.run",
                side_effect=[
                    MagicMock(returncode=0),  # inspect image
                    MagicMock(returncode=0),  # rm -f
                    MagicMock(returncode=0),  # docker run
                ],
            ) as mock_run,
            patch("holon_coherence.cli.wait_for_proxy_ready", return_value=True),
        ):
            started = ensure_proxy_running(port=8080)
            assert started is True
            docker_cmd = mock_run.call_args_list[2][0][0]
            assert "--init" in docker_cmd

    def test_container_already_running_on_different_port_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("holon_coherence.cli.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.cli.is_port_in_use", return_value=False),
            patch("holon_coherence.cli.is_container_running", return_value=True),
            patch("holon_coherence.cli.is_container_bound_to_port", return_value=False),
            pytest.raises(SystemExit) as exc_info,
        ):
            ensure_proxy_running(port=9090)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error: A holon-coherence proxy container is already running on a different port." in captured.err
        assert "Stop it first using 'holon-coherence stop' before launching on port 9090." in captured.err

    def test_container_unresponsive_diagnostic(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("holon_coherence.cli.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.cli.is_port_in_use", return_value=False),
            patch("holon_coherence.cli.is_container_running", return_value=True),
            patch("holon_coherence.cli.is_container_bound_to_port", return_value=True),
            patch("holon_coherence.cli.wait_for_proxy_ready", return_value=False) as mock_wait,
            pytest.raises(SystemExit) as exc_info,
        ):
            ensure_proxy_running(port=9090)
        assert exc_info.value.code == 1
        mock_wait.assert_called_once_with(9090)
        captured = capsys.readouterr()
        assert (
            "Error: A holon-coherence proxy container is running for port 9090, but is not responding." in captured.err
        )
        assert "Please restart it using 'holon-coherence stop' and retry." in captured.err

    def test_ensure_proxy_running_bound_container_becomes_ready(self) -> None:
        with (
            patch("holon_coherence.cli.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.cli.is_port_in_use", return_value=False),
            patch("holon_coherence.cli.is_container_running", return_value=True),
            patch("holon_coherence.cli.is_container_bound_to_port", return_value=True),
            patch("holon_coherence.cli.wait_for_proxy_ready", return_value=True) as mock_wait,
        ):
            result = ensure_proxy_running(port=9090)
        assert result is False
        mock_wait.assert_called_once_with(9090)

    def test_port_conflict_when_container_running_on_different_port(self) -> None:
        with (
            patch("holon_coherence.cli.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.cli.is_port_in_use", return_value=True),
            patch("holon_coherence.cli.is_container_running", return_value=True),
            patch("holon_coherence.cli.is_container_bound_to_port", return_value=False),
            pytest.raises(SystemExit) as exc_info,
        ):
            ensure_proxy_running(port=8080)
        assert exc_info.value.code == 1

    def test_is_container_bound_to_port_direct_match(self) -> None:
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_res.stdout = "127.0.0.1:8080\n"
        with patch("subprocess.run", return_value=mock_res):
            assert is_container_bound_to_port(8080) is True
            assert is_container_bound_to_port(9090) is False

    def test_is_container_bound_to_port_fallback(self) -> None:
        failed_res = MagicMock(returncode=1, stdout="")
        fallback_res = MagicMock(returncode=0, stdout="8080/tcp -> 127.0.0.1:9090\n")
        with patch("subprocess.run", side_effect=[failed_res, fallback_res]):
            assert is_container_bound_to_port(9090) is True

    def test_is_container_bound_to_port_failure(self) -> None:
        failed_res = MagicMock(returncode=1, stdout="")
        with patch("subprocess.run", return_value=failed_res):
            assert is_container_bound_to_port(8080) is False

    def test_is_container_running_timeout_returns_false(self) -> None:
        """is_container_running returns False when docker inspect times out."""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["docker"], timeout=5.0)):
            assert is_container_running() is False

    def test_is_container_running_oserror_returns_false(self) -> None:
        """is_container_running returns False when docker binary is missing (OSError)."""
        with patch("subprocess.run", side_effect=OSError("docker not found")):
            assert is_container_running() is False

    def test_is_container_bound_to_port_primary_timeout_returns_false(self) -> None:
        """is_container_bound_to_port returns False if primary docker port call times out."""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["docker", "port"], timeout=5.0)):
            assert is_container_bound_to_port(8080) is False

    def test_is_container_bound_to_port_fallback_timeout_returns_false(self) -> None:
        """is_container_bound_to_port returns False if fallback docker port call times out."""
        failed_res = MagicMock(returncode=1, stdout="")
        with patch(
            "subprocess.run",
            side_effect=[failed_res, subprocess.TimeoutExpired(cmd=["docker", "port"], timeout=5.0)],
        ):
            assert is_container_bound_to_port(8080) is False

    def test_is_container_bound_to_port_oserror_returns_false(self) -> None:
        """is_container_bound_to_port returns False when OSError raised on primary call."""
        with patch("subprocess.run", side_effect=OSError("no docker")):
            assert is_container_bound_to_port(8080) is False

    def test_ensure_proxy_running_timeout_combines_logs(self, capsys: pytest.CaptureFixture[str]) -> None:
        logs_res = MagicMock(returncode=0, stdout="out msg\n", stderr="err traceback\n")
        with (
            patch("holon_coherence.cli.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.cli.is_port_in_use", return_value=False),
            patch("holon_coherence.cli.is_container_running", return_value=False),
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch(
                "subprocess.run",
                side_effect=[
                    MagicMock(returncode=0),  # inspect image
                    MagicMock(returncode=0),  # rm -f
                    MagicMock(returncode=0),  # docker run
                    logs_res,  # docker logs
                ],
            ),
            patch("holon_coherence.cli.wait_for_proxy_ready", return_value=False),
            patch("holon_coherence.cli.stop_proxy_container") as mock_stop,
            pytest.raises(SystemExit) as exc_info,
        ):
            ensure_proxy_running(port=8080)
        assert exc_info.value.code == 1
        mock_stop.assert_called_once()
        captured = capsys.readouterr()
        assert "out msg" in captured.err
        assert "err traceback" in captured.err

    def test_ensure_proxy_running_build_failure(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("holon_coherence.cli.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.cli.is_port_in_use", return_value=False),
            patch("holon_coherence.cli.is_container_running", return_value=False),
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch(
                "subprocess.run",
                side_effect=[
                    MagicMock(returncode=1),  # inspect image fails
                    MagicMock(returncode=1),  # docker build fails
                ],
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            ensure_proxy_running(port=8080)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Failed to build Docker image" in captured.err

    def test_ensure_proxy_running_ghcr_pull_failure(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("holon_coherence.cli.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.cli.is_port_in_use", return_value=False),
            patch("holon_coherence.cli.is_container_running", return_value=False),
            patch("os.makedirs"),
            patch("os.path.exists", side_effect=lambda p: not str(p).endswith("Dockerfile")),
            patch(
                "subprocess.run",
                side_effect=[
                    MagicMock(returncode=1),  # inspect image fails
                    MagicMock(returncode=1),  # docker pull image fails
                    MagicMock(returncode=1),  # docker pull ghcr fails
                ],
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            ensure_proxy_running(port=8080)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Could not find or pull Docker image" in captured.err


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
            patch("holon_coherence.cli.ensure_proxy_running", return_value=True) as mock_ensure,
            patch("holon_coherence.cli.execute_interactive_process", return_value=0),
            patch("holon_coherence.cli.stop_proxy_container") as mock_stop,
        ):
            code = run_agent("agy", ["-p", "test"], ephemeral=True)
            assert code == 0
            mock_ensure.assert_called_once()
            mock_stop.assert_called_once()

    def test_ephemeral_mode_does_not_tear_down_reused_proxy(self) -> None:
        with (
            patch("holon_coherence.cli.resolve_agent_binary", return_value="/bin/dummy-agent"),
            patch("holon_coherence.cli.ensure_proxy_running", return_value=False) as mock_ensure,
            patch("holon_coherence.cli.execute_interactive_process", return_value=0),
            patch("holon_coherence.cli.stop_proxy_container") as mock_stop,
        ):
            code = run_agent("agy", ["-p", "test"], ephemeral=True)
            assert code == 0
            mock_ensure.assert_called_once()
            mock_stop.assert_not_called()

    def test_run_agent_missing_binary_returns_exit_code_1(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("holon_coherence.cli.resolve_agent_binary", return_value=None):
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

    @pytest.mark.parametrize("invalid_port", ["0", "70000", "abc"])
    def test_run_agent_invalid_env_port_fallback(
        self, invalid_port: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("HOLON_PROXY_PORT", invalid_port)
        with (
            patch("holon_coherence.cli.resolve_agent_binary", return_value="/bin/dummy-agent"),
            patch("holon_coherence.cli.ensure_proxy_running") as mock_ensure,
            patch("holon_coherence.cli.execute_interactive_process", return_value=0),
        ):
            run_agent("codex", [])
            mock_ensure.assert_called_once_with(port=DEFAULT_PROXY_PORT)
            captured = capsys.readouterr()
            expected_warning = f"⚠️  Invalid HOLON_PROXY_PORT '{invalid_port}', falling back to {DEFAULT_PROXY_PORT}."
            assert expected_warning in captured.err

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

    def test_run_agent_parameterless_exits_one(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["run-agent"])
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "usage: holon-coherence run-agent" in captured.out

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
            patch("holon_coherence.cli.execute_interactive_process", side_effect=fake_execute),
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
            patch("holon_coherence.cli.get_or_create_merged_ca_bundle", return_value="/mock/merged.crt"),
            patch("holon_coherence.cli.execute_interactive_process", side_effect=fake_execute),
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
            patch("holon_coherence.cli.execute_interactive_process", return_value=42) as mock_exec,
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
            patch("holon_coherence.cli.is_in_container", return_value=False),
            patch("holon_coherence.cli.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.cli.ensure_docker_image"),
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
            patch("holon_coherence.cli.is_in_container", return_value=False),
            patch("holon_coherence.cli.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.cli.ensure_docker_image"),
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
            patch("holon_coherence.cli.is_in_container", return_value=False),
            patch("holon_coherence.cli.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.cli.ensure_docker_image"),
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch("subprocess.run") as mock_run,
        ):
            main(["start"])
            assert mock_run.call_count == 2
            docker_cmd = mock_run.call_args_list[1][0][0]
            assert "--init" in docker_cmd
            assert "--rm" in docker_cmd


class TestWaitForProxyReady:
    """Tests for wait_for_proxy_ready polling and fail-fast container exit handling."""

    def test_wait_for_proxy_ready_success(self) -> None:
        with (
            patch("holon_coherence.cli.is_container_running", return_value=True),
            patch("holon_coherence.cli.is_port_in_use", return_value=True),
        ):
            assert wait_for_proxy_ready(8080) is True

    def test_wait_for_proxy_ready_fail_fast_when_container_exits(self) -> None:
        with (
            patch("holon_coherence.cli.is_container_running", return_value=False),
            patch("holon_coherence.cli.is_port_in_use", return_value=False),
        ):
            # Should immediately return False without polling up to timeout
            assert wait_for_proxy_ready(8080, timeout=15.0) is False

    def test_wait_for_proxy_ready_timeout(self) -> None:
        with (
            patch("holon_coherence.cli.is_container_running", return_value=True),
            patch("holon_coherence.cli.is_port_in_use", return_value=False),
            patch("time.sleep"),
        ):
            assert wait_for_proxy_ready(8080, timeout=0.001) is False


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
