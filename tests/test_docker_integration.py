import os
import shutil
import subprocess
import sys
import time
import unittest
import urllib.request

import pytest

from holon_coherence.cli import main


def docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    res = subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return res.returncode == 0


def _remove_container_if_present(container_name: str) -> None:
    subprocess.run(["docker", "rm", "-f", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _wait_for_http_proxy_forwarding(port: int, attempts: int = 20, delay_seconds: float = 0.5) -> bool:
    for _ in range(attempts):
        time.sleep(delay_seconds)
        try:
            proxy_handler = urllib.request.ProxyHandler({"http": f"http://127.0.0.1:{port}"})
            opener = urllib.request.build_opener(proxy_handler)
            req = urllib.request.Request("http://example.com", headers={"User-Agent": "coherence-test/1.0"})
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


@pytest.mark.integration_test
class TestDockerIntegration(unittest.TestCase):
    def setUp(self):
        if not docker_available():
            self.skipTest("Docker is not installed or daemon is not running.")

    def test_docker_image_cli_help(self):
        cmd = ["docker", "run", "--rm", "holon-coherence:latest", "--help"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        self.assertEqual(res.returncode, 0)
        self.assertIn("High-coherence, low-entropy optimization gateway", res.stdout)
        self.assertIn("start", res.stdout)

    def test_docker_proxy_container_lifecycle_and_traffic(self):
        container_name = "test-coherence-integration"
        port = 18092

        _remove_container_if_present(container_name)

        cmd = [
            "docker",
            "run",
            "-d",
            "--name",
            container_name,
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
        self.assertEqual(start_res.returncode, 0)

        try:
            ready = _wait_for_http_proxy_forwarding(port)
            self.assertTrue(ready, "Proxy container failed to service HTTP requests within 10 seconds.")
        finally:
            _remove_container_if_present(container_name)

    def test_cli_docker_wrapper_start_and_stop(self):
        sandbox_container = "test-holon-coherence-sandbox"
        orig_argv = sys.argv
        orig_container_env = os.environ.get("HOLON_CONTAINER_NAME")
        os.environ["HOLON_CONTAINER_NAME"] = sandbox_container

        _remove_container_if_present(sandbox_container)

        try:
            sys.argv = ["holon-coherence", "start", "-d", "--port", "18095", "--name", sandbox_container]
            main()

            self.assertTrue(
                _is_container_running_exact(sandbox_container),
                "Sandbox container was not detected running.",
            )

            sys.argv = ["holon-coherence", "stop", "--name", sandbox_container]
            main()

            time.sleep(1)
            self.assertFalse(
                _is_container_running_exact(sandbox_container),
                "Sandbox container should not be running after stop.",
            )
        finally:
            sys.argv = orig_argv
            if orig_container_env is not None:
                os.environ["HOLON_CONTAINER_NAME"] = orig_container_env
            else:
                os.environ.pop("HOLON_CONTAINER_NAME", None)
            _remove_container_if_present(sandbox_container)


if __name__ == "__main__":
    unittest.main()
