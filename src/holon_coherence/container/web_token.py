from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections.abc import Iterator

WEB_TOKEN_DIR_MODE = 0o700
WEB_TOKEN_FILE_MODE = 0o600
WEB_PASSWORD_ENV_VAR = "HOLON_COHERENCE_WEB_PASSWORD"
MITMPROXY_CONFDIR = "~/.mitmproxy"
MITMPROXY_CONFIG_FILENAME = "config.yaml"


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
