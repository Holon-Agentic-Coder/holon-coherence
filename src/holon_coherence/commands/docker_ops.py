"""Docker operations and container lifecycle management."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Any

from holon_coherence.commands._dispatch import get_cli
from holon_coherence.commands.web_token import get_active_web_token

DEFAULT_CONTAINER_NAME = "holon-coherence-proxy"
CONTAINER_NAME = DEFAULT_CONTAINER_NAME
DOCKER_BUILD_TIMEOUT_SECONDS = 600


def get_container_name(override: str | None = None) -> str:
    """Return configured Docker container name respecting override or HOLON_CONTAINER_NAME."""
    if override:
        return override
    return os.getenv("HOLON_CONTAINER_NAME", DEFAULT_CONTAINER_NAME)


def is_container_running(container_name: str | None = None) -> bool:
    """Check if the Docker container is currently running."""
    name = container_name or get_container_name()
    try:
        res = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", name],
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        return res.returncode == 0 and res.stdout.strip().lower() == "true"
    except (subprocess.TimeoutExpired, OSError):
        return False


def is_container_bound_to_port(port: int, container_name: str | None = None) -> bool:
    """Check if the container is currently running and bound to the specified host port."""
    name = container_name or get_container_name()
    try:
        res = subprocess.run(
            ["docker", "port", name, "8080/tcp"],
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
                ["docker", "port", name],
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


def stop_proxy_container(container_name: str | None = None) -> None:
    """Stop and remove the holon-coherence background Docker container on demand."""
    target_container = container_name or get_container_name()
    is_default = target_container in (DEFAULT_CONTAINER_NAME, "holon-coherence")
    display_name = "holon-coherence" if is_default else target_container
    print(f"🛑 Stopping and removing {display_name} Docker container...")
    try:
        res = subprocess.run(
            ["docker", "rm", "-f", target_container],
            capture_output=True,
            text=True,
        )
        if res.returncode == 0:
            print(f"✅ {display_name} container stopped and removed.")
        elif "no such container" in (res.stderr or "").lower():
            print(f"✅ No active {display_name} container found.")
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
    target_container = getattr(args, "name", None) or get_container_name()
    cli = get_cli()
    stopper = getattr(cli, "stop_proxy_container", stop_proxy_container)
    stopper(target_container)
    return 0


def get_container_mapped_port(container_name: str | None = None, container_port: int = 8080) -> int | None:
    """Return the host port mapped to the specified container TCP port."""
    name = container_name or get_container_name()
    try:
        res = subprocess.run(
            ["docker", "port", name, f"{container_port}/tcp"],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            first_line = res.stdout.strip().splitlines()[0]
            port_str = first_line.split(":")[-1].strip()
            return int(port_str)
    except Exception:
        pass
    return None


def handle_status(args: Any = None) -> int:
    """Check status of holon-coherence Docker container."""
    target_container = getattr(args, "name", None) or get_container_name()
    is_default = target_container in (DEFAULT_CONTAINER_NAME, "holon-coherence")
    display_name = "holon-coherence" if is_default else target_container
    cli = get_cli()
    is_running = getattr(cli, "is_container_running", is_container_running)
    get_token = getattr(cli, "get_active_web_token", get_active_web_token)
    get_mapped_port = getattr(cli, "get_container_mapped_port", get_container_mapped_port)
    try:
        res = subprocess.run(["docker", "ps", "-a", "--filter", f"name=^{target_container}$"])
        retcode = res.returncode
    except (subprocess.SubprocessError, OSError):
        retcode = 1
    token = get_token()

    if not is_running(target_container):
        print(f"\n🔴 {display_name} is down (not running).")
        return retcode

    web_port = get_mapped_port(target_container, 8081)
    if token and web_port:
        print(f"\n🔑 Web Dashboard Token: {token}")
        print(f"🌐 Access URL: http://127.0.0.1:{web_port}/?token={token}")

    proxy_port = get_mapped_port(target_container, 8080)
    if proxy_port is None:
        proxy_port_str = os.getenv("HOLON_PROXY_PORT", "8080")
        try:
            proxy_port = int(proxy_port_str)
        except ValueError:
            proxy_port = 8080

    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{proxy_port}/holon/api/metrics",
            headers={"User-Agent": "holon-coherence-cli"},
        )
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                hit_rate = data.get("cache_hit_rate", 0.0) * 100
                pruned = data.get("tool_calls_pruned", 0)
                reduced = data.get("tokens_reduced", 0)
                tps = data.get("avg_decode_throughput_tps", 0.0)
                prefill_tps = data.get("avg_prefill_throughput_tps", 0.0)
                print("\n📊 Optimization Metrics Summary:")
                print(
                    f"   Tool Calls Saved: {pruned:,} | Tokens Reduced: {reduced:,} | "
                    f"Cache Hit Rate: {hit_rate:.1f}% | Prefill: {prefill_tps:.1f} t/s | Output: {tps:.1f} t/s"
                )
                print(f"   🌐 Live Dashboard: http://127.0.0.1:{proxy_port}/holon/")
    except Exception:
        pass
    return retcode


def handle_logs(args: Any) -> int:
    """View logs of holon-coherence Docker container."""
    target_container = getattr(args, "name", None) or get_container_name()
    cmd = ["docker", "logs"]
    if getattr(args, "follow", False):
        cmd.append("-f")
    cmd.append(target_container)
    res = subprocess.run(cmd)
    return res.returncode
