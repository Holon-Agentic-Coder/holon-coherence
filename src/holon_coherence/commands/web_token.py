"""Web dashboard token management and credential persistence."""

from __future__ import annotations

import contextlib
import os
import secrets
from typing import Any

from holon_coherence.commands._dispatch import get_cli

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


def handle_web_token(args: Any = None, token_path: str = WEB_TOKEN_PATH) -> int:
    """Displays active web dashboard authentication token."""
    cli = get_cli()
    tok_getter = getattr(cli, "get_active_web_token", get_active_web_token)
    token = tok_getter(token_path)
    if token:
        print(f"🔑 Active web dashboard token: {token}")
        print("🌐 Access URL: http://127.0.0.1:8081 (or configured --web-port)")
        return 0
    print("No active web dashboard session token found.")
    print("Start the proxy with '--web' to generate one: holon-coherence start --web")
    return 1
