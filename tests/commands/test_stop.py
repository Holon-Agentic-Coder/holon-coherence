from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

import pytest

from holon_coherence.cli import main
from holon_coherence.commands import docker_ops, stop
from holon_coherence.container.lifecycle import ProxyLifecycle


class TestStopCommand:
    def test_register_and_defaults(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        stop.register(subparsers)
        args = parser.parse_args(["stop", "--name", "my-box"])
        assert args.command == "stop"
        assert args.name == "my-box"
        assert args.handler == stop.handle

    def test_handle_stop_uses_injected_stopper(self) -> None:
        stopper = MagicMock(return_value=False)
        assert stop.handle_stop(argparse.Namespace(name="box"), stopper_fn=stopper) == 0
        stopper.assert_called_once_with("box")

    def test_handle_stop_defaults_to_configured_container(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_CONTAINER_NAME", "env-box")
        with patch.object(ProxyLifecycle, "stop", return_value=True) as mock_stop:
            assert stop.handle(argparse.Namespace(name=None)) == 0
        mock_stop.assert_called_once_with("env-box")

    def test_cli_stop_runs_docker_rm(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            main(["stop", "--name", "sandbox-custom"])
        mock_run.assert_called_once_with(["docker", "rm", "-f", "sandbox-custom"], capture_output=True, text=True)
        assert "sandbox-custom container stopped and removed" in capsys.readouterr().out

    def test_docker_ops_compatibility_exports(self) -> None:
        assert docker_ops.handle_stop is stop.handle_stop
        with patch.object(ProxyLifecycle, "stop", return_value=True) as mock_stop:
            assert docker_ops.stop_proxy_container("box") is None
        mock_stop.assert_called_once_with("box")
