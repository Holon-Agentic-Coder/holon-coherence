from __future__ import annotations

import ast
from pathlib import Path

import pytest

from holon_coherence.commands import web_token as commands_web_token
from holon_coherence.container import web_token as container_web_token
from holon_coherence.container.web_token import (
    MITMPROXY_CONFDIR,
    MITMPROXY_CONFIG_FILENAME,
    WEB_PASSWORD_ENV_VAR,
    WEB_TOKEN_DIR_MODE,
    WEB_TOKEN_FILE_MODE,
    mitmweb_password_config,
    web_password_env_file,
    write_private_file,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTAINER_WEB_TOKEN_PATH = REPO_ROOT / "src" / "holon_coherence" / "container" / "web_token.py"


def test_container_web_token_has_zero_commands_imports() -> None:
    tree = ast.parse(CONTAINER_WEB_TOKEN_PATH.read_text(encoding="utf-8"), filename=str(CONTAINER_WEB_TOKEN_PATH))
    forbidden: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "commands" or alias.name.startswith(("commands.", "holon_coherence.commands")):
                    forbidden.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "commands" or module.startswith(("commands.", "holon_coherence.commands")):
                forbidden.append(module)
            elif module == "holon_coherence" and any(alias.name == "commands" for alias in node.names):
                forbidden.append("holon_coherence.commands")
    assert forbidden == []


def test_container_web_token_constants() -> None:
    assert WEB_TOKEN_DIR_MODE == 0o700
    assert WEB_TOKEN_FILE_MODE == 0o600
    assert WEB_PASSWORD_ENV_VAR == "HOLON_COHERENCE_WEB_PASSWORD"
    assert MITMPROXY_CONFDIR == "~/.mitmproxy"
    assert MITMPROXY_CONFIG_FILENAME == "config.yaml"


def test_write_private_file_creates_private_dir_and_hardens_mode(tmp_path: Path) -> None:
    private_dir = tmp_path / "nested" / "secrets"
    target = private_dir / "token.txt"

    returned = write_private_file(str(target), "initial-secret")
    assert returned == str(target)
    assert (private_dir.stat().st_mode & 0o777) == 0o700
    assert (target.stat().st_mode & 0o777) == 0o600
    assert target.read_text(encoding="utf-8") == "initial-secret"

    target.chmod(0o644)
    assert (target.stat().st_mode & 0o777) == 0o644
    write_private_file(str(target), "rotated-secret")
    assert (target.stat().st_mode & 0o777) == 0o600
    assert target.read_text(encoding="utf-8") == "rotated-secret"


def test_web_password_env_file_sanitizes_hardens_and_cleans_up() -> None:
    with web_password_env_file(None) as none_path:
        assert none_path is None

    with web_password_env_file("abc\r\ndef\n") as env_path:
        assert env_path is not None
        path_obj = Path(env_path)
        assert (path_obj.stat().st_mode & 0o777) == 0o600
        assert path_obj.read_text(encoding="utf-8") == "HOLON_COHERENCE_WEB_PASSWORD=abcdef\n"
    assert not path_obj.exists()

    leaked_path: Path | None = None
    with pytest.raises(RuntimeError), web_password_env_file("secret-on-error") as env_path:
        assert env_path is not None
        leaked_path = Path(env_path)
        assert leaked_path.exists()
        raise RuntimeError("boom")
    assert leaked_path is not None
    assert not leaked_path.exists()


def test_mitmweb_password_config_writes_escapes_and_restores(tmp_path: Path) -> None:
    confdir = tmp_path / "mitmproxy"
    with mitmweb_password_config(None, confdir=str(confdir)) as none_path:
        assert none_path is None
    assert not confdir.exists()

    special_pwd = 'a:b # "quoted"'
    with mitmweb_password_config(special_pwd, confdir=str(confdir)) as cfg_path:
        assert cfg_path is not None
        cfg = Path(cfg_path)
        assert (confdir.stat().st_mode & 0o777) == 0o700
        assert (cfg.stat().st_mode & 0o777) == 0o600
        assert cfg.read_text(encoding="utf-8") == 'web_password: "a:b # \\"quoted\\""\n'
    assert not cfg.exists()

    existing_cfg = confdir / MITMPROXY_CONFIG_FILENAME
    original = "anticache: true\nweb_password: old\n"
    existing_cfg.write_text(original, encoding="utf-8")
    with pytest.raises(RuntimeError), mitmweb_password_config("updated", confdir=str(confdir)) as cfg_path:
        assert cfg_path == str(existing_cfg)
        active = existing_cfg.read_text(encoding="utf-8")
        assert "anticache: true\n" in active
        assert 'web_password: "updated"\n' in active
        assert "web_password: old" not in active
        raise RuntimeError("abort")
    assert existing_cfg.read_text(encoding="utf-8") == original
    assert (existing_cfg.stat().st_mode & 0o777) == 0o600


def test_commands_web_token_reexports_container_web_token_symbols() -> None:
    assert commands_web_token.web_password_env_file is container_web_token.web_password_env_file
    assert commands_web_token.mitmweb_password_config is container_web_token.mitmweb_password_config
    assert commands_web_token.write_private_file is container_web_token.write_private_file
    assert commands_web_token.WEB_TOKEN_DIR_MODE == container_web_token.WEB_TOKEN_DIR_MODE
    assert commands_web_token.WEB_TOKEN_FILE_MODE == container_web_token.WEB_TOKEN_FILE_MODE
    assert commands_web_token.WEB_PASSWORD_ENV_VAR == container_web_token.WEB_PASSWORD_ENV_VAR
    assert commands_web_token.MITMPROXY_CONFDIR == container_web_token.MITMPROXY_CONFDIR
    assert commands_web_token.MITMPROXY_CONFIG_FILENAME == container_web_token.MITMPROXY_CONFIG_FILENAME
