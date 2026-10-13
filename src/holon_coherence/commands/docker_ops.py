"""Docker operations and container lifecycle management."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Any

from holon_coherence.commands._dispatch import get_cli
from holon_coherence.commands.web_token import get_active_web_token

CONTAINER_NAME = "holon-coherence-proxy"
DOCKER_BUILD_TIMEOUT_SECONDS = 600


def is_container_running(container_name: str = CONTAINER_NAME) -> bool:
    """Check if the Docker container is currently running."""
    try:
        res = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        return res.returncode == 0 and res.stdout.strip().lower() == "true"
    except (subprocess.TimeoutExpired, OSError):
        return False


def is_container_bound_to_port(port: int, container_name: str = CONTAINER_NAME) -> bool:
    """Check if the container is currently running and bound to the specified host port."""
    try:
        res = subprocess.run(
            ["docker", "port", container_name, "8080/tcp"],
            capture_output=True,
            text=True,
            timeout=5.0,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    output = res.stdout
    if res.returncode != 0 or not output.strip():
        try:
            fallback_res = subprocess.run(
                ["docker", "port", container_name],
                capture_output=True,
                text=True,
                timeout=5.0,
            )
        except (subprocess.TimeoutExpired, OSError):
            return False
        if fallback_res.returncode != 0:
            return False
        output = fallback_res.stdout

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        host_part = line.split("->")[-1].strip()
        if ":" in host_part:
            try:
                mapped_port = int(host_part.rsplit(":", 1)[1])
                if mapped_port == port:
                    return True
            except ValueError:
                continue
    return False


def check_docker_daemon() -> tuple[bool, str]:
    """Check Docker CLI and daemon status with clean diagnostics."""
    if not shutil.which("docker"):
        return (
            False,
            "Error: Docker CLI is not installed or not found on PATH.\n"
            "Please install Docker to run the holon-coherence optimization proxy container.",
        )
    try:
        res = subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5.0,
        )
        if res.returncode != 0:
            return (
                False,
                "Error: Docker daemon is not running.\n"
                "Please start Docker Desktop or the Docker daemon to enable the optimization proxy.",
            )
    except subprocess.TimeoutExpired:
        return (
            False,
            "Error: Docker daemon connection timed out.\n"
            "Please ensure Docker Desktop or the Docker daemon is responding.",
        )
    return True, ""


def ensure_docker_image(image: str, rebuild: bool = False) -> None:
    """Ensure the Docker image exists locally, building or pulling from registry/GHCR if needed."""
    if not rebuild:
        img_check = subprocess.run(
            ["docker", "image", "inspect", image],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if img_check.returncode == 0:
            return

    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    dockerfile = os.path.join(repo_root, "Dockerfile")
    if os.path.exists(dockerfile):
        print(f"🔨 Building Docker image '{image}' from {dockerfile}...")
        try:
            build_res = subprocess.run(
                ["docker", "build", "-t", image, repo_root],
                timeout=DOCKER_BUILD_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            print(
                f"Error: Docker build timed out after {DOCKER_BUILD_TIMEOUT_SECONDS}s. "
                "Check your Docker daemon or network connection.",
                file=sys.stderr,
            )
            sys.exit(1)
        if build_res.returncode != 0:
            print(f"Error: Failed to build Docker image '{image}'.", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"📥 Pulling Docker image '{image}'...")
        try:
            pull_res = subprocess.run(
                ["docker", "pull", image],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=DOCKER_BUILD_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            print(
                f"Error: Docker pull timed out after {DOCKER_BUILD_TIMEOUT_SECONDS}s.",
                file=sys.stderr,
            )
            sys.exit(1)
        if pull_res.returncode != 0:
            if "/" not in image:
                ghcr_img = f"ghcr.io/holon-agentic-coder/{image}"
                print(f"📥 Attempting pull from {ghcr_img}...")
                try:
                    ghcr_res = subprocess.run(
                        ["docker", "pull", ghcr_img],
                        timeout=DOCKER_BUILD_TIMEOUT_SECONDS,
                    )
                except subprocess.TimeoutExpired:
                    print(
                        f"Error: Docker pull from GHCR timed out after {DOCKER_BUILD_TIMEOUT_SECONDS}s.",
                        file=sys.stderr,
                    )
                    sys.exit(1)
                if ghcr_res.returncode != 0:
                    print(
                        f"Error: Could not find or pull Docker image '{image}' or '{ghcr_img}'.\n"
                        "Please verify your network connection or build the image locally.",
                        file=sys.stderr,
                    )
                    sys.exit(1)
                try:
                    tag_res = subprocess.run(
                        ["docker", "tag", ghcr_img, image],
                        timeout=30,
                    )
                except subprocess.TimeoutExpired:
                    print(
                        "Error: Docker tag timed out after 30s.",
                        file=sys.stderr,
                    )
                    sys.exit(1)
                if tag_res.returncode != 0:
                    print(f"Error: Failed to tag Docker image '{ghcr_img}' as '{image}'.", file=sys.stderr)
                    sys.exit(1)
            else:
                print(
                    f"Error: Could not find or pull Docker image '{image}'.\n"
                    "Please verify your network connection or build the image locally.",
                    file=sys.stderr,
                )
                sys.exit(1)


def stop_proxy_container() -> None:
    """Stop and remove the holon-coherence background Docker container on demand."""
    print("🛑 Stopping and removing holon-coherence Docker container...")
    try:
        res = subprocess.run(
            ["docker", "rm", "-f", CONTAINER_NAME],
            capture_output=True,
            text=True,
        )
        if res.returncode == 0:
            print("✅ holon-coherence container stopped and removed.")
        elif "no such container" in (res.stderr or "").lower():
            print("✅ No active holon-coherence container found.")
        else:
            print(f"⚠️  Failed to remove container: {res.stderr.strip()}")
    except OSError as e:
        print(f"⚠️  Failed to remove container: {e}")


def handle_build(args: Any) -> int:
    """Build the holon-coherence Docker image."""
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    dockerfile = os.path.join(repo_root, "Dockerfile")
    if not os.path.exists(dockerfile):
        print(f"Error: Dockerfile not found at {dockerfile}.", file=sys.stderr)
        sys.exit(1)
    print(f"🐳 Building Docker image {args.tag}...")
    subprocess.run(["docker", "build", "-t", args.tag, repo_root], check=True)
    print(f"✅ Docker image '{args.tag}' built successfully.")
    return 0


def handle_stop(args: Any = None) -> int:
    """Stop and remove running holon-coherence Docker container."""
    cli = get_cli()
    stopper = getattr(cli, "stop_proxy_container", stop_proxy_container)
    stopper()
    return 0


def handle_status(args: Any = None) -> int:
    """Check status of holon-coherence Docker container."""
    cli = get_cli()
    is_running = getattr(cli, "is_container_running", is_container_running)
    get_token = getattr(cli, "get_active_web_token", get_active_web_token)
    res = subprocess.run(["docker", "ps", "-a", "--filter", f"name={CONTAINER_NAME}"])
    token = get_token()
    if token and is_running():
        print(f"\n🔑 Web Dashboard Token: {token}")
        print("🌐 Access URL: http://127.0.0.1:8081 (or configured --web-port)")
    return res.returncode


def handle_logs(args: Any) -> int:
    """View logs of holon-coherence Docker container."""
    cmd = ["docker", "logs"]
    if getattr(args, "follow", False):
        cmd.append("-f")
    cmd.append(CONTAINER_NAME)
    res = subprocess.run(cmd)
    return res.returncode
