from __future__ import annotations

import argparse
import os
import secrets
from collections.abc import Callable
from typing import Any

from holon_coherence.commands.docker_ops import (
    get_container_mapped_port,
    get_container_name,
    get_container_web_token,
    is_container_running,
)
from holon_coherence.commands.endpoints import (
    INSPECTOR_CONTAINER_PORT,
    INSPECTOR_LABEL,
    inspector_url,
    token_recovery_command,
)
from holon_coherence.container.web_token import (
    MITMPROXY_CONFDIR as MITMPROXY_CONFDIR,
)
from holon_coherence.container.web_token import (
    MITMPROXY_CONFIG_FILENAME as MITMPROXY_CONFIG_FILENAME,
)
from holon_coherence.container.web_token import (
    WEB_PASSWORD_ENV_VAR as WEB_PASSWORD_ENV_VAR,
)
from holon_coherence.container.web_token import (
    WEB_TOKEN_DIR_MODE as WEB_TOKEN_DIR_MODE,
)
from holon_coherence.container.web_token import (
    WEB_TOKEN_FILE_MODE as WEB_TOKEN_FILE_MODE,
)
from holon_coherence.container.web_token import (
    mitmweb_password_config as mitmweb_password_config,
)
from holon_coherence.container.web_token import (
    web_password_env_file as web_password_env_file,
)
from holon_coherence.container.web_token import (
    write_private_file as write_private_file,
)
from holon_coherence.settings import CoherenceSettings

WEB_TOKEN_PATH = os.path.expanduser("~/.holon/web-token")
GENERATED_WEB_TOKEN_BYTES = 16


def resolve_web_password(cli_password: str | None = None) -> str:
    if cli_password:
        return cli_password
    env_password = CoherenceSettings.from_env().web_password
    if env_password:
        return env_password
    return secrets.token_urlsafe(GENERATED_WEB_TOKEN_BYTES)


def save_web_token(token: str, token_path: str = WEB_TOKEN_PATH) -> str:
    return write_private_file(token_path, token.strip())


def get_active_web_token(token_path: str = WEB_TOKEN_PATH) -> str | None:
    if os.path.isfile(token_path):
        try:
            with open(token_path) as f:
                content = f.read().strip()
                if content:
                    return content
        except OSError:
            return None
    return None


def handle_web_token(  # noqa: PLR0913
    args: Any = None,
    token_path: str = WEB_TOKEN_PATH,
    *,
    tok_getter_fn: Callable[[str], str | None] | None = None,
    container_tok_getter_fn: Callable[[str], str | None] | None = None,
    is_running_fn: Callable[[str], bool] | None = None,
    get_mapped_port_fn: Callable[[str, int], int | None] | None = None,
) -> int:
    tok_getter = tok_getter_fn or get_active_web_token
    container_tok_getter = container_tok_getter_fn or get_container_web_token
    is_running = is_running_fn or is_container_running
    get_mapped_port = get_mapped_port_fn or get_container_mapped_port
    name = getattr(args, "name", None) or get_container_name()
    web_port = get_mapped_port(name, INSPECTOR_CONTAINER_PORT) if is_running(name) else None
    if web_port is not None:
        container_token = container_tok_getter(name)
        if container_token:
            print(f"🔑 Active mitmweb inspector token: {container_token}")
            print(f"🌐 {INSPECTOR_LABEL}: {inspector_url(web_port, container_token)}")
            return 0
        print(f"🌐 mitmweb inspector: running on 127.0.0.1:{web_port} (token unavailable for container '{name}')")
        print(f"   Recover the token the container saved with: {token_recovery_command(name)}")
        return 1
    token = tok_getter(token_path)
    if token:
        print(f"🔑 Last saved mitmweb inspector token ({token_path}): {token}")
        print(
            f"🌐 mitmweb inspector: not running for container '{name}' (start it with 'holon-coherence start --web', "
            "or pass --name for another container)"
        )
        return 0
    print("No active mitmweb inspector token found.")
    print("Start the proxy with 'holon-coherence start --web' (or HOLON_COHERENCE_WEB=1) to generate one.")
    return 1


def handle(args: Any) -> int:
    return handle_web_token(args)


def register(subparsers: Any) -> list[argparse.ArgumentParser]:
    parsers = []
    for token_command, token_help in (
        ("web-token", "Display the active mitmweb inspector token and URL"),
        ("web-key", "Alias for web-token"),
    ):
        token_parser = subparsers.add_parser(token_command, help=token_help)
        token_parser.add_argument(
            "--name",
            default=None,
            help="Container name (defaults to HOLON_CONTAINER_NAME or holon-coherence-proxy)",
        )
        token_parser.set_defaults(handler=handle, propagates_exit=True)
        parsers.append(token_parser)
    return parsers
