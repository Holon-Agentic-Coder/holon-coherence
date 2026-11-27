from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

TRUTHY_VALUES = frozenset({"1", "true", "yes", "on"})
FALSY_VALUES = frozenset({"0", "false", "no", "off"})

DEFAULT_PROXY_PORT = 8080
MIN_PORT = 1
MAX_PORT = 65535
DEFAULT_CONTAINER_NAME = "holon-coherence-proxy"
DEFAULT_ARCHITECT_MODEL = "claude-3-5-sonnet"
DEFAULT_EXECUTOR_MODEL = "gemini-3.5-flash"
DEFAULT_CACHE_DIR = "~/.holon/cache"
DEFAULT_WIRE_LOG_DIR = "~/.holon/logs"
DEFAULT_WIRE_LOG_MAX_PENDING = 256
DEFAULT_AGENT_ID = "agy"
DEFAULT_AGENT_ROLE = "executor"


def parse_bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in TRUTHY_VALUES:
        return True
    if normalized in FALSY_VALUES:
        return False
    return default


def parse_optional_port(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        value = int(raw.strip())
    except ValueError:
        return None
    if MIN_PORT <= value <= MAX_PORT:
        return value
    return None


def parse_port(raw: str | None, default: int) -> int:
    parsed = parse_optional_port(raw)
    return default if parsed is None else parsed


def parse_non_negative_int(raw: str | None, default: int) -> int:
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        return default
    return value if value >= 0 else default


def parse_optional_str(raw: str | None) -> str | None:
    if raw is None:
        return None
    stripped = raw.strip()
    return stripped or None


def parse_str(raw: str | None, default: str) -> str:
    return parse_optional_str(raw) or default


def parse_optional_path(raw: str | None) -> Path | None:
    value = parse_optional_str(raw)
    if value is None:
        return None
    return Path(os.path.expanduser(value))


def parse_path(raw: str | None, default: str) -> Path:
    return parse_optional_path(raw) or Path(os.path.expanduser(default))


@dataclass(frozen=True, slots=True)
class CoherenceSettings:
    web_password: str | None = None
    api_token: str | None = None
    web_inspector: bool = False
    proxy_port: int = DEFAULT_PROXY_PORT
    proxy_port_override: int | None = None
    container_name: str = DEFAULT_CONTAINER_NAME
    in_container: bool = False
    token_reduction: bool = True
    passive_monitoring: bool = False
    enable_wire_logging: bool = True
    ca_cert: Path | None = None
    cache_dir: Path = field(default_factory=lambda: Path(os.path.expanduser(DEFAULT_CACHE_DIR)))
    wire_log_dir: Path = field(default_factory=lambda: Path(os.path.expanduser(DEFAULT_WIRE_LOG_DIR)))
    wire_log_dir_override: str | None = None
    wire_log_max_pending: int = DEFAULT_WIRE_LOG_MAX_PENDING
    wire_log_base_dir: Path | None = None
    agent_id: str = DEFAULT_AGENT_ID
    agent_role: str = DEFAULT_AGENT_ROLE
    agy_model: str | None = None
    local_model: str | None = None
    local_llm_base: str | None = None
    architect_model: str = DEFAULT_ARCHITECT_MODEL
    executor_model: str = DEFAULT_EXECUTOR_MODEL
    no_proxy: str | None = None
    no_proxy_lower: str | None = None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> CoherenceSettings:
        env = os.environ if environ is None else environ
        proxy_port_override = parse_optional_port(env.get("HOLON_PROXY_PORT"))
        return cls(
            web_password=parse_optional_str(env.get("HOLON_COHERENCE_WEB_PASSWORD")),
            api_token=parse_optional_str(env.get("HOLON_COHERENCE_API_TOKEN")),
            web_inspector=parse_bool(env.get("HOLON_COHERENCE_WEB"), False),
            proxy_port=DEFAULT_PROXY_PORT if proxy_port_override is None else proxy_port_override,
            proxy_port_override=proxy_port_override,
            container_name=parse_str(env.get("HOLON_CONTAINER_NAME"), DEFAULT_CONTAINER_NAME),
            in_container=parse_bool(env.get("HOLON_IN_CONTAINER"), False),
            token_reduction=parse_bool(env.get("COHERENCE_TOKEN_REDUCTION"), True),
            passive_monitoring=parse_bool(env.get("HOLON_PASSIVE_MONITORING"), False),
            enable_wire_logging=parse_bool(env.get("ENABLE_WIRE_LOGGING"), True),
            ca_cert=parse_optional_path(env.get("HOLON_CA_CERT")),
            cache_dir=parse_path(env.get("CACHE_DIR"), DEFAULT_CACHE_DIR),
            wire_log_dir=parse_path(env.get("WIRE_LOG_DIR"), DEFAULT_WIRE_LOG_DIR),
            wire_log_dir_override=parse_optional_str(env.get("WIRE_LOG_DIR")),
            wire_log_max_pending=parse_non_negative_int(env.get("WIRE_LOG_MAX_PENDING"), DEFAULT_WIRE_LOG_MAX_PENDING),
            wire_log_base_dir=parse_optional_path(env.get("HOLON_WIRE_LOG_BASE_DIR")),
            agent_id=parse_str(env.get("HOLON_AGENT_ID"), DEFAULT_AGENT_ID),
            agent_role=parse_str(env.get("HOLON_ROLE"), DEFAULT_AGENT_ROLE),
            agy_model=parse_optional_str(env.get("AGY_MODEL")),
            local_model=parse_optional_str(env.get("HOLON_LOCAL_MODEL")),
            local_llm_base=parse_optional_str(env.get("HOLON_LOCAL_LLM_BASE")),
            architect_model=parse_str(env.get("HOLON_ARCHITECT_MODEL"), DEFAULT_ARCHITECT_MODEL),
            executor_model=parse_str(env.get("HOLON_EXECUTOR_MODEL"), DEFAULT_EXECUTOR_MODEL),
            no_proxy=parse_optional_str(env.get("NO_PROXY")),
            no_proxy_lower=parse_optional_str(env.get("no_proxy")),
        )
