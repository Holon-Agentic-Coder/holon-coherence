from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from holon_coherence.cli import (
    SUPPORTED_AGENTS,
    check_docker_daemon,
    main,
    stop_proxy_container,
)

pytestmark = pytest.mark.integration_test

PROXY_IMAGE_NAME = "holon-coherence:latest"
TEST_PORT_BASE = 8900


@pytest.fixture(autouse=True)
def _docker_prerequisite() -> None:
    ok, err_msg = check_docker_daemon()
    if not ok:
        pytest.skip(f"Docker daemon unavailable: {err_msg}")


def _require_proxy_image_or_dockerfile() -> None:
    res = subprocess.run(
        ["docker", "image", "inspect", PROXY_IMAGE_NAME],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if res.returncode != 0 and not (Path(__file__).resolve().parents[1] / "Dockerfile").exists():
        pytest.skip(f"Docker image {PROXY_IMAGE_NAME} not available and no Dockerfile to build")


def _ensure_agent_binary_on_path(
    agent_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if shutil.which(agent_name) is not None:
        return
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    mock_script = bin_dir / agent_name
    mock_script.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then\n'
        f'    echo "Usage: {agent_name} [options]"\n'
        "    exit 0\n"
        "fi\n"
        "exit 0\n"
    )
    mock_script.chmod(mock_script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")


@pytest.mark.parametrize("agent_name", list(SUPPORTED_AGENTS))
def test_agent_runner_cold_start_help(
    agent_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_proxy_image_or_dockerfile()
    _ensure_agent_binary_on_path(agent_name, tmp_path, monkeypatch)

    agent_idx = list(SUPPORTED_AGENTS).index(agent_name)
    test_port = TEST_PORT_BASE + agent_idx
    container_name = f"holon-test-startup-{agent_name}"
    monkeypatch.setenv("HOLON_CONTAINER_NAME", container_name)
    monkeypatch.setenv("HOLON_PROXY_PORT", str(test_port))

    try:
        stop_proxy_container(container_name)

        from holon_coherence.container.lifecycle import ProxyLifecycle

        readiness: list[bool] = []
        real_wait = ProxyLifecycle.wait_until_ready

        def recording_wait(self: ProxyLifecycle, *args: float, **kwargs: float) -> bool:
            result = real_wait(self, *args, **kwargs)
            readiness.append(result)
            return result

        monkeypatch.setattr(ProxyLifecycle, "wait_until_ready", recording_wait)

        with pytest.raises(SystemExit) as exc_info:
            main([agent_name, "--ephemeral", "--", "--help"])

        assert exc_info.value.code == 0
        assert readiness == [True], "proxy container did not report ready before the agent ran"
    finally:
        stop_proxy_container(container_name)
