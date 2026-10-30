"""Unit tests for mitmweb inspector token resolution, persistence, and CLI command."""

from __future__ import annotations

import argparse
import stat
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from holon_coherence.cli import main
from holon_coherence.commands.web_token import (
    get_active_web_token,
    handle,
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
        assert args_tok.handler == handle

        args_key = parser.parse_args(["web-key", "--name", "my-box"])
        assert args_key.command == "web-key"
        assert args_key.name == "my-box"
        assert args_key.handler == handle

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


class TestWebTokenAndDashboardAuth:
    """Tests for web dashboard token management and password protection."""

    def test_web_token_resolution_and_generation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 1. Explicit CLI argument
        assert resolve_web_password("explicit-cli-pwd") == "explicit-cli-pwd"

        # 2. Environment variable fallback
        monkeypatch.setenv("HOLON_COHERENCE_WEB_PASSWORD", "env-secret-password")
        assert resolve_web_password(None) == "env-secret-password"

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
        # Non-existent file
        assert get_active_web_token(token_path=str(tmp_path / "nonexistent")) is None

        # Empty or whitespace-only file
        empty_token = tmp_path / "empty"
        empty_token.write_text("   \n")
        assert get_active_web_token(token_path=str(empty_token)) is None

        # Unreadable file / OSError handling
        unreadable = tmp_path / "unreadable"
        unreadable.write_text("valid-token")
        with patch("builtins.open", side_effect=OSError("Disk error")):
            assert get_active_web_token(token_path=str(unreadable)) is None

    def test_start_web_command_forwards_web_password_in_container(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("holon_coherence.commands.start.is_in_container", lambda: True)
        launched: list[list[str]] = []

        def fake_run(cmd, *args, **kwargs):
            launched.append(list(cmd))
            return MagicMock(returncode=0)

        with (
            patch("holon_coherence.commands.start.save_web_token"),
            patch("subprocess.run", side_effect=fake_run),
        ):
            main(["start", "--port", "8080", "--web", "--web-password", "container-pwd"])

        assert len(launched) == 1
        cmd = launched[0]
        assert "--set" in cmd
        set_idx = cmd.index("--set") + 1
        assert cmd[set_idx] == "web_password=container-pwd"

    def test_start_web_command_forwards_web_password_on_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("holon_coherence.commands.start.is_in_container", lambda: False)
        with (
            patch("holon_coherence.commands.start.save_web_token"),
            patch("holon_coherence.commands.start.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.commands.start.ensure_docker_image"),
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch("subprocess.run") as mock_run,
        ):
            main(["start", "-d", "--web", "--web-password", "host-custom-pwd"])
            assert mock_run.call_count == 2
            docker_cmd = mock_run.call_args_list[1][0][0]
            assert "-e" in docker_cmd
            assert "HOLON_COHERENCE_WEB_PASSWORD=host-custom-pwd" in docker_cmd
            # Plaintext password must NOT be in container CLI tail arguments (SEC-01)
            tail_args = docker_cmd[docker_cmd.index("holon-coherence:latest") :]
            assert "--web-password" not in tail_args

    def test_status_command_displays_web_token(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("holon_coherence.commands.docker_ops.is_container_running", return_value=True),
            patch("holon_coherence.commands.endpoints.is_container_running", return_value=True),
            patch("holon_coherence.commands.endpoints.get_container_mapped_port", side_effect=lambda _name, port: port),
            patch("holon_coherence.commands.endpoints.get_container_web_token", return_value="active-session-tok"),
            patch("subprocess.run", return_value=MagicMock(returncode=0)),
            patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")),
        ):
            main(["status"])
            captured = capsys.readouterr()
            assert "mitmweb Req/Resp Inspector   : http://127.0.0.1:8081/?token=active-session-tok" in captured.out

    def test_status_command_when_down_displays_explicit_indicator(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("holon_coherence.commands.docker_ops.is_container_running", return_value=False),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value.returncode = 1
            main(["status"])
            captured = capsys.readouterr()
            assert "🔴 holon-coherence is down (not running)" in captured.out

    def test_status_command_when_docker_missing_does_not_crash(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("holon_coherence.commands.docker_ops.is_container_running", return_value=False),
            patch("subprocess.run", side_effect=FileNotFoundError("docker")),
        ):
            main(["status"])
            captured = capsys.readouterr()
            assert "🔴 holon-coherence is down (not running)" in captured.out

    def test_web_token_and_web_key_commands(self, capsys: pytest.CaptureFixture[str]) -> None:
        # Token exists: web-token
        with (
            patch("holon_coherence.commands.web_token.get_active_web_token", return_value="existing-key-999"),
            patch("holon_coherence.commands.web_token.is_container_running", return_value=False),
            pytest.raises(SystemExit) as exc,
        ):
            main(["web-token"])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "Last saved mitmweb inspector token" in captured.out
        assert "existing-key-999" in captured.out
        assert "Active mitmweb inspector token" not in captured.out
        assert "mitmweb inspector: not running" in captured.out
        assert "?token=" not in captured.out

        # Token exists: web-key alias
        with (
            patch("holon_coherence.commands.web_token.get_active_web_token", return_value="existing-key-999"),
            patch("holon_coherence.commands.web_token.is_container_running", return_value=False),
            pytest.raises(SystemExit) as exc,
        ):
            main(["web-key"])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "Last saved mitmweb inspector token" in captured.out
        assert "existing-key-999" in captured.out
        assert "Active mitmweb inspector token" not in captured.out
        assert "mitmweb inspector: not running" in captured.out
        assert "?token=" not in captured.out

        # Token missing
        with (
            patch("holon_coherence.commands.web_token.get_active_web_token", return_value=None),
            patch("holon_coherence.commands.web_token.is_container_running", return_value=False),
            pytest.raises(SystemExit) as exc,
        ):
            main(["web-token"])
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "No active mitmweb inspector token found" in captured.out
