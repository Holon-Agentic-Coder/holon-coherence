from __future__ import annotations

import argparse
import contextlib
import json
import os
import secrets
import tempfile
from collections.abc import Callable, Iterator
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
WEB_TOKEN_DIR_MODE = 0o700
WEB_TOKEN_FILE_MODE = 0o600
GENERATED_WEB_TOKEN_BYTES = 16
WEB_PASSWORD_ENV_VAR = "HOLON_COHERENCE_WEB_PASSWORD"
MITMPROXY_CONFDIR = "~/.mitmproxy"
MITMPROXY_CONFIG_FILENAME = "config.yaml"


def resolve_web_password(cli_password: str | None = None) -> str:
    if cli_password:
        return cli_password
    env_password = os.getenv(WEB_PASSWORD_ENV_VAR)
    if env_password:
        return env_password
    return secrets.token_urlsafe(GENERATED_WEB_TOKEN_BYTES)


def write_private_file(path: str, content: str) -> str:
    parent_dir = os.path.dirname(path)
    if parent_dir:
        os.makedirs(parent_dir, mode=WEB_TOKEN_DIR_MODE, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(parent_dir, WEB_TOKEN_DIR_MODE)

    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, WEB_TOKEN_FILE_MODE)
    try:
        with open(fd, "w", encoding="utf-8") as f:
            with contextlib.suppress(OSError, AttributeError):
                os.fchmod(f.fileno(), WEB_TOKEN_FILE_MODE)
            f.write(content)
    finally:
        with contextlib.suppress(OSError):
            os.chmod(path, WEB_TOKEN_FILE_MODE)
    return path


def save_web_token(token: str, token_path: str = WEB_TOKEN_PATH) -> str:
    return write_private_file(token_path, token.strip())


@contextlib.contextmanager
def web_password_env_file(web_password: str | None) -> Iterator[str | None]:
    if web_password is None:
        yield None
        return
    sanitized = web_password.replace("\r", "").replace("\n", "")
    fd, env_path = tempfile.mkstemp(prefix="holon-web-env-", suffix=".env")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f"{WEB_PASSWORD_ENV_VAR}={sanitized}\n")
        with contextlib.suppress(OSError):
            os.chmod(env_path, WEB_TOKEN_FILE_MODE)
        yield env_path
    finally:
        with contextlib.suppress(OSError):
            os.unlink(env_path)


@contextlib.contextmanager
def mitmweb_password_config(web_password: str | None, confdir: str = MITMPROXY_CONFDIR) -> Iterator[str | None]:
    if web_password is None:
        yield None
        return
    target_dir = os.path.expanduser(confdir)
    config_path = os.path.join(target_dir, MITMPROXY_CONFIG_FILENAME)
    previous: str | None = None
    if os.path.isfile(config_path):
        with contextlib.suppress(OSError), open(config_path, encoding="utf-8") as f:
            previous = f.read()
    kept_lines = [line for line in (previous or "").splitlines() if not line.lstrip().startswith("web_password:")]
    kept_lines.append(f"web_password: {json.dumps(web_password)}")
    write_private_file(config_path, "\n".join(kept_lines) + "\n")
    try:
        yield config_path
    finally:
        if previous is None:
            with contextlib.suppress(OSError):
                os.unlink(config_path)
        else:
            write_private_file(config_path, previous)


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
