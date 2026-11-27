from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import pytest

from holon_coherence.commands.runner import build_proxy_env
from holon_coherence.commands.web_token import resolve_web_password
from holon_coherence.ringer_orchestrator import get_default_architect_model, get_default_executor_model
from holon_coherence.settings import (
    DEFAULT_AGENT_ID,
    DEFAULT_ARCHITECT_MODEL,
    DEFAULT_CONTAINER_NAME,
    DEFAULT_EXECUTOR_MODEL,
    DEFAULT_PROXY_PORT,
    DEFAULT_ROLE,
    DEFAULT_WIRE_LOG_MAX_PENDING,
    CoherenceSettings,
    parse_bool,
    parse_non_negative_int,
    parse_optional_path,
    parse_optional_port,
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
    assert settings.proxy_port_override is None
    assert settings.container_name == DEFAULT_CONTAINER_NAME == "holon-coherence-proxy"
    assert settings.in_container is False
    assert settings.token_reduction is True
    assert settings.passive_monitoring is False
    assert settings.enable_wire_logging is True
    assert settings.ca_cert is None
    assert isinstance(settings.cache_dir, Path)
    assert isinstance(settings.wire_log_dir, Path)
    assert settings.wire_log_dir_override is None
    assert settings.wire_log_max_pending == DEFAULT_WIRE_LOG_MAX_PENDING == 256
    assert settings.wire_log_base_dir is None
    assert settings.local_llm_base is None
    assert settings.architect_model == DEFAULT_ARCHITECT_MODEL == "claude-3-5-sonnet"
    assert settings.executor_model == DEFAULT_EXECUTOR_MODEL == "gemini-3.5-flash"
    assert settings.agent_id == DEFAULT_AGENT_ID == "agy"
    assert settings.role == DEFAULT_ROLE == "executor"
    assert settings.agy_model is None
    assert settings.local_model is None
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
    assert parse_optional_port(raw) == expected


@pytest.mark.parametrize("raw", [None, "0", "-1", "65536", "abc", "", "   "])
def test_parse_port_invalid_or_out_of_range_falls_back(raw: str | None) -> None:
    assert parse_port(raw, 8080) == 8080
    assert parse_optional_port(raw) is None


@pytest.mark.parametrize(("raw", "expected"), [("0", 0), (" 512 ", 512), ("256", 256)])
def test_parse_non_negative_int_valid(raw: str, expected: int) -> None:
    assert parse_non_negative_int(raw, DEFAULT_WIRE_LOG_MAX_PENDING) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "-1", "abc"])
def test_parse_non_negative_int_invalid_falls_back(raw: str | None) -> None:
    assert parse_non_negative_int(raw, DEFAULT_WIRE_LOG_MAX_PENDING) == DEFAULT_WIRE_LOG_MAX_PENDING


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
            "WIRE_LOG_DIR": "  ~/custom-logs  ",
            "WIRE_LOG_MAX_PENDING": " 512 ",
            "HOLON_WIRE_LOG_BASE_DIR": "  ~/wire-base  ",
            "HOLON_AGENT_ID": "  custom-agent  ",
            "HOLON_ROLE": "  planner  ",
            "AGY_MODEL": "  gemini-pro  ",
            "HOLON_LOCAL_MODEL": "  qwen-coder  ",
        }
    )
    assert settings.web_password == "pw123"
    assert settings.api_token == "tok456"
    assert settings.container_name == DEFAULT_CONTAINER_NAME
    assert settings.local_llm_base == "http://127.0.0.1:11434"
    assert settings.ca_cert == tmp_path / "certs" / "ca.pem"
    assert settings.cache_dir == tmp_path / "custom-cache"
    assert settings.wire_log_dir == tmp_path / "custom-logs"
    assert settings.wire_log_dir_override == "~/custom-logs"
    assert settings.wire_log_max_pending == 512
    assert settings.wire_log_base_dir == tmp_path / "wire-base"
    assert settings.agent_id == "custom-agent"
    assert settings.role == "planner"
    assert settings.agy_model == "gemini-pro"
    assert settings.local_model == "qwen-coder"

    blank_settings = CoherenceSettings.from_env(
        {
            "WIRE_LOG_DIR": "   ",
            "WIRE_LOG_MAX_PENDING": "   ",
            "HOLON_WIRE_LOG_BASE_DIR": "   ",
            "HOLON_AGENT_ID": "   ",
            "HOLON_ROLE": "   ",
            "AGY_MODEL": "   ",
            "HOLON_LOCAL_MODEL": "   ",
        }
    )
    assert blank_settings.wire_log_dir == tmp_path / ".holon" / "logs"
    assert blank_settings.wire_log_dir_override is None
    assert blank_settings.wire_log_max_pending == DEFAULT_WIRE_LOG_MAX_PENDING
    assert blank_settings.wire_log_base_dir is None
    assert blank_settings.agent_id == DEFAULT_AGENT_ID
    assert blank_settings.role == DEFAULT_ROLE
    assert blank_settings.agy_model is None
    assert blank_settings.local_model is None


def test_settings_instance_is_frozen() -> None:
    settings = CoherenceSettings.from_env({})
    with pytest.raises(FrozenInstanceError):
        settings.proxy_port = 9999  # type: ignore[misc]


def test_from_env_reads_dynamically_without_import_freeze(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOLON_PROXY_PORT", "9091")
    monkeypatch.setenv("HOLON_COHERENCE_WEB", "yes")
    monkeypatch.setenv("WIRE_LOG_DIR", "/tmp/wire_a")
    monkeypatch.setenv("WIRE_LOG_MAX_PENDING", "64")
    monkeypatch.setenv("HOLON_AGENT_ID", "agent-a")
    monkeypatch.setenv("HOLON_ROLE", "architect")
    monkeypatch.setenv("AGY_MODEL", "model-a")
    monkeypatch.setenv("HOLON_LOCAL_MODEL", "local-a")
    first = CoherenceSettings.from_env()
    assert first.proxy_port == 9091
    assert first.proxy_port_override == 9091
    assert first.web_inspector is True
    assert first.wire_log_dir_override == "/tmp/wire_a"
    assert first.wire_log_max_pending == 64
    assert first.agent_id == "agent-a"
    assert first.role == "architect"
    assert first.agy_model == "model-a"
    assert first.local_model == "local-a"

    monkeypatch.setenv("HOLON_PROXY_PORT", "9092")
    monkeypatch.delenv("HOLON_COHERENCE_WEB")
    monkeypatch.setenv("WIRE_LOG_DIR", "/tmp/wire_b")
    monkeypatch.setenv("WIRE_LOG_MAX_PENDING", "128")
    monkeypatch.delenv("HOLON_AGENT_ID")
    monkeypatch.delenv("HOLON_ROLE")
    monkeypatch.delenv("AGY_MODEL")
    monkeypatch.delenv("HOLON_LOCAL_MODEL")
    second = CoherenceSettings.from_env()
    assert second.proxy_port == 9092
    assert second.proxy_port_override == 9092
    assert second.web_inspector is False
    assert second.wire_log_dir_override == "/tmp/wire_b"
    assert second.wire_log_max_pending == 128
    assert second.agent_id == DEFAULT_AGENT_ID
    assert second.role == DEFAULT_ROLE
    assert second.agy_model is None
    assert second.local_model is None


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
