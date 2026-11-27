import contextlib
import http.server
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from collections.abc import Iterator
from typing import Any

import pytest

from holon_coherence.cli import main


def docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    res = subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return res.returncode == 0


def _remove_container_if_present(container_name: str) -> None:
    subprocess.run(["docker", "rm", "-f", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@contextlib.contextmanager
def _start_local_http_target() -> Iterator[int]:
    class _HealthHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = http.server.HTTPServer(("0.0.0.0", 0), _HealthHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _wait_for_http_proxy_forwarding(port: int, target_url: str, attempts: int = 20, delay_seconds: float = 0.5) -> bool:
    for _ in range(attempts):
        time.sleep(delay_seconds)
        try:
            proxy_handler = urllib.request.ProxyHandler({"http": f"http://127.0.0.1:{port}"})
            opener = urllib.request.build_opener(proxy_handler)
            req = urllib.request.Request(target_url, headers={"User-Agent": "coherence-test/1.0"})
            with opener.open(req, timeout=3) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            continue
    return False


def _is_container_running_exact(container_name: str) -> bool:
    ps_res = subprocess.run(
        ["docker", "ps", "-q", "--filter", f"name=^{container_name}$"],
        capture_output=True,
        text=True,
        check=True,
    )
    return len(ps_res.stdout.strip()) > 0


@pytest.fixture(autouse=True)
def _require_docker() -> None:
    if not docker_available():
        pytest.skip("Docker is not installed or daemon is not running.")


@pytest.mark.integration_test
def test_docker_image_cli_help() -> None:
    cmd = ["docker", "run", "--rm", "holon-coherence:latest", "--help"]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    assert res.returncode == 0
    assert "High-coherence, low-entropy optimization gateway" in res.stdout
    assert "start" in res.stdout


@pytest.mark.integration_test
def test_docker_proxy_container_lifecycle_and_traffic() -> None:
    container_name = "test-coherence-integration"
    port = 18092

    _remove_container_if_present(container_name)

    with _start_local_http_target() as target_port:
        cmd = [
            "docker",
            "run",
            "-d",
            "--name",
            container_name,
            "--add-host=host.docker.internal:host-gateway",
            "-p",
            f"127.0.0.1:{port}:8080",
            "-e",
            "HOLON_IN_CONTAINER=1",
            "holon-coherence:latest",
            "start",
            "--port",
            "8080",
        ]
        start_res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        assert start_res.returncode == 0

        try:
            target_url = f"http://host.docker.internal:{target_port}/health"
            ready = _wait_for_http_proxy_forwarding(port, target_url)
            assert ready, "Proxy container failed to service HTTP requests within 10 seconds."
        finally:
            _remove_container_if_present(container_name)


@pytest.mark.integration_test
def test_cli_docker_wrapper_start_and_stop() -> None:
    sandbox_container = "test-holon-coherence-sandbox"
    orig_argv = sys.argv
    orig_container_env = os.environ.get("HOLON_CONTAINER_NAME")
    os.environ["HOLON_CONTAINER_NAME"] = sandbox_container

    _remove_container_if_present(sandbox_container)

    try:
        sys.argv = ["holon-coherence", "start", "-d", "--port", "18095", "--name", sandbox_container]
        main()

        assert _is_container_running_exact(sandbox_container), "Sandbox container was not detected running."

        sys.argv = ["holon-coherence", "stop", "--name", sandbox_container]
        main()

        time.sleep(1)
        assert not _is_container_running_exact(sandbox_container), "Sandbox container should not be running after stop."
    finally:
        sys.argv = orig_argv
        if orig_container_env is not None:
            os.environ["HOLON_CONTAINER_NAME"] = orig_container_env
        else:
            os.environ.pop("HOLON_CONTAINER_NAME", None)
        _remove_container_if_present(sandbox_container)
