"""mitmweb inspector token management and credential persistence."""

from __future__ import annotations

import argparse
import contextlib
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

WEB_TOKEN_PATH = os.path.expanduser("~/.holon/web-token")


def resolve_web_password(cli_password: str | None = None) -> str:
    """Resolves web password from CLI argument, environment, or generates a secure token."""
    if cli_password:
        return cli_password
    env_password = os.getenv("HOLON_COHERENCE_WEB_PASSWORD")
    if env_password:
        return env_password
    return secrets.token_urlsafe(16)


def save_web_token(token: str, token_path: str = WEB_TOKEN_PATH) -> str:
    """Persists web dashboard token to disk with strict 0600 POSIX permissions."""
    token_dir = os.path.dirname(token_path)
    if token_dir:
        os.makedirs(token_dir, mode=0o700, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(token_dir, 0o700)

    fd = os.open(token_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        with open(fd, "w") as f:
            f.write(token.strip())
    finally:
        with contextlib.suppress(OSError):
            os.chmod(token_path, 0o600)
    return token_path


def get_active_web_token(token_path: str = WEB_TOKEN_PATH) -> str | None:
    """Reads active web token from disk if present and readable."""
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
    """Displays the active mitmweb inspector token and, when it is running, its resolved URL."""
    tok_getter = tok_getter_fn or get_active_web_token
    container_tok_getter = container_tok_getter_fn or get_container_web_token
    is_running = is_running_fn or is_container_running
    get_mapped_port = get_mapped_port_fn or get_container_mapped_port
    name = getattr(args, "name", None) or get_container_name()
    web_port = get_mapped_port(name, INSPECTOR_CONTAINER_PORT) if is_running(name) else None
    if web_port is not None:
        # A running inspector accepts only its own container's token, not the last-written file.
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
    """Handle web-token and web-key commands."""
    return handle_web_token(args)


def register(subparsers: Any) -> list[argparse.ArgumentParser]:
    """Register web-token and web-key subparsers."""
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
