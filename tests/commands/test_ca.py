from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from holon_coherence.ca_generator import _sync_mitmproxy_ca
from holon_coherence.commands.ca import (
    find_system_ca_bundle,
    get_or_create_merged_ca_bundle,
    handle,
    register,
)


class TestFindSystemCABundle:
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


class TestGetOrCreateMergedCABundle:
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

        os.utime(holon_ca, (t0 + 200, t0 + 200))
        with patch("holon_coherence.commands.ca.find_system_ca_bundle", return_value=str(sys_ca)):
            result = get_or_create_merged_ca_bundle(str(holon_ca))
            assert result == str(merged_path)
            content = merged_path.read_text()
            assert "SYSTEM_ROOT_CA" in content
            assert "CACHED_CONTENT" not in content

    def test_merged_ca_bundle_deduplication(self, tmp_path: Path) -> None:
        holon_ca = tmp_path / "mitmproxy-ca-cert.pem"
        holon_ca.write_text("-----BEGIN CERTIFICATE-----\nHOLON_ROOT_CA\n-----END CERTIFICATE-----")

        sys_ca = tmp_path / "system-ca.pem"
        sys_ca.write_text(
            "-----BEGIN CERTIFICATE-----\nSYSTEM_ROOT_CA\n-----END CERTIFICATE-----\n"
            "-----BEGIN CERTIFICATE-----\nHOLON_ROOT_CA\n-----END CERTIFICATE-----"
        )

        with patch("holon_coherence.commands.ca.find_system_ca_bundle", return_value=str(sys_ca)):
            merged_path = get_or_create_merged_ca_bundle(str(holon_ca))
            with open(merged_path, encoding="utf-8") as f:
                content = f.read()
            assert content.count("HOLON_ROOT_CA") == 1


class TestCACommandRegistrationAndDispatch:
    def test_register_and_defaults(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        register(subparsers)

        args = parser.parse_args(["init-ca"])
        assert args.command == "init-ca"
        assert args.output_dir == os.path.expanduser("~/.holon/proxy-ca")
        assert args.handler == handle
        assert getattr(args, "propagates_exit", False) is False

    def test_handle_init_ca_invoked(self, tmp_path: Path) -> None:
        out_dir = tmp_path / "ca"
        args = argparse.Namespace(output_dir=str(out_dir))
        with patch("holon_coherence.commands.ca.generate_root_ca", return_value=("/cert.pem", "/key.pem")):
            res = handle(args)
            assert res == 0


class TestSyncMitmproxyCALogging:
    def test_sync_mitmproxy_ca_logs_warning_on_cert_copy_oserror(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        ca_cert = tmp_path / "holon-root-ca.crt"
        ca_key = tmp_path / "holon-root-ca.key"
        ca_cert.write_text("-----BEGIN CERTIFICATE-----\nCERT\n-----END CERTIFICATE-----\n", encoding="utf-8")
        ca_key.write_text("-----BEGIN PRIVATE KEY-----\nKEY\n-----END PRIVATE KEY-----\n", encoding="utf-8")

        with (
            patch(
                "holon_coherence.ca_generator.shutil.copyfile",
                side_effect=PermissionError("read-only cert target"),
            ),
            caplog.at_level(logging.WARNING, logger="holon_coherence.ca_generator"),
        ):
            _sync_mitmproxy_ca(str(ca_cert), str(ca_key), str(tmp_path))

        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("mitmproxy-ca-cert.pem" in msg and "read-only cert target" in msg for msg in warnings)
        assert (tmp_path / "mitmproxy-ca.pem").is_file()

    def test_sync_mitmproxy_ca_logs_warning_on_bundle_write_oserror(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        ca_cert = tmp_path / "holon-root-ca.crt"
        ca_key = tmp_path / "holon-root-ca.key"
        ca_cert.write_text("-----BEGIN CERTIFICATE-----\nCERT\n-----END CERTIFICATE-----\n", encoding="utf-8")
        ca_key.write_text("-----BEGIN PRIVATE KEY-----\nKEY\n-----END PRIVATE KEY-----\n", encoding="utf-8")

        with (
            patch(
                "holon_coherence.ca_generator.os.open",
                side_effect=PermissionError("read-only bundle target"),
            ),
            caplog.at_level(logging.WARNING, logger="holon_coherence.ca_generator"),
        ):
            _sync_mitmproxy_ca(str(ca_cert), str(ca_key), str(tmp_path))

        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("mitmproxy-ca.pem" in msg and "read-only bundle target" in msg for msg in warnings)
        assert (tmp_path / "mitmproxy-ca-cert.pem").is_file()
