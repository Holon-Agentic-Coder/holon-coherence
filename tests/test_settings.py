from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import pytest

from holon_coherence.commands.runner import build_proxy_env
from holon_coherence.commands.web_token import resolve_web_password
from holon_coherence.ringer_orchestrator import get_default_architect_model, get_default_executor_model
from holon_coherence.settings import (
    DEFAULT_ARCHITECT_MODEL,
    DEFAULT_CONTAINER_NAME,
    DEFAULT_EXECUTOR_MODEL,
    DEFAULT_PROXY_PORT,
    CoherenceSettings,
    parse_bool,
    parse_optional_path,
    parse_optional_str,
    parse_path,
    parse_port,
    parse_str,
)


def test_from_env_defaults() -> None:
    settings = CoherenceSettings.from_env({})
    assert settings.web_password is None
    assert settings.api_token is None
    assert settings.web_inspector is False
    assert settings.proxy_port == DEFAULT_PROXY_PORT == 8080
    assert settings.container_name == DEFAULT_CONTAINER_NAME == "holon-coherence-proxy"
    assert settings.in_container is False
    assert settings.token_reduction is True
    assert settings.passive_monitoring is False
    assert settings.enable_wire_logging is True
    assert settings.ca_cert is None
    assert isinstance(settings.cache_dir, Path)
    assert isinstance(settings.wire_log_dir, Path)
    assert settings.local_llm_base is None
    assert settings.architect_model == DEFAULT_ARCHITECT_MODEL == "claude-3-5-sonnet"
    assert settings.executor_model == DEFAULT_EXECUTOR_MODEL == "gemini-3.5-flash"
    assert settings.no_proxy is None
    assert settings.no_proxy_lower is None


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", " Yes ", "on"])
def test_parse_bool_truthy(raw: str) -> None:
    assert parse_bool(raw, False) is True
    assert parse_bool(raw, True) is True


@pytest.mark.parametrize("raw", ["0", "false", "FALSE", " No ", "off"])
def test_parse_bool_falsy(raw: str) -> None:
    assert parse_bool(raw, True) is False
    assert parse_bool(raw, False) is False


@pytest.mark.parametrize("raw", [None, "", "   ", "maybe"])
@pytest.mark.parametrize("default", [True, False])
def test_parse_bool_invalid_or_empty_falls_back(raw: str | None, default: bool) -> None:
    assert parse_bool(raw, default) is default


@pytest.mark.parametrize(("raw", "expected"), [("1", 1), ("8080", 8080), (" 65535 ", 65535)])
def test_parse_port_valid(raw: str, expected: int) -> None:
    assert parse_port(raw, 8080) == expected


@pytest.mark.parametrize("raw", [None, "0", "-1", "65536", "abc", "", "   "])
def test_parse_port_invalid_or_out_of_range_falls_back(raw: str | None) -> None:
    assert parse_port(raw, 8080) == 8080


def test_string_and_path_parsing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    assert parse_optional_str("  secret-val  ") == "secret-val"
    assert parse_optional_str("   ") is None
    assert parse_optional_str("") is None
    assert parse_optional_str(None) is None
    assert parse_str("  custom-name  ", "fallback") == "custom-name"
    assert parse_str("   ", "fallback") == "fallback"
    assert parse_optional_path("   ") is None
    assert parse_path("   ", "~/.holon/cache") == tmp_path / ".holon" / "cache"

    settings = CoherenceSettings.from_env(
        {
            "HOLON_COHERENCE_WEB_PASSWORD": "  pw123  ",
            "HOLON_COHERENCE_API_TOKEN": "  tok456  ",
            "HOLON_CONTAINER_NAME": "  ",
            "HOLON_LOCAL_LLM_BASE": "  http://127.0.0.1:11434  ",
            "HOLON_CA_CERT": "  ~/certs/ca.pem  ",
            "CACHE_DIR": "~/custom-cache",
            "WIRE_LOG_DIR": "~/custom-logs",
        }
    )
    assert settings.web_password == "pw123"
    assert settings.api_token == "tok456"
    assert settings.container_name == DEFAULT_CONTAINER_NAME
    assert settings.local_llm_base == "http://127.0.0.1:11434"
    assert settings.ca_cert == tmp_path / "certs" / "ca.pem"
    assert settings.cache_dir == tmp_path / "custom-cache"
    assert settings.wire_log_dir == tmp_path / "custom-logs"


def test_settings_instance_is_frozen() -> None:
    settings = CoherenceSettings.from_env({})
    with pytest.raises(FrozenInstanceError):
        settings.proxy_port = 9999  # type: ignore[misc]


def test_from_env_reads_dynamically_without_import_freeze(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOLON_PROXY_PORT", "9091")
    monkeypatch.setenv("HOLON_COHERENCE_WEB", "yes")
    first = CoherenceSettings.from_env()
    assert first.proxy_port == 9091
    assert first.web_inspector is True

    monkeypatch.setenv("HOLON_PROXY_PORT", "9092")
    monkeypatch.delenv("HOLON_COHERENCE_WEB")
    second = CoherenceSettings.from_env()
    assert second.proxy_port == 9092
    assert second.web_inspector is False


def test_resolve_web_password_uses_settings_dynamically(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOLON_COHERENCE_WEB_PASSWORD", "  dynamic-pwd  ")
    assert resolve_web_password() == "dynamic-pwd"

    monkeypatch.setenv("HOLON_COHERENCE_WEB_PASSWORD", "   ")
    generated = resolve_web_password()
    assert generated and generated != "dynamic-pwd"


def test_build_proxy_env_normalizes_bools_and_merges_no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COHERENCE_TOKEN_REDUCTION", "false")
    monkeypatch.setenv("HOLON_PASSIVE_MONITORING", "true")
    monkeypatch.setenv("NO_PROXY", "corp.internal,shared.local")
    monkeypatch.setenv("no_proxy", "dev.internal,shared.local")

    with (
        patch("os.path.exists", return_value=True),
        patch("holon_coherence.commands.runner.get_or_create_merged_ca_bundle", return_value="/tmp/merged.crt"),
    ):
        env = build_proxy_env("http://127.0.0.1:8080")

    assert env["COHERENCE_TOKEN_REDUCTION"] == "0"
    assert env["HOLON_PASSIVE_MONITORING"] == "1"
    entries = env["NO_PROXY"].split(",")
    assert "corp.internal" in entries
    assert "dev.internal" in entries
    assert entries.count("shared.local") == 1
    assert env["no_proxy"] == env["NO_PROXY"]


def test_ringer_orchestrator_models_read_dynamically(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOLON_ARCHITECT_MODEL", "  custom-architect  ")
    monkeypatch.setenv("HOLON_EXECUTOR_MODEL", "  custom-executor  ")
    assert get_default_architect_model() == "custom-architect"
    assert get_default_executor_model() == "custom-executor"

    monkeypatch.delenv("HOLON_ARCHITECT_MODEL")
    monkeypatch.delenv("HOLON_EXECUTOR_MODEL")
    assert get_default_architect_model() == DEFAULT_ARCHITECT_MODEL
    assert get_default_executor_model() == DEFAULT_EXECUTOR_MODEL
