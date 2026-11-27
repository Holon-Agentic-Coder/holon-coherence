from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from holon_coherence.cli import main
from holon_coherence.commands.start import ensure_proxy_running


def _free_ports(port: int, host: str = "127.0.0.1") -> bool:
    return False


class TestMitmwebInspectorDefault:
    @staticmethod
    def _host_start(
        argv: list[str],
        in_use: Any = _free_ports,
        token: str = "tok123",
        env_capture: dict[str, Any] | None = None,
    ) -> tuple[list[str], MagicMock, MagicMock]:
        def fake_run(cmd: list[str], *args: Any, **kwargs: Any) -> MagicMock:
            if env_capture is not None and "--env-file" in cmd:
                env_path = Path(cmd[cmd.index("--env-file") + 1])
                env_capture["path"] = env_path
                env_capture["mode"] = stat.S_IMODE(os.stat(env_path).st_mode)
                env_capture["content"] = env_path.read_text(encoding="utf-8")
            return MagicMock(returncode=0)

        with (
            patch("holon_coherence.commands.start.is_in_container", return_value=False),
            patch("holon_coherence.container.lifecycle.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.commands.start.is_port_in_use", side_effect=in_use),
            patch("holon_coherence.container.lifecycle.is_port_in_use", side_effect=in_use),
            patch("holon_coherence.commands.start.resolve_web_password", return_value=token) as mock_resolve,
            patch("holon_coherence.commands.start.save_web_token") as mock_save,
            patch("holon_coherence.container.lifecycle.ensure_docker_image"),
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch("subprocess.run", side_effect=fake_run) as mock_run,
        ):
            main(argv)
        return mock_run.call_args_list[-1][0][0], mock_resolve, mock_save

    @staticmethod
    def _in_container_start(
        argv: list[str],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path | None = None,
        config_capture: dict[str, Any] | None = None,
    ) -> list[str]:
        launched: list[list[str]] = []
        if tmp_path is not None:
            monkeypatch.setenv("HOME", str(tmp_path))

        def fake_run(cmd: list[str], *args: Any, **kwargs: Any) -> MagicMock:
            launched.append(list(cmd))
            if tmp_path is not None and config_capture is not None:
                cfg = tmp_path / ".mitmproxy" / "config.yaml"
                if cfg.exists():
                    config_capture["path"] = cfg
                    config_capture["mode"] = stat.S_IMODE(os.stat(cfg).st_mode)
                    config_capture["content"] = cfg.read_text(encoding="utf-8")
            return MagicMock(returncode=0)

        monkeypatch.setattr("holon_coherence.commands.start.is_in_container", lambda: True)
        with (
            patch("holon_coherence.commands.start.resolve_web_password", return_value="tok123"),
            patch("holon_coherence.commands.start.save_web_token"),
            patch("subprocess.run", side_effect=fake_run),
        ):
            main(argv)
        assert len(launched) == 1, "no Docker command may run inside the container"
        return launched[0]

    def test_start_web_selects_mitmweb_and_passes_token(self) -> None:
        env_capture: dict[str, Any] = {}
        docker_cmd, mock_resolve, mock_save = self._host_start(["start", "-d", "--web"], env_capture=env_capture)

        assert "127.0.0.1:8081:8081" in docker_cmd
        assert "--env-file" in docker_cmd
        assert "HOLON_COHERENCE_WEB_PASSWORD=tok123" not in docker_cmd
        assert not any("tok123" in arg for arg in docker_cmd)
        assert env_capture["mode"] == 0o600
        assert env_capture["content"] == "HOLON_COHERENCE_WEB_PASSWORD=tok123\n"
        assert not env_capture["path"].exists()
        tail = docker_cmd[docker_cmd.index("holon-coherence:latest") :]
        assert tail == ["holon-coherence:latest", "start", "--port", "8080", "--web", "--web-port", "8081"]
        mock_resolve.assert_called_once_with(None)
        mock_save.assert_called_once_with("tok123")

    def test_start_web_binds_inspector_to_loopback_only(self) -> None:
        docker_cmd, _resolve, _save = self._host_start(["start", "-d", "--web"])
        mappings = [docker_cmd[i + 1] for i, arg in enumerate(docker_cmd) if arg == "-p"]
        assert mappings and all(mapping.startswith("127.0.0.1:") for mapping in mappings)

    @pytest.mark.parametrize("argv", [["start", "-d"], ["start", "-d", "--no-web"]])
    def test_start_default_and_no_web_select_mitmdump(self, argv: list[str]) -> None:
        docker_cmd, mock_resolve, mock_save = self._host_start(argv)

        assert not any(arg.endswith(":8081") for arg in docker_cmd)
        assert not any(arg.startswith("HOLON_COHERENCE_WEB_PASSWORD=") for arg in docker_cmd)
        tail = docker_cmd[docker_cmd.index("holon-coherence:latest") :]
        assert tail == ["holon-coherence:latest", "start", "--port", "8080"]
        mock_resolve.assert_not_called()
        mock_save.assert_not_called()

    @pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
    def test_start_env_opt_in_selects_mitmweb(self, value: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_COHERENCE_WEB", value)
        docker_cmd, _resolve, mock_save = self._host_start(["start", "-d"])
        assert "127.0.0.1:8081:8081" in docker_cmd
        assert docker_cmd[-3:] == ["--web", "--web-port", "8081"]
        mock_save.assert_called_once_with("tok123")

    @pytest.mark.parametrize("value", ["", "0", "false", "off"])
    def test_start_env_falsy_stays_headless(self, value: str, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_COHERENCE_WEB", value)
        docker_cmd, _resolve, _save = self._host_start(["start", "-d"])
        assert "--web" not in docker_cmd

    def test_start_no_web_overrides_env_opt_in(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_COHERENCE_WEB", "1")
        docker_cmd, mock_resolve, _save = self._host_start(["start", "-d", "--no-web"])
        assert "--web" not in docker_cmd
        mock_resolve.assert_not_called()

    @pytest.mark.parametrize("env_value", [None, "0"])
    def test_start_web_password_alone_implies_inspector(
        self, env_value: str | None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        if env_value is not None:
            monkeypatch.setenv("HOLON_COHERENCE_WEB", env_value)
        docker_cmd, mock_resolve, mock_save = self._host_start(["start", "-d", "--web-password", "pw-secret"])

        assert "127.0.0.1:8081:8081" in docker_cmd
        assert docker_cmd[-3:] == ["--web", "--web-port", "8081"]
        mock_resolve.assert_called_once_with("pw-secret")
        mock_save.assert_called_once_with("tok123")
        assert "pw-secret" not in capsys.readouterr().err

    def test_start_no_web_with_web_password_warns_without_leaking(self, capsys: pytest.CaptureFixture[str]) -> None:
        docker_cmd, mock_resolve, mock_save = self._host_start(
            ["start", "-d", "--no-web", "--web-password", "pw-secret"]
        )

        assert "--web" not in docker_cmd
        assert not any(arg.startswith("HOLON_COHERENCE_WEB_PASSWORD=") for arg in docker_cmd)
        mock_resolve.assert_not_called()
        mock_save.assert_not_called()
        captured = capsys.readouterr()
        assert "--web-password is ignored because --no-web disables the mitmweb inspector" in captured.err
        assert "pw-secret" not in captured.out + captured.err

    def test_in_container_web_password_alone_runs_mitmweb(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cmd = self._in_container_start(
            ["start", "--port", "8080", "--web-password", "pw-secret"], monkeypatch, tmp_path
        )
        assert cmd[0].endswith("mitmweb")

    def test_web_password_env_var_does_not_imply_inspector(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_COHERENCE_WEB_PASSWORD", "env-secret")
        docker_cmd, mock_resolve, _save = self._host_start(["start", "-d"])
        assert "--web" not in docker_cmd
        mock_resolve.assert_not_called()

    def test_start_web_inspector_port_falls_back(self, capsys: pytest.CaptureFixture[str]) -> None:
        docker_cmd, _resolve, _save = self._host_start(
            ["start", "-d", "--web"], in_use=lambda port, host="127.0.0.1": port == 8081
        )

        assert "127.0.0.1:8082:8081" in docker_cmd
        assert "127.0.0.1:8080:8080" in docker_cmd
        out = capsys.readouterr().out
        assert "Mapping mitmweb inspector to host port 8082 instead." in out
        assert (
            "http://127.0.0.1:8082/ "
            "(recover token with: docker exec <container> sh -c 'cat \"$HOME/.holon/web-token\"')"
        ) in out
        assert "?token=" not in out
        assert "tok123" not in out

    def test_start_custom_inspector_port_falls_back(self) -> None:
        docker_cmd, _resolve, _save = self._host_start(
            ["start", "-d", "--web", "--web-port", "9090"], in_use=lambda port, host="127.0.0.1": port == 9090
        )
        assert "127.0.0.1:9091:8081" in docker_cmd

    def test_start_inspector_fallback_skips_local_llm_port(self) -> None:
        docker_cmd, _resolve, _save = self._host_start(
            ["start", "-d", "--web", "--local-llm-base", "localhost:8082"],
            in_use=lambda port, host="127.0.0.1": port == 8081,
        )
        assert "127.0.0.1:8083:8081" in docker_cmd
        assert not any(arg == "127.0.0.1:8082:8081" for arg in docker_cmd)

    def test_start_inspector_never_lands_on_the_requested_local_llm_port(self) -> None:
        docker_cmd, _resolve, _save = self._host_start(["start", "-d", "--web", "--local-llm-base", "localhost:8081"])
        assert "127.0.0.1:8082:8081" in docker_cmd

    def test_start_prints_all_endpoints(self, capsys: pytest.CaptureFixture[str]) -> None:
        self._host_start(["start", "-d", "--web"])
        out = capsys.readouterr().out
        assert "Proxy Listen Address         : 127.0.0.1:8080" in out
        assert "Coherence Live Dashboard     : http://127.0.0.1:8080/holon/" in out
        assert (
            "mitmweb Req/Resp Inspector   : http://127.0.0.1:8081/ "
            "(recover token with: docker exec <container> sh -c 'cat \"$HOME/.holon/web-token\"')"
        ) in out
        assert "?token=" not in out
        assert "tok123" not in out
        assert "Web API Key" not in out

    @pytest.mark.parametrize("argv", [["start", "-d"], ["start", "-d", "--no-web"]])
    def test_start_headless_reports_inspector_not_running(
        self, argv: list[str], capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._host_start(argv)
        out = capsys.readouterr().out
        assert "Proxy Listen Address         : 127.0.0.1:8080" in out
        assert "mitmweb Req/Resp Inspector   : not running (headless; enable with --web or HOLON_COHERENCE_WEB=1)" in (
            out
        )
        assert "?token=" not in out

    def test_in_container_web_runs_mitmweb_with_password_without_printing_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config_capture: dict[str, Any] = {}
        cmd = self._in_container_start(
            ["start", "--port", "8080", "--web", "--web-port", "8081"],
            monkeypatch,
            tmp_path,
            config_capture=config_capture,
        )

        assert cmd[0].endswith("mitmweb")
        assert cmd[cmd.index("--web-host") + 1] == "0.0.0.0"
        assert cmd[cmd.index("--web-port") + 1] == "8081"
        set_values = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "--set"]
        assert set_values == ["web_open_browser=false"]
        assert "web_password=tok123" not in cmd
        assert not any("tok123" in arg for arg in cmd)
        assert config_capture["mode"] == 0o600
        assert 'web_password: "tok123"' in config_capture["content"]
        assert not config_capture["path"].exists()
        out = capsys.readouterr().out
        assert "tok123" not in out
        assert "mitmweb inspector listening on container port 8081" in out
        assert "docker exec <container> sh -c 'cat \"$HOME/.holon/web-token\"'" in out

    def test_in_container_no_web_runs_mitmdump(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cmd = self._in_container_start(["start", "--port", "8080", "--no-web"], monkeypatch)
        assert cmd[0].endswith("mitmdump")
        assert not any("web_password" in arg for arg in cmd)

    def test_in_container_default_stays_headless(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cmd = self._in_container_start(["start", "--port", "8080"], monkeypatch)
        assert cmd[0].endswith("mitmdump")
        assert "--web-port" not in cmd

    def test_in_container_ignores_env_opt_in(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_COHERENCE_WEB", "1")
        cmd = self._in_container_start(["start", "--port", "8080"], monkeypatch)
        assert cmd[0].endswith("mitmdump")

    def test_ensure_proxy_running_stays_headless(self) -> None:
        with (
            patch("holon_coherence.container.lifecycle.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.container.lifecycle.is_port_in_use", return_value=False),
            patch("holon_coherence.container.lifecycle.is_container_running", return_value=False),
            patch("holon_coherence.commands.start.resolve_web_password") as mock_resolve,
            patch("os.makedirs"),
            patch("os.path.exists", return_value=True),
            patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run,
            patch("holon_coherence.container.lifecycle.ProxyLifecycle.wait_until_ready", return_value=True),
        ):
            assert ensure_proxy_running(port=8080) is True
        docker_cmd = mock_run.call_args_list[-1][0][0]
        assert "--web" not in docker_cmd
        assert not any(arg.endswith(":8081") for arg in docker_cmd)
        assert not any(arg.startswith("HOLON_COHERENCE_WEB_PASSWORD=") for arg in docker_cmd)
        mock_resolve.assert_not_called()

    def test_ensure_proxy_running_enforces_private_ca_permissions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        ca_dir = tmp_path / ".holon" / "proxy-ca"
        ca_dir.mkdir(parents=True)
        os.chmod(ca_dir, 0o777)
        (ca_dir / "mitmproxy-ca-cert.pem").write_text("cert")
        (ca_dir / "mitmproxy-ca.pem").write_text("pem")
        (ca_dir / "holon-root-ca.key").write_text("key")
        os.chmod(ca_dir / "mitmproxy-ca.pem", 0o666)
        os.chmod(ca_dir / "holon-root-ca.key", 0o666)

        with (
            patch("holon_coherence.container.lifecycle.check_docker_daemon", return_value=(True, "")),
            patch("holon_coherence.container.lifecycle.is_port_in_use", return_value=False),
            patch("holon_coherence.container.lifecycle.is_container_running", return_value=False),
            patch("holon_coherence.container.lifecycle.ensure_docker_image"),
            patch("subprocess.run", return_value=MagicMock(returncode=0)),
            patch("holon_coherence.container.lifecycle.ProxyLifecycle.wait_until_ready", return_value=True),
        ):
            assert ensure_proxy_running(port=8080) is True

        for d in (ca_dir, tmp_path / ".holon" / "cache", tmp_path / ".holon" / "logs"):
            assert stat.S_IMODE(os.stat(d).st_mode) == 0o700
        assert stat.S_IMODE(os.stat(ca_dir / "mitmproxy-ca.pem").st_mode) == 0o600
        assert stat.S_IMODE(os.stat(ca_dir / "holon-root-ca.key").st_mode) == 0o600
