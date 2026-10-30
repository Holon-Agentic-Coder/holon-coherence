"""Unit tests for mitmweb inspector token resolution, persistence, and CLI command."""

from __future__ import annotations

import argparse
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from holon_coherence.commands.web_token import (
    WEB_TOKEN_PATH,
    get_active_web_token,
    handle,
    handle_web_token,
    register,
    resolve_web_password,
    save_web_token,
)


class TestWebTokenHelpers:
    """Tests for token password resolution and file storage."""

    def test_resolve_web_password_priority(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 1. CLI explicit argument takes highest priority
        monkeypatch.setenv("HOLON_COHERENCE_WEB_PASSWORD", "env-pwd-123")
        assert resolve_web_password("cli-pwd-abc") == "cli-pwd-abc"

        # 2. Environment variable fallback
        assert resolve_web_password(None) == "env-pwd-123"

        # 3. Auto-generation fallback
        monkeypatch.delenv("HOLON_COHERENCE_WEB_PASSWORD", raising=False)
        auto_token = resolve_web_password(None)
        assert isinstance(auto_token, str)
        assert len(auto_token) >= 16

    def test_web_token_file_persistence_and_permissions(self, tmp_path: Path) -> None:
        target_path = tmp_path / "subdir" / "web-token"
        saved = save_web_token("super-secret-token", token_path=str(target_path))
        assert saved == str(target_path)
        assert target_path.read_text().strip() == "super-secret-token"

        # POSIX file permissions must be 0600
        mode = target_path.stat().st_mode
        assert (mode & 0o777) == (stat.S_IRUSR | stat.S_IWUSR)
        assert (mode & 0o077) == 0

        # Retrieval helper
        retrieved = get_active_web_token(token_path=str(target_path))
        assert retrieved == "super-secret-token"

    def test_get_active_web_token_edge_cases(self, tmp_path: Path) -> None:
        assert get_active_web_token(token_path=str(tmp_path / "nonexistent")) is None

        empty_token = tmp_path / "empty"
        empty_token.write_text("   \n")
        assert get_active_web_token(token_path=str(empty_token)) is None

        unreadable = tmp_path / "unreadable"
        unreadable.write_text("valid-token")
        with patch("builtins.open", side_effect=OSError("Disk error")):
            assert get_active_web_token(token_path=str(unreadable)) is None


class TestWebTokenRegistrationAndDispatch:
    """Tests for web-token and web-key subparsers registration and handle execution."""

    def test_register_and_defaults(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        parsers = register(subparsers)
        assert len(parsers) == 2

        args_tok = parser.parse_args(["web-token", "--name", "my-box"])
        assert args_tok.command == "web-token"
        assert args_tok.name == "my-box"
        assert getattr(args_tok, "handler") == handle

        args_key = parser.parse_args(["web-key", "--name", "my-box"])
        assert args_key.command == "web-key"
        assert args_key.name == "my-box"
        assert getattr(args_key, "handler") == handle

    def test_handle_web_token_saved_token(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = argparse.Namespace(name=None)
        with (
            patch("holon_coherence.commands.web_token.get_active_web_token", return_value="saved-tok-456"),
            patch("holon_coherence.commands.web_token.is_container_running", return_value=False),
        ):
            res = handle(args)
            assert res == 0
            out = capsys.readouterr().out
            assert "Last saved mitmweb inspector token" in out
            assert "saved-tok-456" in out

    def test_handle_web_token_container_token(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = argparse.Namespace(name="box")
        with (
            patch("holon_coherence.commands.web_token.is_container_running", return_value=True),
            patch("holon_coherence.commands.web_token.get_container_mapped_port", return_value=8081),
            patch("holon_coherence.commands.web_token.get_container_web_token", return_value="live-tok-789"),
        ):
            res = handle(args)
            assert res == 0
            out = capsys.readouterr().out
            assert "Active mitmweb inspector token: live-tok-789" in out
            assert "http://127.0.0.1:8081/?token=live-tok-789" in out

    def test_handle_web_token_missing(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = argparse.Namespace(name=None)
        with (
            patch("holon_coherence.commands.web_token.is_container_running", return_value=False),
            patch("holon_coherence.commands.web_token.get_active_web_token", return_value=None),
        ):
            res = handle(args)
            assert res == 1
            out = capsys.readouterr().out
            assert "No active mitmweb inspector token found." in out
