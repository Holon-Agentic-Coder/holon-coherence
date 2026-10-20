"""Integration tests for cold-start execution of supported agent runners."""

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


@pytest.fixture(autouse=True)
def _docker_prerequisite() -> None:
    """Ensure Docker daemon is operational before running startup integration tests."""
    ok, err_msg = check_docker_daemon()
    if not ok:
        pytest.skip(f"Docker daemon unavailable: {err_msg}")


@pytest.mark.parametrize("agent_name", list(SUPPORTED_AGENTS))
def test_agent_runner_cold_start_help(
    agent_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify cold-start execution of supported agent runners boots the proxy container cleanly."""
    # Ensure Docker image is inspectable or buildable
    res = subprocess.run(
        ["docker", "image", "inspect", "holon-coherence:latest"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if res.returncode != 0 and not os.path.exists("Dockerfile"):
        pytest.skip("Docker image holon-coherence:latest not available and no Dockerfile to build")

    # If the real binary is missing on host, create a dummy mock executable on PATH
    if shutil.which(agent_name) is None:
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

    agent_idx = list(SUPPORTED_AGENTS).index(agent_name)
    test_port = 8900 + agent_idx
    container_name = f"holon-test-startup-{agent_name}"
    monkeypatch.setenv("HOLON_CONTAINER_NAME", container_name)
    monkeypatch.setenv("HOLON_PROXY_PORT", str(test_port))

    try:
        stop_proxy_container(container_name)

        # Launch agent runner with --ephemeral and -- --help
        with pytest.raises(SystemExit) as exc_info:
            main([agent_name, "--ephemeral", "--", "--help"])

        assert exc_info.value.code == 0
    finally:
        stop_proxy_container(container_name)
