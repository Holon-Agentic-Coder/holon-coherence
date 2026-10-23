"""Unit and integration tests for holon-coherence CLI and coding agent runners."""

from __future__ import annotations

import email.message
import json
import os
import signal
import stat
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from holon_coherence.cli import (
    CA_ENV_VARS,
    CONTAINER_NAME,
    DEFAULT_PROXY_PORT,
    DOCKER_BUILD_TIMEOUT_SECONDS,
    NO_PROXY_HOSTS,
    SUPPORTED_AGENTS,
    ExposedEndpoints,
    build_agent_env,
    build_proxy_env,
    check_docker_daemon,
    container_host_local_spec,
    docker_host_alias_args,
    ensure_docker_image,
    ensure_proxy_running,
    execute_interactive_process,
    extract_runner_flags,
    find_system_ca_bundle,
    format_endpoint_rows,
    get_active_web_token,
    get_container_web_token,
    get_or_create_merged_ca_bundle,
    handle_metrics,
    host_local_container_args,
    host_local_covered,
    is_container_bound_to_port,
    is_container_running,
    main,
    merge_no_proxy_values,
    plan_local_llm_route,
    probe_host_local_reachable,
    report_local_llm_route,
    resolve_agent_binary,
    resolve_web_password,
    run_agent,
    save_web_token,
    stop_proxy_container,
    wait_for_proxy_ready,
)
from holon_coherence.commands.metrics import _read_offline_metrics
from holon_coherence.host_local import HOST_LOCAL_ENV_VAR, decode_targets
from holon_coherence.mitm_addon import CumulativeMetrics


@pytest.fixture(autouse=True)
def _never_persist_real_web_token() -> Iterator[MagicMock]:
    """A ``start --web`` resolves an inspector token; keep it out of the real ~/.holon/web-token.

    ``HOLON_COHERENCE_WEB`` is cleared so a developer's shell opt-in cannot flip the headless default under test.
    """
    with (
        patch.dict(os.environ, {}, clear=False),
        patch("holon_coherence.cli.save_web_token") as mock_save,
    ):
        os.environ.pop("HOLON_COHERENCE_WEB", None)
        yield mock_save


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
        monkeypatch.setattr("holon_coherence.cli.get_or_create_merged_ca_bundle", lambda _p: str(merged))

        env = build_agent_env("claude", port=9090)

        for var in CA_ENV_VARS:
            assert env[var] == str(merged), f"{var} kept the inherited path instead of the resolved bundle"

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
        with patch("holon_coherence.cli.stop_proxy_container") as mock_stop:
            main(["stop"])
            mock_stop.assert_called_once_with("holon-coherence-proxy")

        with patch("holon_coherence.cli.stop_proxy_container") as mock_stop:
            main(["stop", "--name", "sandbox-custom"])
            mock_stop.assert_called_once_with("sandbox-custom")

    def test_status_and_logs_subcommand_dispatch_with_name(self) -> None:
        with patch("holon_coherence.cli.handle_status") as mock_status:
            main(["status", "--name", "sandbox-custom"])
            assert mock_status.call_count == 1
            assert mock_status.call_args[0][0].name == "sandbox-custom"

        with patch("holon_coherence.cli.handle_logs") as mock_logs:
            main(["logs", "--name", "sandbox-custom", "-f"])
            assert mock_logs.call_count == 1
            assert mock_logs.call_args[0][0].name == "sandbox-custom"
            assert mock_logs.call_args[0][0].follow is True

    def test_port_configuration_from_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_PROXY_PORT", "9999")
        with (
            patch("holon_coherence.cli.resolve_agent_binary", return_value="/bin/dummy-agent"),
            patch("holon_coherence.cli.ensure_proxy_running") as mock_ensure,
            patch("holon_coherence.cli.execute_interactive_process", return_value=0),
        ):
            run_agent("codex", [])
            mock_ensure.assert_called_once_with(port=9999, host_local_spec="")

    def test_port_flag_overrides_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_PROXY_PORT", "9999")
        with (
            patch("holon_coherence.cli.resolve_agent_binary", return_value="/bin/dummy-agent"),
            patch("holon_coherence.cli.ensure_proxy_running") as mock_ensure,
            patch("holon_coherence.cli.execute_interactive_process", return_value=0),
        ):
            run_agent("codex", [], port=7777)
            mock_ensure.assert_called_once_with(port=7777, host_local_spec="")

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
            patch("holon_coherence.cli.is_port_in_use", return_value=False),
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

        monkeypatch.setattr("holon_coherence.cli.is_in_container", lambda: True)
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
            patch("holon_coherence.cli.is_in_container", return_value=False),
            patch("holon_coherence.cli.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.cli.is_port_in_use", return_value=False),
            patch("holon_coherence.cli.save_web_token"),
            patch("holon_coherence.cli.ensure_docker_image"),
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
            patch("holon_coherence.cli.is_in_container", return_value=False),
            patch("holon_coherence.cli.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.cli.is_port_in_use", side_effect=fake_in_use),
            patch("holon_coherence.cli.ensure_docker_image"),
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
            patch("holon_coherence.cli.is_in_container", return_value=False),
            patch("holon_coherence.cli.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.cli.is_port_in_use", side_effect=fake_in_use),
            patch("holon_coherence.cli.save_web_token"),
            patch("holon_coherence.cli.ensure_docker_image"),
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
            patch("holon_coherence.cli.is_in_container", return_value=False),
            patch("holon_coherence.cli.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.cli.is_port_in_use", side_effect=fake_in_use),
            patch("holon_coherence.cli.save_web_token"),
            patch("holon_coherence.cli.ensure_docker_image"),
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
            patch("holon_coherence.cli.is_in_container", return_value=False),
            patch("holon_coherence.cli.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.cli.is_port_in_use", return_value=False),
            patch("holon_coherence.cli.save_web_token"),
            patch("holon_coherence.cli.ensure_docker_image"),
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
            patch("holon_coherence.cli.is_in_container", return_value=False),
            patch("holon_coherence.cli.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.cli.is_port_in_use", return_value=False),
            patch("holon_coherence.cli.ensure_docker_image"),
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

        monkeypatch.setattr("holon_coherence.cli.is_in_container", lambda: True)
        with (
            patch("holon_coherence.cli.save_web_token"),
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


class TestWaitForProxyReady:
    """Tests for wait_for_proxy_ready HTTP metrics polling and fail-fast container exit handling."""

    def test_wait_for_proxy_ready_immediate_success(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status = 200
        with (
            patch("holon_coherence.cli.is_container_running", return_value=True),
            patch("holon_coherence.commands.start._urlopen_no_proxy", return_value=mock_resp) as mock_urlopen,
            patch("time.sleep") as mock_sleep,
        ):
            assert wait_for_proxy_ready(8080) is True
            assert mock_urlopen.call_count == 1
            mock_sleep.assert_not_called()

    def test_wait_for_proxy_ready_retry_success(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status = 200
        side_effects = [
            urllib.error.URLError(ConnectionRefusedError("Connection refused")),
            urllib.error.URLError(ConnectionRefusedError("Connection refused")),
            mock_resp,
        ]
        with (
            patch("holon_coherence.cli.is_container_running", return_value=True),
            patch("holon_coherence.commands.start._urlopen_no_proxy", side_effect=side_effects) as mock_urlopen,
            patch("time.sleep") as mock_sleep,
        ):
            assert wait_for_proxy_ready(8080) is True
            assert mock_urlopen.call_count == 3
            assert mock_sleep.call_count == 2

    def test_wait_for_proxy_ready_fallback_endpoint_on_404(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status = 200
        http_404 = urllib.error.HTTPError(
            url="http://127.0.0.1:8080/holon/api/metrics",
            code=404,
            msg="Not Found",
            hdrs=email.message.Message(),
            fp=None,
        )
        with (
            patch("holon_coherence.cli.is_container_running", return_value=True),
            patch(
                "holon_coherence.commands.start._urlopen_no_proxy", side_effect=[http_404, mock_resp]
            ) as mock_urlopen,
            patch("time.sleep"),
        ):
            assert wait_for_proxy_ready(8080) is True
            assert mock_urlopen.call_count == 2
            first_url = mock_urlopen.call_args_list[0][0][0].full_url
            second_url = mock_urlopen.call_args_list[1][0][0].full_url
            assert first_url == "http://127.0.0.1:8080/holon/api/metrics"
            assert second_url == "http://127.0.0.1:8080/_holon/metrics"

    def test_wait_for_proxy_ready_fail_fast_when_container_exits(self) -> None:
        with (
            patch("holon_coherence.cli.is_container_running", side_effect=[True, False]),
            patch(
                "holon_coherence.commands.start._urlopen_no_proxy",
                side_effect=urllib.error.URLError(ConnectionRefusedError()),
            ),
            patch("time.sleep"),
        ):
            assert wait_for_proxy_ready(8080, timeout=15.0) is False

    def test_wait_for_proxy_ready_timeout(self) -> None:
        clock = [0.0]
        fake_time = MagicMock()
        fake_time.monotonic.side_effect = lambda: clock[0]
        fake_time.sleep.side_effect = lambda s: clock.__setitem__(0, clock[0] + 1.0)
        with (
            patch("holon_coherence.cli.is_container_running", return_value=True),
            patch(
                "holon_coherence.commands.start._urlopen_no_proxy",
                side_effect=urllib.error.URLError(ConnectionRefusedError()),
            ) as mock_urlopen,
            patch("holon_coherence.commands.start.time", fake_time),
        ):
            assert wait_for_proxy_ready(8080, timeout=3.0) is False
            assert mock_urlopen.call_count == 3
            assert fake_time.sleep.call_count == 3

    def test_wait_for_proxy_ready_non_404_http_error_retries_without_fallback(self) -> None:
        http_503 = urllib.error.HTTPError(
            url="http://127.0.0.1:8080/holon/api/metrics",
            code=503,
            msg="Service Unavailable",
            hdrs=email.message.Message(),
            fp=None,
        )
        mock_resp = MagicMock()
        mock_resp.status = 200
        with (
            patch("holon_coherence.cli.is_container_running", return_value=True),
            patch(
                "holon_coherence.commands.start._urlopen_no_proxy", side_effect=[http_503, mock_resp]
            ) as mock_urlopen,
            patch("time.sleep") as mock_sleep,
        ):
            assert wait_for_proxy_ready(8080) is True
            assert mock_urlopen.call_count == 2
            assert mock_urlopen.call_args_list[1][0][0].full_url == "http://127.0.0.1:8080/holon/api/metrics"
            assert mock_sleep.call_count == 1

    def test_wait_for_proxy_ready_ignores_env_proxy(self) -> None:
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_opener = MagicMock()
        mock_opener.open.return_value = mock_resp
        with (
            patch("holon_coherence.cli.is_container_running", return_value=True),
            patch("urllib.request.build_opener", return_value=mock_opener) as mock_build,
            patch("time.sleep"),
        ):
            assert wait_for_proxy_ready(8080) is True
        handler = mock_build.call_args[0][0]
        assert isinstance(handler, urllib.request.ProxyHandler)
        assert handler.proxies == {}

    @staticmethod
    def _stepping_clock(wall_step: float) -> tuple[MagicMock, list[float], list[float]]:
        """Fake ``time`` module whose wall clock jumps by ``wall_step`` on the first sleep.

        Both clocks advance 0.25s per poll, as real clocks would; only the wall clock is stepped.
        A quarter-second tick keeps the monotonic arithmetic exact in binary floating point.
        """
        wall = [1_000_000.0]
        mono = [0.0]
        fake_time = MagicMock()
        fake_time.time.side_effect = lambda: wall[0]
        fake_time.monotonic.side_effect = lambda: mono[0]

        def fake_sleep(_seconds: float) -> None:
            if fake_time.sleep.call_count == 1:
                wall[0] += wall_step
            wall[0] += 0.25
            mono[0] += 0.25

        fake_time.sleep.side_effect = fake_sleep
        return fake_time, wall, mono

    def test_wait_for_proxy_ready_backwards_wall_step_does_not_extend(self) -> None:
        fake_time, _wall, _mono = self._stepping_clock(-3600.0)
        with (
            patch("holon_coherence.cli.is_container_running", return_value=True),
            patch(
                "holon_coherence.commands.start._urlopen_no_proxy",
                side_effect=urllib.error.URLError(ConnectionRefusedError()),
            ) as mock_urlopen,
            patch("holon_coherence.commands.start.time", fake_time),
        ):
            assert wait_for_proxy_ready(8080, timeout=1.0) is False
        # 1.0s budget at 0.25s per poll: exactly four attempts, regardless of the wall-clock step.
        assert mock_urlopen.call_count == 4
        assert fake_time.time.call_count == 0

    def test_wait_for_proxy_ready_forwards_wall_step_does_not_short_circuit(self) -> None:
        fake_time, _wall, _mono = self._stepping_clock(+3600.0)
        with (
            patch("holon_coherence.cli.is_container_running", return_value=True),
            patch(
                "holon_coherence.commands.start._urlopen_no_proxy",
                side_effect=urllib.error.URLError(ConnectionRefusedError()),
            ) as mock_urlopen,
            patch("holon_coherence.commands.start.time", fake_time),
        ):
            assert wait_for_proxy_ready(8080, timeout=1.0) is False
        assert mock_urlopen.call_count == 4
        assert fake_time.time.call_count == 0

    def test_wait_for_proxy_ready_returns_on_first_200_despite_wall_steps(self) -> None:
        fake_time, wall, _mono = self._stepping_clock(+3600.0)
        mock_resp = MagicMock()
        mock_resp.status = 200
        refused = urllib.error.URLError(ConnectionRefusedError("Connection refused"))

        attempts = [0]

        def flaky_open(_req: urllib.request.Request, timeout: float) -> Any:
            # Step the wall clock backwards on every attempt as well.
            wall[0] -= 7200.0
            attempts[0] += 1
            if attempts[0] <= 2:
                raise refused
            return mock_resp

        with (
            patch("holon_coherence.cli.is_container_running", return_value=True),
            patch("holon_coherence.commands.start._urlopen_no_proxy", side_effect=flaky_open) as mock_urlopen,
            patch("holon_coherence.commands.start.time", fake_time),
        ):
            assert wait_for_proxy_ready(8080, timeout=15.0) is True
        assert mock_urlopen.call_count == 3
        assert fake_time.sleep.call_count == 2
        assert fake_time.time.call_count == 0


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
            patch("holon_coherence.cli.resolve_agent_binary", return_value="/bin/pi"),
            patch("holon_coherence.cli.ensure_proxy_running") as mock_ensure,
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
            patch("holon_coherence.cli.resolve_agent_binary", return_value="/bin/pi"),
            patch("holon_coherence.cli.detect_host_addresses", return_value=self.HOST_IPS),
            patch("holon_coherence.cli.ensure_proxy_running", return_value=False) as mock_ensure,
            patch("holon_coherence.cli.probe_host_local_reachable", return_value=(True, "")),
            patch("holon_coherence.cli.build_agent_env", return_value={}) as mock_env,
            patch("holon_coherence.cli.execute_interactive_process", return_value=0),
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
            patch("holon_coherence.cli.resolve_agent_binary", return_value="/bin/pi"),
            patch("holon_coherence.cli.detect_host_addresses", return_value=self.HOST_IPS),
            patch("holon_coherence.cli.ensure_proxy_running", return_value=False),
            patch(
                "holon_coherence.cli.probe_host_local_reachable",
                return_value=(False, "Connection refused"),
            ),
            patch("holon_coherence.cli.build_agent_env", return_value={}) as mock_env,
            patch("holon_coherence.cli.execute_interactive_process", return_value=0),
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
            patch("holon_coherence.cli.resolve_agent_binary", return_value="/bin/pi"),
            patch("holon_coherence.cli.detect_host_addresses", return_value=self.HOST_IPS),
            patch("holon_coherence.cli.ensure_proxy_running", return_value=False),
            patch("holon_coherence.cli.probe_host_local_reachable", return_value=(True, "")),
            patch("holon_coherence.cli.build_agent_env", return_value={}) as mock_env,
            patch("holon_coherence.cli.execute_interactive_process", return_value=0),
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
            patch("holon_coherence.cli.resolve_agent_binary", return_value="/bin/pi"),
            patch("holon_coherence.cli.detect_host_addresses", return_value=self.HOST_IPS),
            patch("holon_coherence.cli.ensure_proxy_running", return_value=False),
            patch("holon_coherence.cli.probe_host_local_reachable", return_value=(True, "")),
            patch("holon_coherence.cli.build_agent_env", return_value={}) as mock_env,
            patch("holon_coherence.cli.execute_interactive_process", return_value=0),
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
            patch("holon_coherence.cli.resolve_agent_binary", return_value="/bin/pi"),
            patch("holon_coherence.cli.detect_host_addresses", return_value=self.HOST_IPS),
            patch("holon_coherence.cli.ensure_proxy_running", return_value=False),
            patch("holon_coherence.cli.probe_host_local_reachable", return_value=(False, "exit code 3")),
            patch("holon_coherence.cli.build_agent_env", return_value={}) as mock_env,
            patch("holon_coherence.cli.execute_interactive_process", return_value=0),
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
            patch("holon_coherence.cli.resolve_agent_binary", return_value="/bin/pi"),
            patch("holon_coherence.cli.detect_host_addresses", return_value=self.HOST_IPS),
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
            patch("holon_coherence.cli.resolve_agent_binary", return_value="/bin/pi"),
            patch("holon_coherence.cli.detect_host_addresses", return_value=self.HOST_IPS),
            patch("holon_coherence.cli.ensure_proxy_running", return_value=False),
            patch("holon_coherence.cli.probe_host_local_reachable") as mock_probe,
            patch("holon_coherence.cli.build_agent_env", return_value={}) as mock_env,
            patch("holon_coherence.cli.execute_interactive_process", return_value=0),
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
            patch("holon_coherence.cli.resolve_agent_binary", return_value="/bin/pi"),
            patch("holon_coherence.cli.detect_host_addresses", return_value=self.HOST_IPS),
            patch("holon_coherence.cli.ensure_proxy_running", return_value=False) as mock_ensure,
            patch("holon_coherence.cli.probe_host_local_reachable", return_value=(True, "")),
            patch("holon_coherence.cli.build_agent_env", return_value={}),
            patch("holon_coherence.cli.execute_interactive_process", return_value=0),
        ):
            run_agent("pi", [])

        assert "localhost:8081" in mock_ensure.call_args.kwargs["host_local_spec"]

    def test_start_command_supports_local_llm_base_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with (
            patch("holon_coherence.cli.is_in_container", return_value=False),
            patch("holon_coherence.cli.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.cli.is_port_in_use", return_value=False),
            patch("holon_coherence.cli.ensure_docker_image"),
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
            patch("holon_coherence.cli.is_in_container", return_value=False),
            patch("holon_coherence.cli.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.cli.ensure_docker_image"),
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch("subprocess.run"),
        ):
            main(["start", "--local-llm-base", "localhost:11434", "-d"])
        assert HOST_LOCAL_ENV_VAR not in os.environ


class TestHostLocalContainerWiring:
    """The container must be able to resolve the host and know which authorities to reroute."""

    def test_add_host_flag_shape(self) -> None:
        assert docker_host_alias_args() == ["--add-host", "host.docker.internal:host-gateway"]

    def test_allow_list_env_flag_shape(self) -> None:
        assert host_local_container_args("localhost:8081") == ["-e", f"{HOST_LOCAL_ENV_VAR}=localhost:8081"]
        assert host_local_container_args("") == []

    def test_docker_run_includes_add_host_and_allow_list(self) -> None:
        with (
            patch("holon_coherence.cli.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.cli.is_port_in_use", return_value=False),
            patch("holon_coherence.cli.is_container_running", return_value=False),
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch(
                "subprocess.run",
                side_effect=[
                    MagicMock(returncode=0),  # image inspect
                    MagicMock(returncode=0),  # rm -f
                    MagicMock(returncode=0),  # docker run
                ],
            ) as mock_run,
            patch("holon_coherence.cli.wait_for_proxy_ready", return_value=True),
        ):
            assert ensure_proxy_running(port=8080, host_local_spec="localhost:8081") is True

        docker_cmd = mock_run.call_args_list[2][0][0]
        assert "--add-host" in docker_cmd
        assert "host.docker.internal:host-gateway" in docker_cmd
        assert "-e" in docker_cmd
        assert f"{HOST_LOCAL_ENV_VAR}=localhost:8081" in docker_cmd

    def test_start_command_also_adds_host_alias(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(HOST_LOCAL_ENV_VAR, raising=False)
        with (
            patch("holon_coherence.cli.is_in_container", return_value=False),
            patch("holon_coherence.cli.check_docker_daemon", return_value=(True, "")),
            patch("os.makedirs"),
            patch("holon_coherence.cli.generate_root_ca", return_value=("/tmp/ca.pem", "/tmp/ca.key")),
            patch("holon_coherence.cli.ensure_docker_image"),
            patch("subprocess.run") as mock_run,
        ):
            main(["start", "-d"])

        docker_cmd = mock_run.call_args_list[-1][0][0]
        assert docker_cmd[:2] == ["docker", "run"]
        assert "host.docker.internal:host-gateway" in docker_cmd

    def test_start_command_forwards_host_local_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(HOST_LOCAL_ENV_VAR, "localhost:11434")
        monkeypatch.delenv("HOLON_PROXY_PORT", raising=False)
        with (
            patch("holon_coherence.cli.is_in_container", return_value=False),
            patch("holon_coherence.cli.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.cli.is_port_in_use", return_value=False),
            patch("os.makedirs"),
            patch("holon_coherence.cli.generate_root_ca", return_value=("/tmp/ca.pem", "/tmp/ca.key")),
            patch("holon_coherence.cli.ensure_docker_image"),
            patch("subprocess.run") as mock_run,
        ):
            main(["start", "-d"])

        docker_cmd = mock_run.call_args_list[-1][0][0]
        assert f"{HOST_LOCAL_ENV_VAR}=localhost:11434" in docker_cmd
        # The container only knows its own listen port, so the published port has to be handed over
        # for the addon to refuse rewriting a client straight back into the proxy.
        assert "HOLON_PROXY_PORT=8080" in docker_cmd

    def test_running_container_env_is_read_back(self) -> None:
        stdout = f"HOLON_IN_CONTAINER=1\n{HOST_LOCAL_ENV_VAR}=localhost:8081,127.0.0.1:8081\nPATH=/usr/bin\n"
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout=stdout, stderr="")):
            assert container_host_local_spec() == "localhost:8081,127.0.0.1:8081"

    def test_running_container_env_missing_is_empty(self) -> None:
        with patch("subprocess.run", side_effect=OSError("docker missing")):
            assert container_host_local_spec() == ""

    def test_coverage_checks(self) -> None:
        assert host_local_covered("", "anything:1") is True
        assert host_local_covered("localhost:8081", "localhost:8081,127.0.0.1:8081") is True
        assert host_local_covered("localhost:8081", "localhost:11434") is False
        assert host_local_covered("localhost:8081", "") is False
        assert host_local_covered("localhost:8081", "localhost") is True

    def test_unfit_running_container_is_recreated(self) -> None:
        with (
            patch("holon_coherence.cli.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.cli.is_port_in_use", side_effect=[True, False, False]),
            patch("holon_coherence.cli.is_container_running", return_value=True),
            patch("holon_coherence.cli.is_container_bound_to_port", return_value=True),
            patch("holon_coherence.cli.container_host_local_spec", return_value="localhost:11434"),
            patch("holon_coherence.cli.stop_proxy_container") as mock_stop,
            patch("holon_coherence.cli.detect_host_addresses", return_value=()),
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch(
                "subprocess.run",
                side_effect=[
                    MagicMock(returncode=0),  # image inspect
                    MagicMock(returncode=0),  # rm -f
                    MagicMock(returncode=0),  # docker run
                ],
            ) as mock_subproc,
            patch("holon_coherence.cli.wait_for_proxy_ready", return_value=True),
        ):
            assert ensure_proxy_running(port=8080, host_local_spec="localhost:8081") is False
        mock_stop.assert_called_once()
        docker_run_cmd = mock_subproc.call_args_list[2][0][0]
        assert "HOLON_HOST_LOCAL_HOSTS=localhost:11434,localhost:8081" in docker_run_cmd
        assert "HOLON_PROXY_PORT=8080" in docker_run_cmd

    def test_merged_no_proxy_keeps_defaults_and_caller_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NO_PROXY", "internal.example")
        merged = merge_no_proxy_values()
        assert "localhost" in merged
        assert "internal.example" in merged

    def test_build_proxy_env_drops_pruned_entries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NO_PROXY", raising=False)
        monkeypatch.delenv("no_proxy", raising=False)
        env = build_proxy_env("http://127.0.0.1:8080", drop_no_proxy=("localhost", "127.0.0.1", "::1"))
        entries = {entry.strip() for entry in env["NO_PROXY"].split(",") if entry.strip()}
        assert {"localhost", "127.0.0.1", "::1"}.isdisjoint(entries)
        assert {"github.com", "169.254.169.254"} <= entries
        assert env["NO_PROXY"] == env["no_proxy"]

    def test_unfit_running_container_fails_if_port_cannot_be_freed(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("holon_coherence.cli.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.cli.is_port_in_use", return_value=True),
            patch("holon_coherence.cli.is_container_running", return_value=True),
            patch("holon_coherence.cli.is_container_bound_to_port", return_value=True),
            patch("holon_coherence.cli.container_host_local_spec", return_value="localhost:11434"),
            patch("holon_coherence.cli.stop_proxy_container") as mock_stop,
            patch("time.sleep"),
            pytest.raises(SystemExit) as exc_info,
        ):
            ensure_proxy_running(port=8080, host_local_spec="localhost:8081")

        assert exc_info.value.code == 1
        mock_stop.assert_called_once()
        captured = capsys.readouterr()
        assert "could not be freed after stopping container" in captured.err

    def test_build_agent_env_forwards_pruning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NO_PROXY", raising=False)
        monkeypatch.delenv("no_proxy", raising=False)
        env = build_agent_env("pi", 8080, drop_no_proxy=("localhost",))
        assert "localhost" not in {entry.strip() for entry in env["NO_PROXY"].split(",")}


class TestProbeHostLocalReachable:
    """Tests for probe_host_local_reachable() container execution and fallback."""

    def test_probe_python3_success(self) -> None:
        with patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            ok, detail = probe_host_local_reachable(8081)
            assert ok is True
            assert detail == ""
            cmd = mock_run.call_args[0][0]
            assert cmd[:4] == ["docker", "exec", CONTAINER_NAME, "python3"]

    def test_probe_python3_missing_falls_back_to_python(self) -> None:
        missing_proc = MagicMock(
            returncode=127,
            stderr='OCI runtime exec failed: exec: "python3": executable file not found in $PATH',
            stdout="",
        )
        success_proc = MagicMock(returncode=0, stderr="", stdout="")
        with patch("subprocess.run", side_effect=[missing_proc, success_proc]) as mock_run:
            ok, detail = probe_host_local_reachable(8081)
            assert ok is True
            assert detail == ""
            assert mock_run.call_count == 2
            assert mock_run.call_args_list[0][0][0][3] == "python3"
            assert mock_run.call_args_list[1][0][0][3] == "python"

    def test_probe_both_interpreters_missing(self) -> None:
        missing_proc = MagicMock(
            returncode=126,
            stderr='OCI runtime exec failed: unable to start container process: exec: "python": not found',
            stdout="",
        )
        with patch("subprocess.run", return_value=missing_proc) as mock_run:
            ok, detail = probe_host_local_reachable(8081)
            assert ok is False
            assert detail == "unreachable"
            assert mock_run.call_count == 2

    def test_probe_target_refused(self) -> None:
        fail_proc = MagicMock(
            returncode=1,
            stderr="Traceback (most recent call last):\nConnectionRefusedError: [Errno 111] Connection refused\n",
            stdout="",
        )
        with patch("subprocess.run", return_value=fail_proc) as mock_run:
            ok, detail = probe_host_local_reachable(8081)
            assert ok is False
            assert "ConnectionRefusedError" in detail
            mock_run.assert_called_once()

    def test_probe_timeout(self) -> None:
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="docker", timeout=15.0)):
            ok, detail = probe_host_local_reachable(8081)
            assert ok is False
            assert detail == "probe timed out"

    def test_probe_oserror(self) -> None:
        with patch("subprocess.run", side_effect=OSError("docker daemon not found")):
            ok, detail = probe_host_local_reachable(8081)
            assert ok is False
            assert "docker daemon not found" in detail

    def test_probe_parameterized_container_name(self) -> None:
        with patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            ok, _ = probe_host_local_reachable(8081, container_name="custom-container")
            assert ok is True
            assert mock_run.call_args[0][0][2] == "custom-container"

    def test_container_gateway_probe_filters_loopback_and_bracket_strips(self) -> None:
        from holon_coherence.cli import _CONTAINER_GATEWAY_PROBE

        assert "strip('[]')" in _CONTAINER_GATEWAY_PROBE
        assert "127." in _CONTAINER_GATEWAY_PROBE
        assert "::1" in _CONTAINER_GATEWAY_PROBE
        assert "fallback" in _CONTAINER_GATEWAY_PROBE
        assert "gateway name does not resolve" in _CONTAINER_GATEWAY_PROBE
        assert "no non-loopback gateway IP found" in _CONTAINER_GATEWAY_PROBE

    def test_container_gateway_probe_handles_gaierror(self) -> None:
        from holon_coherence.cli import _CONTAINER_GATEWAY_PROBE

        wrapper = (
            "import sys, unittest.mock as mock\n"
            "with mock.patch('socket.getaddrinfo', side_effect=OSError('mock DNS fail')):\n"
            f"    exec({_CONTAINER_GATEWAY_PROBE!r})\n"
        )
        res = subprocess.run([sys.executable, "-c", wrapper, "8081"], capture_output=True, text=True)
        assert res.returncode == 3
        assert "gateway name does not resolve" in res.stderr

    def test_container_gateway_probe_iterates_and_connects(self) -> None:
        from holon_coherence.cli import _CONTAINER_GATEWAY_PROBE

        wrapper = (
            "import sys, unittest.mock as mock, socket\n"
            "mock_infos = [\n"
            "    (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('192.168.65.1', 0)),\n"
            "    (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('192.168.65.2', 0)),\n"
            "]\n"
            "calls = []\n"
            "def mock_conn(addr, timeout=3):\n"
            "    assert timeout == 3\n"
            "    calls.append(addr)\n"
            "    if addr[0] == '192.168.65.1':\n"
            "        raise OSError('Connection refused')\n"
            "    return mock.MagicMock()\n"
            "with (\n"
            "    mock.patch('socket.getaddrinfo', return_value=mock_infos),\n"
            "    mock.patch('socket.create_connection', side_effect=mock_conn),\n"
            "):\n"
            f"    exec({_CONTAINER_GATEWAY_PROBE!r})\n"
        )
        res = subprocess.run([sys.executable, "-c", wrapper, "8081"], capture_output=True, text=True)
        assert res.returncode == 0


class TestPlanAndReportLocalLlmRoute:
    """Unit tests for plan_local_llm_route and report_local_llm_route."""

    @pytest.fixture(autouse=True)
    def _mock_host_addrs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("holon_coherence.cli.detect_host_addresses", lambda: ("192.168.2.13",))

    def test_plan_local_llm_route_valid_and_invalid(self) -> None:
        route = plan_local_llm_route("localhost:8081")
        assert route is not None
        assert route.target.canonical == "localhost:8081"
        assert route.target.port == 8081
        assert "localhost:8081" in route.container_env_value

        route_portless = plan_local_llm_route("localhost")
        assert route_portless is not None
        assert route_portless.target.canonical == "localhost"
        assert route_portless.target.port is None

        assert plan_local_llm_route("localhost:") is None
        assert plan_local_llm_route("localhost:notaport") is None
        assert plan_local_llm_route("://x") is None

    def test_report_local_llm_route_reachable_with_pruning(self, capsys: pytest.CaptureFixture[str]) -> None:
        route = plan_local_llm_route("localhost:8081")
        assert route is not None
        dropped = report_local_llm_route(route, reachable=True, detail="ok")
        assert len(dropped) > 0
        captured = capsys.readouterr()
        assert "Removing" in captured.out
        assert "is intercepted" in captured.out

    def test_report_local_llm_route_unreachable_with_pruning(self, capsys: pytest.CaptureFixture[str]) -> None:
        route = plan_local_llm_route("localhost:8081")
        assert route is not None
        dropped = report_local_llm_route(route, reachable=False, detail="connection refused")
        assert dropped == ()
        captured = capsys.readouterr()
        assert "Container cannot reach localhost:8081" in captured.err
        assert "Keeping NO_PROXY as-is" in captured.err
        assert "retained" in captured.err

    def test_report_local_llm_route_unreachable_without_pruning(self, capsys: pytest.CaptureFixture[str]) -> None:
        # 192.168.2.13:8081 is not in default NO_PROXY, so plan.remove is empty
        route = plan_local_llm_route("192.168.2.13:8081")
        assert route is not None
        dropped = report_local_llm_route(route, reachable=False, detail="gateway name does not resolve")
        assert dropped == ()
        captured = capsys.readouterr()
        assert "Container cannot reach 192.168.2.13:8081" in captured.err
        assert "retained" not in captured.err
        assert "already intercepted" not in captured.out

    def test_report_local_llm_route_reachable_without_pruning(self, capsys: pytest.CaptureFixture[str]) -> None:
        route = plan_local_llm_route("192.168.2.13:8081")
        assert route is not None
        dropped = report_local_llm_route(route, reachable=True, detail="ok")
        assert dropped == ()
        captured = capsys.readouterr()
        assert "already intercepted" in captured.out

    def test_report_local_llm_route_wildcard_blocked(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("NO_PROXY", "*")
        route = plan_local_llm_route("localhost:8081")
        assert route is not None
        dropped = report_local_llm_route(route, reachable=True, detail="ok")
        assert dropped == ()
        captured = capsys.readouterr()
        assert "NO_PROXY contains '*'" in captured.err


class TestWebTokenAndDashboardAuth:
    """Tests for web dashboard token management and password protection (Bean 0042)."""

    def test_web_token_resolution_and_generation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 1. Explicit CLI argument
        assert resolve_web_password("explicit-cli-pwd") == "explicit-cli-pwd"

        # 2. Environment variable fallback
        monkeypatch.setenv("HOLON_COHERENCE_WEB_PASSWORD", "env-secret-password")
        assert resolve_web_password(None) == "env-secret-password"

        # 3. Auto-generation fallback
        monkeypatch.delenv("HOLON_COHERENCE_WEB_PASSWORD", raising=False)
        auto_token = resolve_web_password(None)
        assert isinstance(auto_token, str)
        assert len(auto_token) >= 16

    def test_web_token_file_persistence_and_permissions(self, tmp_path: Path) -> None:
        target_path = tmp_path / "subdir" / "web-token"
        saved = save_web_token("super-secret-token", token_path=str(target_path))
        assert saved == str(target_path)
        assert target_path.read_text().strip() == "super-secret-token"

        # POSIX file permissions must be 0600
        mode = target_path.stat().st_mode
        assert (mode & 0o777) == (stat.S_IRUSR | stat.S_IWUSR)
        assert (mode & 0o077) == 0

        # Retrieval helper
        retrieved = get_active_web_token(token_path=str(target_path))
        assert retrieved == "super-secret-token"

    def test_get_active_web_token_edge_cases(self, tmp_path: Path) -> None:
        # Non-existent file
        assert get_active_web_token(token_path=str(tmp_path / "nonexistent")) is None

        # Empty or whitespace-only file
        empty_token = tmp_path / "empty"
        empty_token.write_text("   \n")
        assert get_active_web_token(token_path=str(empty_token)) is None

        # Unreadable file / OSError handling
        unreadable = tmp_path / "unreadable"
        unreadable.write_text("valid-token")
        with patch("builtins.open", side_effect=OSError("Disk error")):
            assert get_active_web_token(token_path=str(unreadable)) is None

    def test_start_web_command_forwards_web_password_in_container(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("holon_coherence.cli.is_in_container", lambda: True)
        launched: list[list[str]] = []

        def fake_run(cmd, *args, **kwargs):
            launched.append(list(cmd))
            return MagicMock(returncode=0)

        with (
            patch("holon_coherence.cli.save_web_token"),
            patch("subprocess.run", side_effect=fake_run),
        ):
            main(["start", "--port", "8080", "--web", "--web-password", "container-pwd"])

        assert len(launched) == 1
        cmd = launched[0]
        assert "--set" in cmd
        set_idx = cmd.index("--set") + 1
        assert cmd[set_idx] == "web_password=container-pwd"

    def test_start_web_command_forwards_web_password_on_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("holon_coherence.cli.is_in_container", lambda: False)
        with (
            patch("holon_coherence.cli.save_web_token"),
            patch("holon_coherence.cli.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.cli.ensure_docker_image"),
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch("subprocess.run") as mock_run,
        ):
            main(["start", "-d", "--web", "--web-password", "host-custom-pwd"])
            assert mock_run.call_count == 2
            docker_cmd = mock_run.call_args_list[1][0][0]
            assert "-e" in docker_cmd
            assert "HOLON_COHERENCE_WEB_PASSWORD=host-custom-pwd" in docker_cmd
            # Plaintext password must NOT be in container CLI tail arguments (SEC-01)
            tail_args = docker_cmd[docker_cmd.index("holon-coherence:latest") :]
            assert "--web-password" not in tail_args

    def test_status_command_displays_web_token(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("holon_coherence.cli.is_container_running", return_value=True),
            patch("holon_coherence.cli.get_container_mapped_port", side_effect=lambda _name, port: port),
            patch("holon_coherence.cli.get_container_web_token", return_value="active-session-tok"),
            patch("subprocess.run", return_value=MagicMock(returncode=0)),
            patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")),
        ):
            main(["status"])
            captured = capsys.readouterr()
            assert "mitmweb Req/Resp Inspector   : http://127.0.0.1:8081/?token=active-session-tok" in captured.out

    def test_status_command_when_down_displays_explicit_indicator(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("holon_coherence.cli.is_container_running", return_value=False),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value.returncode = 1
            main(["status"])
            captured = capsys.readouterr()
            assert "🔴 holon-coherence is down (not running)" in captured.out

    def test_status_command_when_docker_missing_does_not_crash(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("holon_coherence.cli.is_container_running", return_value=False),
            patch("subprocess.run", side_effect=FileNotFoundError("docker")),
        ):
            main(["status"])
            captured = capsys.readouterr()
            assert "🔴 holon-coherence is down (not running)" in captured.out

    def test_web_token_and_web_key_commands(self, capsys: pytest.CaptureFixture[str]) -> None:
        # Token exists: web-token
        with (
            patch("holon_coherence.cli.get_active_web_token", return_value="existing-key-999"),
            patch("holon_coherence.cli.is_container_running", return_value=False),
            pytest.raises(SystemExit) as exc,
        ):
            main(["web-token"])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "Active mitmweb inspector token: existing-key-999" in captured.out
        assert "mitmweb inspector: not running" in captured.out
        assert "?token=" not in captured.out

        # Token exists: web-key alias
        with (
            patch("holon_coherence.cli.get_active_web_token", return_value="existing-key-999"),
            patch("holon_coherence.cli.is_container_running", return_value=False),
            pytest.raises(SystemExit) as exc,
        ):
            main(["web-key"])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "Active mitmweb inspector token: existing-key-999" in captured.out
        assert "mitmweb inspector: not running" in captured.out
        assert "?token=" not in captured.out

        # Token missing
        with (
            patch("holon_coherence.cli.get_active_web_token", return_value=None),
            patch("holon_coherence.cli.is_container_running", return_value=False),
            pytest.raises(SystemExit) as exc,
        ):
            main(["web-token"])
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "No active mitmweb inspector token found" in captured.out


class TestCLIMetricsCommand:
    """Tests for holon-coherence metrics command and status integration (Bean 0043)."""

    @pytest.fixture(autouse=True)
    def _no_docker_queries(self) -> Iterator[None]:
        """Endpoint rows query Docker for the container's ports; these tests run with no container."""
        with patch("holon_coherence.cli.is_container_running", return_value=False):
            yield

    def test_handle_metrics_live_formatted(self, capsys: pytest.CaptureFixture[str]) -> None:
        mock_payload = json.dumps(
            {
                "total_turns": 5,
                "total_requests": 10,
                "cache_hits": 4,
                "cache_misses": 6,
                "cache_hit_rate": 0.4,
                "tool_calls_pruned": 12,
                "tokens_reduced": 350,
                "chars_saved": 1400,
                "avg_ttft_ms": 120.5,
                "avg_decode_throughput_tps": 45.2,
                "total_input_tokens": 1500,
                "total_output_tokens": 800,
                "total_cache_read_tokens": 600,
            }
        ).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = mock_payload
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            ret = handle_metrics(port=8080)
        assert ret == 0
        out = capsys.readouterr().out
        assert "HOLON COHERENCE OPTIMIZATION METRICS" in out
        assert "Tool Calls Saved / Pruned    : 12" in out
        assert "Tokens Reduced               : 350" in out
        assert "Cache Hit Rate               : 40.0%" in out
        assert "Average TTFT                 : 120.50 ms" in out
        assert "http://127.0.0.1:8080/holon/" in out

    def test_handle_metrics_live_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        payload = {"tool_calls_pruned": 8, "tokens_reduced": 200, "cache_hit_rate": 0.25}
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            ret = handle_metrics(port=8080, json_output=True)
        assert ret == 0
        data = json.loads(capsys.readouterr().out)
        assert data["tool_calls_pruned"] == 8
        assert data["tokens_reduced"] == 200

    def test_handle_metrics_offline_wire_log(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        jsonl = tmp_path / "transactions.jsonl"
        records = [
            {
                "turn_id": 1,
                "cache_action": "HIT",
                "delta": {"tool_outputs_omitted": 2, "chars_saved": 400},
                "response": {"usage": {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 100}},
                "timing": {"ttft_ms": 10.0},
            },
            {
                "turn_id": 2,
                "cache_action": "MISS",
                "delta": {"tool_outputs_omitted": 3, "chars_saved": 800},
                "response": {
                    "usage": {
                        "input_tokens": 200,
                        "output_tokens": 100,
                        "cache_read_input_tokens": 0,
                        "reasoning_tokens": None,
                    }
                },
                "timing": {"ttft_ms": 100.0, "total_ms": 1100.0},
            },
        ]
        with open(jsonl, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        monkeypatch.setenv("WIRE_LOG_DIR", str(tmp_path))
        with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
            ret = handle_metrics(json_output=True)
        assert ret == 0
        data = json.loads(capsys.readouterr().out)
        assert data["source"] == "offline_wire_log"
        assert data["tool_calls_pruned"] == 5
        assert data["tokens_reduced"] == 300
        assert data["cache_hits"] == 1
        assert data["total_requests"] == 2
        assert data["avg_decode_throughput_tps"] == 100.0
        assert data["total_reasoning_tokens"] == 0

    def test_handle_metrics_offline_fallback_holon_logs(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.delenv("WIRE_LOG_DIR", raising=False)
        fake_home = tmp_path / "home"
        holon_logs = fake_home / ".holon" / "logs"
        holon_logs.mkdir(parents=True)
        jsonl = holon_logs / "transactions.jsonl"
        record = {
            "turn_id": 1,
            "cache_action": "MISS",
            "delta": {"tool_outputs_omitted": 1, "chars_saved": 40},
            "response": {
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_read_input_tokens": 20,
                    "cache_creation_input_tokens": 10,
                    "reasoning_tokens": 5,
                }
            },
            "timing": {"ttft_ms": 200.0, "total_ms": 1200.0},
        }
        with open(jsonl, "w", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

        with (
            patch("os.path.expanduser", side_effect=lambda p: str(holon_logs) if "~/.holon/logs" in p else p),
            patch("urllib.request.urlopen", side_effect=OSError("connection refused")),
        ):
            ret = handle_metrics(json_output=True)
        assert ret == 0
        data = json.loads(capsys.readouterr().out)
        assert data["source"] == "offline_wire_log"
        assert data["avg_prefill_throughput_tps"] == 500.0  # 100 / 0.2s
        assert data["avg_tail_prefill_tps"] == 400.0  # 80 / 0.2s
        assert data["avg_decode_throughput_tps"] == 50.0  # 50 / 1.0s
        assert data["total_cache_creation_tokens"] == 10
        assert data["total_reasoning_tokens"] == 5

    def test_handle_metrics_prefill_and_kv_cache_terminal_output(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_payload = json.dumps(
            {
                "total_turns": 3,
                "total_requests": 5,
                "cache_hits": 2,
                "cache_misses": 3,
                "cache_hit_rate": 0.4,
                "provider_cache_hit_rate": 0.75,
                "tool_calls_pruned": 6,
                "tokens_reduced": 100,
                "chars_saved": 400,
                "avg_ttft_ms": 150.0,
                "avg_decode_throughput_tps": 60.0,
                "avg_prefill_throughput_tps": 650.0,
                "latest_prefill_tps": 700.0,
                "avg_tail_prefill_tps": 200.0,
                "total_input_tokens": 2000,
                "total_output_tokens": 500,
                "total_cache_read_tokens": 1500,
                "total_cache_creation_tokens": 250,
                "total_reasoning_tokens": 40,
            }
        ).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = mock_payload
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            ret = handle_metrics(port=8080)
        assert ret == 0
        out = capsys.readouterr().out
        assert "Prefill Throughput           : 650.00 tokens/sec" in out
        assert "Latest: 700.00 t/s" in out
        assert "Tail Prefill Throughput      : 200.00 tokens/sec" in out
        assert "Decode Throughput            : 60.00 tokens/sec" in out
        assert "Cache Hit Rate               : 40.0%" in out
        assert "75.0% KV hit" in out
        assert "Cache Write Tokens           : 250" in out
        assert "Reasoning Tokens             : 40" in out

    def test_metrics_cli_dispatch(self) -> None:
        with (
            patch("holon_coherence.cli.handle_metrics", return_value=0) as mock_handle,
            pytest.raises(SystemExit) as exc,
        ):
            main(["metrics", "--json", "--port", "9999", "--offline", "--name", "custom-proxy"])
        assert exc.value.code == 0
        assert mock_handle.call_count == 1
        args = mock_handle.call_args[0][0]
        assert args.json is True
        assert args.port == 9999
        assert args.offline is True
        assert args.name == "custom-proxy"


class TestLocalLlmRunnerFlagsAndEnvs:
    """Tests for --model and local LLM runner flags/environments (Bean 0051)."""

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
        # Bean 0051: sets AGY_GATEWAY_URL with non-loopback alias (NOT GOOGLE_GEMINI_BASE_URL)
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


class TestOfflineTelemetryThroughputBean0097:
    """Offline wire-log throughput arithmetic must mirror the live proxy (Bean 0097)."""

    @staticmethod
    def _write_records(tmp_path: Path, records: list[dict[str, Any]]) -> str:
        jsonl = tmp_path / "transactions.jsonl"
        with open(jsonl, "w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")
        return str(tmp_path)

    def test_legacy_non_streaming_window_below_floor_is_not_sampled(self, tmp_path: Path) -> None:
        """A 1.5ms ``total - ttft`` window is socket parse time, not 1,000,000 tokens/sec."""
        log_dir = self._write_records(
            tmp_path,
            [
                {
                    "turn_id": 1,
                    "cache_action": "MISS",
                    "delta": {},
                    "response": {"usage": {"input_tokens": 1_200_000, "output_tokens": 1_500}},
                    "timing": {"ttft_ms": 500.0, "total_ms": 501.5},
                }
            ],
        )

        data = _read_offline_metrics(log_dir)

        assert data is not None
        assert data["decode_samples"] == 0
        assert data["avg_decode_throughput_tps"] == 0.0
        assert data["latest_decode_throughput_tps"] == 0.0
        # Prefill still uses the genuine TTFT: 1,200,000 tokens over 0.5s.
        assert data["avg_prefill_throughput_tps"] == 2_400_000.0
        assert data["avg_ttft_ms"] == 500.0

    def test_legacy_plausible_window_is_still_admitted(self, tmp_path: Path) -> None:
        """Pre-0097 logs keep contributing decode samples when the window is physically credible."""
        log_dir = self._write_records(
            tmp_path,
            [
                {
                    "turn_id": 1,
                    "cache_action": "MISS",
                    "delta": {},
                    "response": {"usage": {"input_tokens": 100, "output_tokens": 50}},
                    "timing": {"ttft_ms": 200.0, "total_ms": 1200.0},
                },
                {
                    "turn_id": 2,
                    "cache_action": "MISS",
                    "delta": {},
                    "response": {"usage": {"input_tokens": 100, "output_tokens": 1500}},
                    "timing": {"ttft_ms": 200.0, "total_ms": 201.0},
                },
            ],
        )

        data = _read_offline_metrics(log_dir)

        assert data is not None
        # Only the 1.0s window is admitted (50 tokens / 1.0s), so the 1,500,000 tok/s artefact never
        # enters the average.
        assert data["decode_samples"] == 1
        assert data["avg_decode_throughput_tps"] == 50.0

    def test_streaming_decode_rate_is_honoured_and_non_streaming_ignored(self, tmp_path: Path) -> None:
        """Post-0097 records carry an explicit ``streaming`` flag plus the admitted rate."""
        log_dir = self._write_records(
            tmp_path,
            [
                {
                    "turn_id": 1,
                    "cache_action": "MISS",
                    "delta": {},
                    "response": {"usage": {"input_tokens": 1000, "output_tokens": 100}},
                    "timing": {
                        "ttft_ms": 500.0,
                        "total_ms": 900.0,
                        "streaming": True,
                        "generation_ms": 400.0,
                        "prefill_tps": 2000.0,
                        "tail_prefill_tps": 2000.0,
                        "decode_tps": 250.0,
                    },
                },
                {
                    "turn_id": 2,
                    "cache_action": "MISS",
                    "delta": {},
                    "response": {"usage": {"input_tokens": 2000, "output_tokens": 200}},
                    "timing": {
                        "ttft_ms": 400.0,
                        "total_ms": 401.0,
                        "streaming": False,
                        "generation_ms": None,
                        "prefill_tps": 5000.0,
                        "tail_prefill_tps": 5000.0,
                        "decode_tps": None,
                    },
                },
            ],
        )

        data = _read_offline_metrics(log_dir)

        assert data is not None
        assert data["decode_samples"] == 1
        assert data["avg_decode_throughput_tps"] == 250.0
        assert data["latest_decode_throughput_tps"] == 250.0
        assert data["avg_prefill_throughput_tps"] == 3500.0
        assert data["latest_prefill_tps"] == 5000.0
        assert data["latest_ttft_ms"] == 400.0
        assert data["latest_total_time_ms"] == 401.0

    def test_unmeasured_prefill_rate_falls_back_to_recorded_ttft(self, tmp_path: Path) -> None:
        """Records with ``prefill_tps: null`` still derive prefill speed from a real TTFT."""
        log_dir = self._write_records(
            tmp_path,
            [
                {
                    "turn_id": 1,
                    "cache_action": "MISS",
                    "delta": {},
                    "response": {"usage": {"input_tokens": 900, "output_tokens": 0, "cache_read_input_tokens": 300}},
                    "timing": {"ttft_ms": 300.0, "total_ms": 300.0, "streaming": False, "prefill_tps": None},
                }
            ],
        )

        data = _read_offline_metrics(log_dir)

        assert data is not None
        assert data["avg_prefill_throughput_tps"] == 3000.0  # 900 / 0.3s
        assert data["avg_tail_prefill_tps"] == 2000.0  # 600 uncached / 0.3s

    def test_stored_zero_rate_stays_unmeasured_instead_of_re_derived(self, tmp_path: Path) -> None:
        """A stored ``0.0`` rate is *unmeasured* and must not be re-derived from the recorded TTFT."""
        log_dir = self._write_records(
            tmp_path,
            [
                {
                    "turn_id": 1,
                    "cache_action": "MISS",
                    "delta": {},
                    "response": {"usage": {"input_tokens": 900, "output_tokens": 0, "cache_read_input_tokens": 300}},
                    "timing": {
                        "ttft_ms": 300.0,
                        "total_ms": 300.0,
                        "streaming": False,
                        "prefill_tps": 0.0,
                        "tail_prefill_tps": 0.0,
                    },
                },
                {
                    "turn_id": 2,
                    "cache_action": "MISS",
                    "delta": {},
                    "response": {"usage": {"input_tokens": 1000, "output_tokens": 0, "cache_read_input_tokens": 0}},
                    "timing": {
                        "ttft_ms": 200.0,
                        "total_ms": 200.0,
                        "streaming": False,
                        "prefill_tps": 5000.0,
                        "tail_prefill_tps": 5000.0,
                    },
                },
            ],
        )

        data = _read_offline_metrics(log_dir)

        assert data is not None
        # The 0.0 record contributes its timing only, never a rate, so the average is the 5000 t/s
        # sample alone -- not (3000 derived + 5000) / 2 = 4000.
        assert data["avg_prefill_throughput_tps"] == 5000.0
        assert data["avg_tail_prefill_tps"] == 5000.0
        assert data["latest_prefill_tps"] == 5000.0
        assert data["avg_ttft_ms"] == 250.0  # (300 + 200) / 2

    def test_live_and_offline_metric_surfaces_agree(self, tmp_path: Path) -> None:
        """The in-memory proxy and the offline parser must publish identical numbers."""
        log_dir = self._write_records(
            tmp_path,
            [
                {
                    "turn_id": 1,
                    "cache_action": "MISS",
                    "delta": {"tool_outputs_omitted": 2, "chars_saved": 400},
                    "response": {
                        "usage": {
                            "input_tokens": 1000,
                            "output_tokens": 100,
                            "cache_read_input_tokens": 200,
                            "cache_creation_input_tokens": 50,
                            "reasoning_tokens": 10,
                        }
                    },
                    "timing": {
                        "ttft_ms": 500.0,
                        "total_ms": 900.0,
                        "streaming": True,
                        "generation_ms": 400.0,
                        "prefill_tps": 2000.0,
                        "tail_prefill_tps": 1600.0,
                        "decode_tps": 250.0,
                    },
                },
                {
                    "turn_id": 2,
                    "cache_action": "MISS",
                    "delta": {"tool_outputs_omitted": 1, "chars_saved": 200},
                    "response": {
                        "usage": {
                            "input_tokens": 2000,
                            "output_tokens": 200,
                            "cache_read_input_tokens": 1000,
                            "cache_creation_input_tokens": 0,
                            "reasoning_tokens": 0,
                        }
                    },
                    "timing": {
                        "ttft_ms": 400.0,
                        "total_ms": 401.0,
                        "streaming": False,
                        "generation_ms": 1.0,
                        "prefill_tps": 5000.0,
                        "tail_prefill_tps": 2500.0,
                        "decode_tps": None,
                    },
                },
            ],
        )

        offline = _read_offline_metrics(log_dir)

        live = CumulativeMetrics()
        live.record_request()
        live.record_request()
        live.record_cleaner(
            SimpleNamespace(
                tool_outputs_omitted=3,
                chars_saved=600,
                turns_summarized=0,
                cache_control_injected=0,
            )
        )
        live.record_response(
            input_tokens=1000,
            output_tokens=100,
            cache_read_tokens=200,
            cache_creation_tokens=50,
            reasoning_tokens=10,
            ttft=0.5,
            output_tps=250.0,
            prefill_tps=2000.0,
            tail_prefill_tps=1600.0,
            total_time=0.9,
        )
        live.record_response(
            input_tokens=2000,
            output_tokens=200,
            cache_read_tokens=1000,
            cache_creation_tokens=0,
            reasoning_tokens=0,
            ttft=0.4,
            output_tps=None,
            prefill_tps=5000.0,
            tail_prefill_tps=2500.0,
            total_time=0.401,
        )
        live_dict = live.to_dict()

        assert offline is not None
        shared_keys = [
            "total_requests",
            "total_turns",
            "cache_hits",
            "cache_misses",
            "cache_hit_rate",
            "provider_cache_hit_rate",
            "tool_calls_pruned",
            "tokens_reduced",
            "chars_saved",
            "avg_ttft_ms",
            "avg_decode_throughput_tps",
            "latest_decode_throughput_tps",
            "decode_samples",
            "avg_prefill_throughput_tps",
            "latest_prefill_tps",
            "avg_tail_prefill_tps",
            "latest_tail_prefill_tps",
            "latest_ttft_ms",
            "latest_total_time_ms",
            "total_input_tokens",
            "total_output_tokens",
            "total_cache_read_tokens",
            "total_cache_creation_tokens",
            "total_reasoning_tokens",
        ]
        for key in shared_keys:
            assert offline[key] == live_dict[key], f"{key}: offline={offline[key]} live={live_dict[key]}"


def _free_ports(port: int, host: str = "127.0.0.1") -> bool:
    return False


class TestMitmwebInspectorDefaultBean0129:
    """The mitmweb inspector is opt-in (``--web`` or ``HOLON_COHERENCE_WEB``); a plain ``start`` stays headless.

    mitmweb keeps every flow in memory with no retention cap, so a long-running default proxy must not run it.
    """

    @staticmethod
    def _host_start(
        argv: list[str],
        in_use: Any = _free_ports,
        token: str = "tok123",
    ) -> tuple[list[str], MagicMock, MagicMock]:
        with (
            patch("holon_coherence.cli.is_in_container", return_value=False),
            patch("holon_coherence.cli.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.cli.is_port_in_use", side_effect=in_use),
            patch("holon_coherence.cli.resolve_web_password", return_value=token) as mock_resolve,
            patch("holon_coherence.cli.save_web_token") as mock_save,
            patch("holon_coherence.cli.ensure_docker_image"),
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch("subprocess.run") as mock_run,
        ):
            main(argv)
        return mock_run.call_args_list[-1][0][0], mock_resolve, mock_save

    @staticmethod
    def _in_container_start(argv: list[str], monkeypatch: pytest.MonkeyPatch) -> list[str]:
        launched: list[list[str]] = []

        def fake_run(cmd: list[str], *args: Any, **kwargs: Any) -> MagicMock:
            launched.append(list(cmd))
            return MagicMock(returncode=0)

        monkeypatch.setattr("holon_coherence.cli.is_in_container", lambda: True)
        with (
            patch("holon_coherence.cli.resolve_web_password", return_value="tok123"),
            patch("subprocess.run", side_effect=fake_run),
        ):
            main(argv)
        assert len(launched) == 1, "no Docker command may run inside the container"
        return launched[0]

    def test_start_web_selects_mitmweb_and_passes_token(self) -> None:
        docker_cmd, mock_resolve, mock_save = self._host_start(["start", "-d", "--web"])

        assert "127.0.0.1:8081:8081" in docker_cmd
        assert "HOLON_COHERENCE_WEB_PASSWORD=tok123" in docker_cmd
        tail = docker_cmd[docker_cmd.index("holon-coherence:latest") :]
        assert tail == ["holon-coherence:latest", "start", "--port", "8080", "--web", "--web-port", "8081"]
        mock_resolve.assert_called_once_with(None)
        mock_save.assert_called_once_with("tok123")

    def test_start_web_binds_inspector_to_loopback_only(self) -> None:
        docker_cmd, _resolve, _save = self._host_start(["start", "-d", "--web"])
        mappings = [docker_cmd[i + 1] for i, arg in enumerate(docker_cmd) if arg == "-p"]
        assert mappings and all(mapping.startswith("127.0.0.1:") for mapping in mappings)

    @pytest.mark.parametrize("argv", [["start", "-d"], ["start", "-d", "--no-web"]])
    def test_start_default_and_no_web_select_mitmdump(self, argv: list[str]) -> None:
        docker_cmd, mock_resolve, mock_save = self._host_start(argv)

        assert not any(arg.endswith(":8081") for arg in docker_cmd)
        assert not any(arg.startswith("HOLON_COHERENCE_WEB_PASSWORD=") for arg in docker_cmd)
        tail = docker_cmd[docker_cmd.index("holon-coherence:latest") :]
        assert tail == ["holon-coherence:latest", "start", "--port", "8080"]
        mock_resolve.assert_not_called()
        mock_save.assert_not_called()

    @pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
    def test_start_env_opt_in_selects_mitmweb(self, value: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_COHERENCE_WEB", value)
        docker_cmd, _resolve, mock_save = self._host_start(["start", "-d"])
        assert "127.0.0.1:8081:8081" in docker_cmd
        assert docker_cmd[-3:] == ["--web", "--web-port", "8081"]
        mock_save.assert_called_once_with("tok123")

    @pytest.mark.parametrize("value", ["", "0", "false", "off"])
    def test_start_env_falsy_stays_headless(self, value: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_COHERENCE_WEB", value)
        docker_cmd, _resolve, _save = self._host_start(["start", "-d"])
        assert "--web" not in docker_cmd

    def test_start_no_web_overrides_env_opt_in(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_COHERENCE_WEB", "1")
        docker_cmd, mock_resolve, _save = self._host_start(["start", "-d", "--no-web"])
        assert "--web" not in docker_cmd
        mock_resolve.assert_not_called()

    @pytest.mark.parametrize("env_value", [None, "0"])
    def test_start_web_password_alone_implies_inspector(
        self, env_value: str | None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        if env_value is not None:
            monkeypatch.setenv("HOLON_COHERENCE_WEB", env_value)
        docker_cmd, mock_resolve, mock_save = self._host_start(["start", "-d", "--web-password", "pw-secret"])

        assert "127.0.0.1:8081:8081" in docker_cmd
        assert docker_cmd[-3:] == ["--web", "--web-port", "8081"]
        mock_resolve.assert_called_once_with("pw-secret")
        mock_save.assert_called_once_with("tok123")
        assert "pw-secret" not in capsys.readouterr().err

    def test_start_no_web_with_web_password_warns_without_leaking(self, capsys: pytest.CaptureFixture[str]) -> None:
        docker_cmd, mock_resolve, mock_save = self._host_start(
            ["start", "-d", "--no-web", "--web-password", "pw-secret"]
        )

        assert "--web" not in docker_cmd
        assert not any(arg.startswith("HOLON_COHERENCE_WEB_PASSWORD=") for arg in docker_cmd)
        mock_resolve.assert_not_called()
        mock_save.assert_not_called()
        captured = capsys.readouterr()
        assert "--web-password is ignored because --no-web disables the mitmweb inspector" in captured.err
        assert "pw-secret" not in captured.out + captured.err

    def test_in_container_web_password_alone_runs_mitmweb(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cmd = self._in_container_start(["start", "--port", "8080", "--web-password", "pw-secret"], monkeypatch)
        assert cmd[0].endswith("mitmweb")

    def test_web_password_env_var_does_not_imply_inspector(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_COHERENCE_WEB_PASSWORD", "env-secret")
        docker_cmd, mock_resolve, _save = self._host_start(["start", "-d"])
        assert "--web" not in docker_cmd
        mock_resolve.assert_not_called()

    def test_start_web_inspector_port_falls_back(self, capsys: pytest.CaptureFixture[str]) -> None:
        docker_cmd, _resolve, _save = self._host_start(
            ["start", "-d", "--web"], in_use=lambda port, host="127.0.0.1": port == 8081
        )

        assert "127.0.0.1:8082:8081" in docker_cmd
        assert "127.0.0.1:8080:8080" in docker_cmd
        out = capsys.readouterr().out
        assert "Mapping mitmweb inspector to host port 8082 instead." in out
        assert "http://127.0.0.1:8082/?token=tok123" in out

    def test_start_custom_inspector_port_falls_back(self) -> None:
        docker_cmd, _resolve, _save = self._host_start(
            ["start", "-d", "--web", "--web-port", "9090"], in_use=lambda port, host="127.0.0.1": port == 9090
        )
        assert "127.0.0.1:9091:8081" in docker_cmd

    def test_start_inspector_fallback_skips_local_llm_port(self) -> None:
        docker_cmd, _resolve, _save = self._host_start(
            ["start", "-d", "--web", "--local-llm-base", "localhost:8082"],
            in_use=lambda port, host="127.0.0.1": port == 8081,
        )
        assert "127.0.0.1:8083:8081" in docker_cmd
        assert not any(arg == "127.0.0.1:8082:8081" for arg in docker_cmd)

    def test_start_inspector_never_lands_on_the_requested_local_llm_port(self) -> None:
        docker_cmd, _resolve, _save = self._host_start(["start", "-d", "--web", "--local-llm-base", "localhost:8081"])
        assert "127.0.0.1:8082:8081" in docker_cmd

    def test_start_prints_all_endpoints(self, capsys: pytest.CaptureFixture[str]) -> None:
        self._host_start(["start", "-d", "--web"])
        out = capsys.readouterr().out
        assert "Proxy Listen Address         : 127.0.0.1:8080" in out
        assert "Coherence Live Dashboard     : http://127.0.0.1:8080/holon/" in out
        assert "mitmweb Req/Resp Inspector   : http://127.0.0.1:8081/?token=tok123" in out
        assert "Web API Key" not in out

    @pytest.mark.parametrize("argv", [["start", "-d"], ["start", "-d", "--no-web"]])
    def test_start_headless_reports_inspector_not_running(
        self, argv: list[str], capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._host_start(argv)
        out = capsys.readouterr().out
        assert "Proxy Listen Address         : 127.0.0.1:8080" in out
        assert "mitmweb Req/Resp Inspector   : not running (headless; enable with --web or HOLON_COHERENCE_WEB=1)" in (
            out
        )
        assert "?token=" not in out

    def test_in_container_web_runs_mitmweb_with_password_without_printing_it(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cmd = self._in_container_start(["start", "--port", "8080", "--web", "--web-port", "8081"], monkeypatch)

        assert cmd[0].endswith("mitmweb")
        assert cmd[cmd.index("--web-host") + 1] == "0.0.0.0"
        assert cmd[cmd.index("--web-port") + 1] == "8081"
        set_values = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "--set"]
        assert "web_password=tok123" in set_values
        assert "web_open_browser=false" in set_values
        # In-container stdout is kept by `docker logs`; the raw token must never reach it.
        out = capsys.readouterr().out
        assert "tok123" not in out
        assert "mitmweb inspector listening on container port 8081" in out
        # A manual `docker run ... start --web` has no host-side token; the message names the recovery path.
        assert "docker exec <container> sh -c 'cat \"$HOME/.holon/web-token\"'" in out

    def test_in_container_no_web_runs_mitmdump(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cmd = self._in_container_start(["start", "--port", "8080", "--no-web"], monkeypatch)
        assert cmd[0].endswith("mitmdump")
        assert not any("web_password" in arg for arg in cmd)

    def test_in_container_default_stays_headless(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The Dockerfile CMD and run/run-agent containers publish no inspector port."""
        cmd = self._in_container_start(["start", "--port", "8080"], monkeypatch)
        assert cmd[0].endswith("mitmdump")
        assert "--web-port" not in cmd

    def test_in_container_ignores_env_opt_in(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The env opt-in is a host preference; only an explicit --web turns on an in-container mitmweb."""
        monkeypatch.setenv("HOLON_COHERENCE_WEB", "1")
        cmd = self._in_container_start(["start", "--port", "8080"], monkeypatch)
        assert cmd[0].endswith("mitmdump")

    def test_ensure_proxy_running_stays_headless(self) -> None:
        with (
            patch("holon_coherence.cli.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.cli.is_port_in_use", return_value=False),
            patch("holon_coherence.cli.is_container_running", return_value=False),
            patch("holon_coherence.cli.resolve_web_password") as mock_resolve,
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run,
            patch("holon_coherence.cli.wait_for_proxy_ready", return_value=True),
        ):
            assert ensure_proxy_running(port=8080) is True
        docker_cmd = mock_run.call_args_list[-1][0][0]
        assert "--web" not in docker_cmd
        assert not any(arg.endswith(":8081") for arg in docker_cmd)
        assert not any(arg.startswith("HOLON_COHERENCE_WEB_PASSWORD=") for arg in docker_cmd)
        mock_resolve.assert_not_called()


class TestEndpointReportingBean0129:
    """``status``, ``metrics`` and ``web-token`` report the resolved endpoints, never a stale URL."""

    @staticmethod
    def _mapped_ports(mapping: dict[int, int | None]) -> Any:
        return lambda _name, container_port: mapping.get(container_port)

    def test_format_endpoint_rows_alignment(self) -> None:
        rows = format_endpoint_rows(ExposedEndpoints(proxy_port=8080, web_port=8081, web_token="tok"))
        assert rows == [
            "  Proxy Listen Address         : 127.0.0.1:8080",
            "  Coherence Live Dashboard     : http://127.0.0.1:8080/holon/",
            "  mitmweb Req/Resp Inspector   : http://127.0.0.1:8081/?token=tok",
        ]

    def test_format_endpoint_rows_without_token_gives_a_hint_not_a_url(self) -> None:
        rows = format_endpoint_rows(ExposedEndpoints(proxy_port=8080, web_port=8081, web_token=None))
        assert "?token=" not in rows[2]
        assert "running on 127.0.0.1:8081 (token unavailable; recover it with: " in rows[2]
        assert "docker exec <container> sh -c 'cat \"$HOME/.holon/web-token\"'" in rows[2]
        no_token = ExposedEndpoints(proxy_port=8080, web_port=8081, web_token=None)
        named = format_endpoint_rows(no_token, container_name="a")
        assert "docker exec a sh -c" in named[2]

    def test_format_endpoint_rows_when_down(self) -> None:
        rows = format_endpoint_rows(ExposedEndpoints(proxy_port=None, web_port=None, web_token="stale"))
        assert all(row.endswith(": not running") for row in rows)

    def test_status_prints_all_endpoints_when_running(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("holon_coherence.cli.is_container_running", return_value=True),
            patch(
                "holon_coherence.cli.get_container_mapped_port",
                side_effect=self._mapped_ports({8080: 8080, 8081: 8082}),
            ),
            patch("holon_coherence.cli.get_container_web_token", return_value="tok"),
            patch("subprocess.run", return_value=MagicMock(returncode=0)),
            patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")),
        ):
            main(["status"])
        out = capsys.readouterr().out
        assert "Proxy Listen Address         : 127.0.0.1:8080" in out
        assert "Coherence Live Dashboard     : http://127.0.0.1:8080/holon/" in out
        assert "mitmweb Req/Resp Inspector   : http://127.0.0.1:8082/?token=tok" in out

    def test_status_reports_inspector_not_running_without_stale_url(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("holon_coherence.cli.is_container_running", return_value=False),
            patch("holon_coherence.cli.get_active_web_token", return_value="stale-token"),
            patch("subprocess.run", return_value=MagicMock(returncode=0)),
        ):
            main(["status"])
        out = capsys.readouterr().out
        assert "mitmweb inspector: not running" in out
        assert "?token=" not in out
        assert "stale-token" not in out

    def test_status_headless_container_reports_inspector_not_running(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("holon_coherence.cli.is_container_running", return_value=True),
            patch("holon_coherence.cli.get_container_mapped_port", side_effect=self._mapped_ports({8080: 8080})),
            patch("holon_coherence.cli.get_active_web_token", return_value="stale-token"),
            patch("subprocess.run", return_value=MagicMock(returncode=0)),
            patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")),
        ):
            main(["status"])
        out = capsys.readouterr().out
        assert "Proxy Listen Address         : 127.0.0.1:8080" in out
        assert "mitmweb Req/Resp Inspector   : not running (headless; enable with --web or HOLON_COHERENCE_WEB=1)" in (
            out
        )
        assert "stale-token" not in out

    @staticmethod
    def _empty_metrics_response() -> MagicMock:
        # Transport fixture only: zero counters exercise the table layout, no figures are asserted.
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({}).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        return mock_resp

    def test_metrics_table_prints_all_endpoints(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("urllib.request.urlopen", return_value=self._empty_metrics_response()),
            patch("holon_coherence.cli.is_container_running", return_value=True),
            patch(
                "holon_coherence.cli.get_container_mapped_port",
                side_effect=self._mapped_ports({8080: 8080, 8081: 8083}),
            ),
            patch("holon_coherence.cli.get_container_web_token", return_value="tok"),
        ):
            assert handle_metrics(port=9000) == 0
        out = capsys.readouterr().out
        # An explicit --port is honoured for the proxy rows; the inspector comes from the container.
        assert "Proxy Listen Address         : 127.0.0.1:9000" in out
        assert "Coherence Live Dashboard     : http://127.0.0.1:9000/holon/" in out
        assert "mitmweb Req/Resp Inspector   : http://127.0.0.1:8083/?token=tok" in out

    def test_metrics_json_does_not_include_token(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("urllib.request.urlopen", return_value=self._empty_metrics_response()),
            patch("holon_coherence.cli.is_container_running", return_value=True),
            patch(
                "holon_coherence.cli.get_container_mapped_port",
                side_effect=self._mapped_ports({8080: 8080, 8081: 8081}),
            ),
            patch("holon_coherence.cli.get_container_web_token", return_value="tok-secret"),
        ):
            assert handle_metrics(port=8080, json_output=True) == 0
        out = capsys.readouterr().out
        assert "tok-secret" not in out
        assert json.loads(out) == {}

    def test_metrics_down_reports_inspector_not_running(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")),
            patch("holon_coherence.cli.get_active_web_token", return_value="stale-token"),
        ):
            assert handle_metrics(port=8080) == 1
        out = capsys.readouterr().out
        assert "PROXY STATUS: DOWN" in out
        assert "mitmweb inspector: not running" in out
        assert "stale-token" not in out

    def test_web_token_prints_resolved_inspector_url(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("holon_coherence.cli.get_container_web_token", return_value="tok"),
            patch("holon_coherence.cli.is_container_running", return_value=True),
            patch("holon_coherence.cli.get_container_mapped_port", side_effect=self._mapped_ports({8081: 8084})),
            pytest.raises(SystemExit) as exc,
        ):
            main(["web-token"])
        assert exc.value.code == 0
        assert "mitmweb Req/Resp Inspector: http://127.0.0.1:8084/?token=tok" in capsys.readouterr().out

    @pytest.mark.parametrize("command", ["web-token", "web-key"])
    def test_web_token_name_selects_container(self, command: str, capsys: pytest.CaptureFixture[str]) -> None:
        ports = {"a": {8081: 8081}, "b": {8081: 8091}}
        tokens = {"a": "tok-a", "b": "tok-b"}
        with (
            patch("holon_coherence.cli.is_container_running", return_value=True),
            patch("holon_coherence.cli.get_container_mapped_port", side_effect=lambda name, port: ports[name][port]),
            patch("holon_coherence.cli.get_container_web_token", side_effect=lambda name: tokens[name]),
            pytest.raises(SystemExit) as exc,
        ):
            main([command, "--name", "b"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "http://127.0.0.1:8091/?token=tok-b" in out
        assert "tok-a" not in out

    def test_web_token_unavailable_names_recovery_command(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("holon_coherence.cli.is_container_running", return_value=True),
            patch("holon_coherence.cli.get_container_mapped_port", side_effect=self._mapped_ports({8081: 8081})),
            patch("holon_coherence.cli.get_container_web_token", return_value=None),
            pytest.raises(SystemExit) as exc,
        ):
            main(["web-token", "--name", "manual-proxy"])
        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "token unavailable for container 'manual-proxy'" in out
        assert "docker exec manual-proxy sh -c 'cat \"$HOME/.holon/web-token\"'" in out
        assert "?token=" not in out

    def test_two_named_containers_each_report_their_own_token(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # ``start --name a`` then ``start --name b``: the shared file holds b's token, but a's inspector accepts a's.
        ports = {"a": {8080: 8080, 8081: 8081}, "b": {8080: 8090, 8081: 8091}}
        tokens = {"a": "tok-a", "b": "tok-b"}
        with (
            patch("holon_coherence.cli.is_container_running", return_value=True),
            patch("holon_coherence.cli.get_container_mapped_port", side_effect=lambda name, port: ports[name][port]),
            patch("holon_coherence.cli.get_container_web_token", side_effect=lambda name: tokens[name]),
            patch("holon_coherence.cli.get_active_web_token", return_value="tok-b"),
            patch("subprocess.run", return_value=MagicMock(returncode=0)),
            patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")),
        ):
            main(["status", "--name", "a"])
            out_a = capsys.readouterr().out
            main(["status", "--name", "b"])
            out_b = capsys.readouterr().out
            monkeypatch.setenv("HOLON_CONTAINER_NAME", "a")
            with pytest.raises(SystemExit) as exc:
                main(["web-token"])
            out_web_a = capsys.readouterr().out
        assert "mitmweb Req/Resp Inspector   : http://127.0.0.1:8081/?token=tok-a" in out_a
        assert "tok-b" not in out_a
        assert "mitmweb Req/Resp Inspector   : http://127.0.0.1:8091/?token=tok-b" in out_b
        assert exc.value.code == 0
        assert "mitmweb Req/Resp Inspector: http://127.0.0.1:8081/?token=tok-a" in out_web_a
        assert "tok-b" not in out_web_a

    def test_web_token_running_inspector_without_container_token_gives_no_stale_url(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with (
            patch("holon_coherence.cli.is_container_running", return_value=True),
            patch("holon_coherence.cli.get_container_mapped_port", side_effect=self._mapped_ports({8081: 8081})),
            patch("holon_coherence.cli.get_container_web_token", return_value=None),
            patch("holon_coherence.cli.get_active_web_token", return_value="stale-token"),
            pytest.raises(SystemExit) as exc,
        ):
            main(["web-token"])
        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "token unavailable for container 'holon-coherence-proxy'" in out
        assert "stale-token" not in out
        assert "?token=" not in out

    def test_get_container_web_token_reads_container_env(self) -> None:
        env = '["PATH=/usr/bin","HOLON_COHERENCE_WEB_PASSWORD=tok-from-env","OTHER=x"]\n'
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout=env)) as mock_run:
            assert get_container_web_token("a") == "tok-from-env"
        assert mock_run.call_args[0][0] == ["docker", "inspect", "-f", "{{json .Config.Env}}", "a"]
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout='["PATH=/usr/bin"]')):
            assert get_container_web_token("a") is None
        with patch("subprocess.run", return_value=MagicMock(returncode=1, stdout="")):
            assert get_container_web_token("a") is None
        with patch("subprocess.run", side_effect=FileNotFoundError("docker")):
            assert get_container_web_token("a") is None
