from __future__ import annotations

import json
import logging
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

DEFAULT_CONTAINER_NAME = "holon-coherence-proxy"
DOCKER_CMD_TIMEOUT_SECONDS = 5.0
WEB_PASSWORD_ENV_VAR = "HOLON_COHERENCE_WEB_PASSWORD"
PROXY_CONTAINER_PORT = 8080
INSPECTOR_CONTAINER_PORT = 8081
ENDPOINT_LABEL_WIDTH = 28
ENDPOINT_TABLE_RULE_WIDTH = 64

PROXY_LABEL = "Proxy Listen Address"
DASHBOARD_LABEL = "Coherence Live Dashboard"
INSPECTOR_LABEL = "mitmweb Req/Resp Inspector"

logger = logging.getLogger(__name__)


def _resolve_container_name(container_name: str | None = None) -> str:
    return container_name or os.getenv("HOLON_CONTAINER_NAME", DEFAULT_CONTAINER_NAME)


def is_container_running(container_name: str | None = None) -> bool:
    name = _resolve_container_name(container_name)
    try:
        res = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", name],
            capture_output=True,
            text=True,
            timeout=DOCKER_CMD_TIMEOUT_SECONDS,
        )
        return res.returncode == 0 and res.stdout.strip().lower() == "true"
    except (subprocess.TimeoutExpired, OSError):
        return False


def get_container_mapped_port(
    container_name: str | None = None, container_port: int = PROXY_CONTAINER_PORT
) -> int | None:
    name = _resolve_container_name(container_name)
    try:
        res = subprocess.run(
            ["docker", "port", name, f"{container_port}/tcp"],
            capture_output=True,
            text=True,
            timeout=DOCKER_CMD_TIMEOUT_SECONDS,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            first_line = res.stdout.strip().splitlines()[0]
            port_str = first_line.split(":")[-1].strip()
            return int(port_str)
    except (subprocess.SubprocessError, OSError, ValueError) as exc:
        logger.debug("Failed to resolve mapped port for %s: %s", name, exc)
    return None


def get_container_web_token(container_name: str | None = None) -> str | None:
    name = _resolve_container_name(container_name)
    try:
        res = subprocess.run(
            ["docker", "inspect", "-f", "{{json .Config.Env}}", name],
            capture_output=True,
            text=True,
            timeout=DOCKER_CMD_TIMEOUT_SECONDS,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if res.returncode != 0:
        return None
    try:
        env = json.loads(res.stdout.strip() or "null")
    except ValueError:
        return None
    if not isinstance(env, list):
        return None
    prefix = f"{WEB_PASSWORD_ENV_VAR}="
    for entry in env:
        if isinstance(entry, str) and entry.startswith(prefix):
            return entry[len(prefix) :].strip() or None
    return None


@dataclass(frozen=True)
class ExposedEndpoints:
    proxy_port: int | None
    web_port: int | None
    web_token: str | None


def format_table_row(label: str, value: str, label_width: int = ENDPOINT_LABEL_WIDTH) -> str:
    return f"  {label:<{label_width}} : {value}"


def inspector_url(web_port: int, _token: str | None = None) -> str:
    return f"http://127.0.0.1:{web_port}/"


def token_recovery_command(container_name: str) -> str:
    return f"docker exec {container_name} sh -c 'cat \"$HOME/.holon/web-token\"'"


def resolve_container_endpoints(
    container_name: str,
    fallback_proxy_port: int | None = None,
    *,
    is_running_fn: Callable[[str], bool] | None = None,
    get_mapped_port_fn: Callable[[str, int], int | None] | None = None,
    get_token_fn: Callable[[str], str | None] | None = None,
) -> ExposedEndpoints:
    is_running = is_running_fn or is_container_running
    get_mapped_port = get_mapped_port_fn or get_container_mapped_port
    get_token = get_token_fn or get_container_web_token
    if not is_running(container_name):
        return ExposedEndpoints(proxy_port=None, web_port=None, web_token=None)

    proxy_port = get_mapped_port(container_name, PROXY_CONTAINER_PORT) or fallback_proxy_port
    web_port = get_mapped_port(container_name, INSPECTOR_CONTAINER_PORT)
    web_token = get_token(container_name) if web_port is not None else None
    return ExposedEndpoints(proxy_port=proxy_port, web_port=web_port, web_token=web_token)


def format_endpoint_rows(
    endpoints: ExposedEndpoints,
    label_width: int = ENDPOINT_LABEL_WIDTH,
    container_name: str = "<container>",
) -> list[str]:
    if endpoints.proxy_port is not None:
        proxy_value = f"127.0.0.1:{endpoints.proxy_port}"
        dashboard_value = f"http://127.0.0.1:{endpoints.proxy_port}/holon/"
    else:
        proxy_value = dashboard_value = "not running"

    if endpoints.web_port is not None and endpoints.web_token:
        inspector_value = (
            f"{inspector_url(endpoints.web_port)} (recover token with: {token_recovery_command(container_name)})"
        )
    elif endpoints.web_port is not None:
        inspector_value = (
            f"running on 127.0.0.1:{endpoints.web_port} (token unavailable; recover it with: "
            f"{token_recovery_command(container_name)})"
        )
    elif endpoints.proxy_port is not None:
        inspector_value = "not running (headless; enable with --web or HOLON_COHERENCE_WEB=1)"
    else:
        inspector_value = "not running"

    return [
        format_table_row(PROXY_LABEL, proxy_value, label_width),
        format_table_row(DASHBOARD_LABEL, dashboard_value, label_width),
        format_table_row(INSPECTOR_LABEL, inspector_value, label_width),
    ]


def print_endpoints(
    endpoints: ExposedEndpoints, header: str = "Exposed Endpoints", container_name: str = "<container>"
) -> None:
    print("-" * ENDPOINT_TABLE_RULE_WIDTH)
    print(f"  {header}")
    for row in format_endpoint_rows(endpoints, container_name=container_name):
        print(row)
    print("-" * ENDPOINT_TABLE_RULE_WIDTH)
