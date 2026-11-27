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
    mitmweb_password_config,
    register,
    resolve_web_password,
    save_web_token,
    web_password_env_file,
    write_private_file,
)


class TestWebTokenHelpers:
    def test_resolve_web_password_priority(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_COHERENCE_WEB_PASSWORD", "env-pwd-123")
        assert resolve_web_password("cli-pwd-abc") == "cli-pwd-abc"

        assert resolve_web_password(None) == "env-pwd-123"

        monkeypatch.delenv("HOLON_COHERENCE_WEB_PASSWORD", raising=False)
        auto_token = resolve_web_password(None)
        assert isinstance(auto_token, str)
        assert len(auto_token) >= 16

    def test_web_token_file_persistence_and_permissions(self, tmp_path: Path) -> None:
        target_path = tmp_path / "subdir" / "web-token"
        saved = save_web_token("super-secret-token", token_path=str(target_path))
        assert saved == str(target_path)
        assert target_path.read_text().strip() == "super-secret-token"

        mode = target_path.stat().st_mode
        assert (mode & 0o777) == (stat.S_IRUSR | stat.S_IWUSR)
        assert (mode & 0o077) == 0

        retrieved = get_active_web_token(token_path=str(target_path))
        assert retrieved == "super-secret-token"

    def test_write_private_file_hardens_preexisting_permissive_file_before_write(self, tmp_path: Path) -> None:
        target = tmp_path / "existing-secret"
        target.write_text("stale", encoding="utf-8")
        target.chmod(0o644)

        events: list[tuple[str, int]] = []
        real_fchmod = __import__("os").fchmod

        def tracking_fchmod(fd: int, mode: int) -> None:
            events.append(("fchmod", mode))
            real_fchmod(fd, mode)

        real_open = open

        class _TrackingWriter:
            def __init__(self, inner: object) -> None:
                self._inner = inner

            def fileno(self) -> int:
                return self._inner.fileno()  # type: ignore[attr-defined]

            def write(self, data: str) -> int:
                events.append(("write", target.stat().st_mode & 0o777))
                return self._inner.write(data)  # type: ignore[attr-defined]

            def __enter__(self) -> _TrackingWriter:
                self._inner.__enter__()  # type: ignore[attr-defined]
                return self

            def __exit__(self, *args: object) -> None:
                self._inner.__exit__(*args)  # type: ignore[attr-defined]

        def tracking_open(file: object, *args: object, **kwargs: object) -> object:
            return _TrackingWriter(real_open(file, *args, **kwargs))  # type: ignore[call-overload]

        with (
            patch("holon_coherence.commands.web_token.os.fchmod", side_effect=tracking_fchmod),
            patch("builtins.open", side_effect=tracking_open),
        ):
            write_private_file(str(target), "fresh-secret")

        assert events == [("fchmod", 0o600), ("write", 0o600)]
        assert (target.stat().st_mode & 0o777) == 0o600
        assert target.read_text(encoding="utf-8") == "fresh-secret"

    def test_get_active_web_token_edge_cases(self, tmp_path: Path) -> None:
        assert get_active_web_token(token_path=str(tmp_path / "nonexistent")) is None

        empty_token = tmp_path / "empty"
        empty_token.write_text("   \n")
        assert get_active_web_token(token_path=str(empty_token)) is None

        unreadable = tmp_path / "unreadable"
        unreadable.write_text("valid-token")
        with patch("builtins.open", side_effect=OSError("Disk error")):
            assert get_active_web_token(token_path=str(unreadable)) is None

    def test_web_password_env_file_permissions_sanitization_and_cleanup(self) -> None:
        with web_password_env_file(None) as none_path:
            assert none_path is None

        with web_password_env_file("line1\r\nline2") as env_path:
            assert env_path is not None
            path_obj = Path(env_path)
            assert (path_obj.stat().st_mode & 0o777) == 0o600
            assert path_obj.read_text(encoding="utf-8") == "HOLON_COHERENCE_WEB_PASSWORD=line1line2\n"
        assert not path_obj.exists()

        leaked_path: Path | None = None
        with pytest.raises(RuntimeError), web_password_env_file("boom-secret") as env_path:
            assert env_path is not None
            leaked_path = Path(env_path)
            assert leaked_path.exists()
            raise RuntimeError("abort")
        assert leaked_path is not None
        assert not leaked_path.exists()

    def test_mitmweb_password_config_permissions_escaping_and_restore(self, tmp_path: Path) -> None:
        confdir = tmp_path / "mitm"
        with mitmweb_password_config(None, confdir=str(confdir)) as none_path:
            assert none_path is None
        assert not confdir.exists()

        special_pwd = 'p:w # "quoted"'
        with mitmweb_password_config(special_pwd, confdir=str(confdir)) as cfg_path:
            assert cfg_path is not None
            cfg = Path(cfg_path)
            assert (confdir.stat().st_mode & 0o777) == 0o700
            assert (cfg.stat().st_mode & 0o777) == 0o600
            assert cfg.read_text(encoding="utf-8") == 'web_password: "p:w # \\"quoted\\""\n'
        assert not cfg.exists()

        existing_cfg = confdir / "config.yaml"
        original_content = "anticache: true\nweb_password: old\n"
        existing_cfg.write_text(original_content, encoding="utf-8")
        with pytest.raises(RuntimeError), mitmweb_password_config("new-pwd", confdir=str(confdir)) as cfg_path:
            assert cfg_path == str(existing_cfg)
            active = existing_cfg.read_text(encoding="utf-8")
            assert "anticache: true\n" in active
            assert 'web_password: "new-pwd"\n' in active
            assert "web_password: old" not in active
            raise RuntimeError("interrupt")
        assert existing_cfg.read_text(encoding="utf-8") == original_content
        assert (existing_cfg.stat().st_mode & 0o777) == 0o600


class TestWebTokenRegistrationAndDispatch:
    def test_register_and_defaults(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        parsers = register(subparsers)
        assert len(parsers) == 2

        args_tok = parser.parse_args(["web-token", "--name", "my-box"])
        assert args_tok.command == "web-token"
        assert args_tok.name == "my-box"
        assert args_tok.handler == handle
        assert args_tok.propagates_exit is True

        args_key = parser.parse_args(["web-key", "--name", "my-box"])
        assert args_key.command == "web-key"
        assert args_key.name == "my-box"
        assert args_key.handler == handle
        assert args_key.propagates_exit is True

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
    def test_web_token_resolution_and_generation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert resolve_web_password("explicit-cli-pwd") == "explicit-cli-pwd"

        monkeypatch.setenv("HOLON_COHERENCE_WEB_PASSWORD", "env-secret-password")
        assert resolve_web_password(None) == "env-secret-password"

        monkeypatch.delenv("HOLON_COHERENCE_WEB_PASSWORD", raising=False)
        auto_token = resolve_web_password(None)
        assert isinstance(auto_token, str)
        assert len(auto_token) >= 16

    def test_web_token_file_persistence_and_permissions(self, tmp_path: Path) -> None:
        target_path = tmp_path / "subdir" / "web-token"
        saved = save_web_token("super-secret-token", token_path=str(target_path))
        assert saved == str(target_path)
        assert target_path.read_text().strip() == "super-secret-token"

        mode = target_path.stat().st_mode
        assert (mode & 0o777) == (stat.S_IRUSR | stat.S_IWUSR)
        assert (mode & 0o077) == 0

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

    def test_start_web_command_forwards_web_password_in_container(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setattr("holon_coherence.commands.start.is_in_container", lambda: True)
        launched: list[list[str]] = []
        config_path = tmp_path / ".mitmproxy" / "config.yaml"
        observed: dict[str, object] = {}

        def fake_run(cmd, *args, **kwargs):
            launched.append(list(cmd))
            observed["mode"] = config_path.stat().st_mode & 0o777
            observed["content"] = config_path.read_text(encoding="utf-8")
            return MagicMock(returncode=0)

        with (
            patch("holon_coherence.commands.start.save_web_token"),
            patch("subprocess.run", side_effect=fake_run),
        ):
            main(["start", "--port", "8080", "--web", "--web-password", "container-pwd"])

        assert len(launched) == 1
        cmd = launched[0]
        assert "web_password=container-pwd" not in cmd
        assert not any("container-pwd" in arg for arg in cmd)
        assert observed["mode"] == 0o600
        assert observed["content"] == 'web_password: "container-pwd"\n'
        assert not config_path.exists()

    def test_start_web_command_forwards_web_password_on_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("holon_coherence.commands.start.is_in_container", lambda: False)
        observed: dict[str, object] = {}

        def fake_run(cmd, *args, **kwargs):
            if cmd[:2] == ["docker", "run"]:
                observed["cmd"] = list(cmd)
                env_path = Path(cmd[cmd.index("--env-file") + 1])
                observed["env_path"] = env_path
                observed["mode"] = env_path.stat().st_mode & 0o777
                observed["content"] = env_path.read_text(encoding="utf-8")
            return MagicMock(returncode=0)

        with (
            patch("holon_coherence.commands.start.save_web_token"),
            patch("holon_coherence.container.lifecycle.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.container.lifecycle.ensure_docker_image"),
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch("subprocess.run", side_effect=fake_run) as mock_run,
        ):
            main(["start", "-d", "--web", "--web-password", "host-custom-pwd"])
            assert mock_run.call_count == 2
            docker_cmd = observed["cmd"]
            assert isinstance(docker_cmd, list)
            assert "--env-file" in docker_cmd
            assert "HOLON_COHERENCE_WEB_PASSWORD=host-custom-pwd" not in docker_cmd
            assert not any("host-custom-pwd" in arg for arg in docker_cmd)
            assert observed["mode"] == 0o600
            assert observed["content"] == "HOLON_COHERENCE_WEB_PASSWORD=host-custom-pwd\n"
            env_path = observed["env_path"]
            assert isinstance(env_path, Path)
            assert not env_path.exists()
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

        with (
            patch("holon_coherence.commands.web_token.get_active_web_token", return_value=None),
            patch("holon_coherence.commands.web_token.is_container_running", return_value=False),
            pytest.raises(SystemExit) as exc,
        ):
            main(["web-token"])
        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "No active mitmweb inspector token found" in captured.out
