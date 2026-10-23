"""Exposed endpoint resolution and reporting shared by ``start``, ``status`` and ``metrics`` (Bean 0129).

Every command that tells the user where the proxy lives prints the same three rows: the proxy listen
address, the Coherence live dashboard under ``/holon/`` and the plain mitmweb raw request/response
inspector. Ports are always the host ports actually resolved (after any fallback), never the
requested defaults, and an inspector that is not running is reported as such rather than with a
stale URL from ``~/.holon/web-token``. The inspector token is read from the container's own
environment, so with several named containers each URL carries the token that container accepts.
"""

from __future__ import annotations

from dataclasses import dataclass

from holon_coherence.commands._dispatch import get_cli
from holon_coherence.commands.docker_ops import (
    get_container_mapped_port,
    get_container_web_token,
    is_container_running,
)

PROXY_CONTAINER_PORT = 8080
INSPECTOR_CONTAINER_PORT = 8081
ENDPOINT_LABEL_WIDTH = 28

PROXY_LABEL = "Proxy Listen Address"
DASHBOARD_LABEL = "Coherence Live Dashboard"
INSPECTOR_LABEL = "mitmweb Req/Resp Inspector"


@dataclass(frozen=True)
class ExposedEndpoints:
    """Host ports (and the inspector token) a proxy session exposes; ``None`` means not running."""

    proxy_port: int | None
    web_port: int | None
    web_token: str | None


def format_table_row(label: str, value: str, label_width: int = ENDPOINT_LABEL_WIDTH) -> str:
    """Format a ``label : value`` row in the terminal table style used by ``metrics``."""
    return f"  {label:<{label_width}} : {value}"


def inspector_url(web_port: int, token: str) -> str:
    """Return the token-authenticated mitmweb inspector URL for a host port."""
    return f"http://127.0.0.1:{web_port}/?token={token}"


def resolve_container_endpoints(container_name: str, fallback_proxy_port: int | None = None) -> ExposedEndpoints:
    """Resolve the endpoints a proxy container really exposes from its Docker port mappings.

    A container that is not running exposes nothing. A running container without an inspector port
    mapping is a headless (mitmdump-only) start, so no token is read and no inspector URL is built.
    The token comes from the container itself, never from the shared ``~/.holon/web-token``, which
    every host ``start`` overwrites regardless of ``--name``.
    """
    cli = get_cli()
    is_running = getattr(cli, "is_container_running", is_container_running)
    get_mapped_port = getattr(cli, "get_container_mapped_port", get_container_mapped_port)
    get_token = getattr(cli, "get_container_web_token", get_container_web_token)

    if not is_running(container_name):
        return ExposedEndpoints(proxy_port=None, web_port=None, web_token=None)

    proxy_port = get_mapped_port(container_name, PROXY_CONTAINER_PORT) or fallback_proxy_port
    web_port = get_mapped_port(container_name, INSPECTOR_CONTAINER_PORT)
    web_token = get_token(container_name) if web_port is not None else None
    return ExposedEndpoints(proxy_port=proxy_port, web_port=web_port, web_token=web_token)


def format_endpoint_rows(endpoints: ExposedEndpoints, label_width: int = ENDPOINT_LABEL_WIDTH) -> list[str]:
    """Render the proxy, Coherence dashboard and mitmweb inspector rows for terminal output."""
    if endpoints.proxy_port is not None:
        proxy_value = f"127.0.0.1:{endpoints.proxy_port}"
        dashboard_value = f"http://127.0.0.1:{endpoints.proxy_port}/holon/"
    else:
        proxy_value = dashboard_value = "not running"

    if endpoints.web_port is not None and endpoints.web_token:
        inspector_value = inspector_url(endpoints.web_port, endpoints.web_token)
    elif endpoints.web_port is not None:
        inspector_value = (
            f"running on 127.0.0.1:{endpoints.web_port} (token unavailable; run 'holon-coherence web-token')"
        )
    elif endpoints.proxy_port is not None:
        inspector_value = "not running (headless start or --no-web)"
    else:
        inspector_value = "not running"

    return [
        format_table_row(PROXY_LABEL, proxy_value, label_width),
        format_table_row(DASHBOARD_LABEL, dashboard_value, label_width),
        format_table_row(INSPECTOR_LABEL, inspector_value, label_width),
    ]


def print_endpoints(endpoints: ExposedEndpoints, header: str = "Exposed Endpoints") -> None:
    """Print the endpoint rows framed by a rule, as ``start`` and ``status`` report them."""
    print("-" * 64)
    print(f"  {header}")
    for row in format_endpoint_rows(endpoints):
        print(row)
    print("-" * 64)
