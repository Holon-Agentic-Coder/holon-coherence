import shutil
import subprocess
import time
import unittest
import urllib.request

import pytest


def docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    res = subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return res.returncode == 0


@pytest.mark.integration_test
class TestDockerIntegration(unittest.TestCase):
    def setUp(self):
        if not docker_available():
            self.skipTest("Docker is not installed or daemon is not running.")

    def test_docker_image_cli_help(self):
        """Verify that running the Docker image directly executes holon-coherence --help."""
        cmd = ["docker", "run", "--rm", "holon-coherence:latest", "--help"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        self.assertEqual(res.returncode, 0)
        self.assertIn("High-coherence, low-entropy optimization gateway", res.stdout)
        self.assertIn("start", res.stdout)

    def test_docker_proxy_container_lifecycle_and_traffic(self):
        """Verify container launches, binds proxy port, forwards HTTP traffic, and stops cleanly."""
        container_name = "test-coherence-integration"
        port = 18092

        # Clean any preexisting container
        subprocess.run(["docker", "rm", "-f", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Run container
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
            # Wait for proxy port to become ready (up to 10 seconds)
            ready = False
            for _ in range(20):
                time.sleep(0.5)
                try:
                    proxy_handler = urllib.request.ProxyHandler({"http": f"http://127.0.0.1:{port}"})
                    opener = urllib.request.build_opener(proxy_handler)
                    req = urllib.request.Request("http://example.com", headers={"User-Agent": "coherence-test/1.0"})
                    with opener.open(req, timeout=3) as resp:
                        if resp.status == 200:
                            ready = True
                            break
                except Exception:
                    continue

            self.assertTrue(ready, "Proxy container failed to service HTTP requests within 10 seconds.")
        finally:
            subprocess.run(["docker", "rm", "-f", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def test_cli_docker_wrapper_start_and_stop(self):
        """Verify holon-coherence start -d and stop manage the container correctly."""
        import sys

        from holon_coherence.cli import main

        # Test start -d on custom port 18095
        orig_argv = sys.argv
        try:
            sys.argv = ["holon-coherence", "start", "-d", "--port", "18095"]
            main()

            # Verify container is running
            ps_res = subprocess.run(
                ["docker", "ps", "-q", "--filter", "name=holon-coherence"], capture_output=True, text=True, check=True
            )
            self.assertTrue(len(ps_res.stdout.strip()) > 0, "holon-coherence container was not detected running.")

            # Stop container
            sys.argv = ["holon-coherence", "stop"]
            main()

            time.sleep(1)
            ps_after = subprocess.run(
                ["docker", "ps", "-q", "--filter", "name=holon-coherence"], capture_output=True, text=True, check=True
            )
            self.assertEqual(len(ps_after.stdout.strip()), 0, "Container should not be running after stop.")
        finally:
            sys.argv = orig_argv
            subprocess.run(
                ["docker", "rm", "-f", "holon-coherence"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )


if __name__ == "__main__":
    unittest.main()
