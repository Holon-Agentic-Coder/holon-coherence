from __future__ import annotations

import argparse
import http.client
import json
import logging
import os
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from holon_coherence.commands.stop import handle_stop
from holon_coherence.container.image import DOCKER_BUILD_TIMEOUT_SECONDS, ensure_docker_image
from holon_coherence.container.lifecycle import (
    DEFAULT_CONTAINER_NAME,
    ProxyLifecycle,
    check_docker_daemon,
    get_container_name,
    is_container_bound_to_port,
    is_container_running,
)

if TYPE_CHECKING:
    from holon_coherence.commands.endpoints import ExposedEndpoints

__all__ = [
    "CONTAINER_NAME",
    "DEFAULT_CONTAINER_NAME",
    "DOCKER_BUILD_TIMEOUT_SECONDS",
    "WEB_PASSWORD_ENV_VAR",
    "check_docker_daemon",
    "ensure_docker_image",
    "get_container_mapped_port",
    "get_container_name",
    "get_container_web_token",
    "handle",
    "handle_build",
    "handle_logs",
    "handle_status",
    "handle_stop",
    "is_container_bound_to_port",
    "is_container_running",
    "register",
    "stop_proxy_container",
]

CONTAINER_NAME = DEFAULT_CONTAINER_NAME
logger = logging.getLogger(__name__)


def stop_proxy_container(container_name: str | None = None) -> None:
    ProxyLifecycle().stop(container_name)


def handle_build(args: Any) -> int:
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    dockerfile = os.path.join(repo_root, "Dockerfile")
    if not os.path.exists(dockerfile):
        print(f"Error: Dockerfile not found at {dockerfile}.", file=sys.stderr)
        sys.exit(1)
    print(f"🐳 Building Docker image {args.tag}...")
    subprocess.run(["docker", "build", "-t", args.tag, repo_root], check=True)
    print(f"✅ Docker image '{args.tag}' built successfully.")
    return 0


def get_container_mapped_port(container_name: str | None = None, container_port: int = 8080) -> int | None:
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
    except (subprocess.SubprocessError, OSError, ValueError) as exc:
        logger.debug("Failed to resolve mapped port for %s: %s", name, exc)
    return None


WEB_PASSWORD_ENV_VAR = "HOLON_COHERENCE_WEB_PASSWORD"


def get_container_web_token(container_name: str | None = None) -> str | None:
    name = container_name or get_container_name()
    try:
        res = subprocess.run(
            ["docker", "inspect", "-f", "{{json .Config.Env}}", name],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if res.returncode != 0:
        return None
    try:
        env = json.loads(res.stdout.strip() or "null")
    except ValueError:
        return None
    if not isinstance(env, list):
        return None
    prefix = f"{WEB_PASSWORD_ENV_VAR}="
    for entry in env:
        if isinstance(entry, str) and entry.startswith(prefix):
            return entry[len(prefix) :].strip() or None
    return None


def handle_status(
    args: Any = None,
    *,
    is_running_fn: Callable[[str], bool] | None = None,
    resolve_endpoints_fn: Callable[..., ExposedEndpoints] | None = None,
) -> int:
    from holon_coherence.commands.endpoints import print_endpoints, resolve_container_endpoints

    is_running = is_running_fn or is_container_running
    resolve_endpoints = resolve_endpoints_fn or resolve_container_endpoints
    target_container = getattr(args, "name", None) or get_container_name()
    is_default = target_container in (DEFAULT_CONTAINER_NAME, "holon-coherence")
    display_name = "holon-coherence" if is_default else target_container

    try:
        res = subprocess.run(["docker", "ps", "-a", "--filter", f"name=^{target_container}$"])
        retcode = res.returncode
    except (subprocess.SubprocessError, OSError):
        retcode = 1

    if not is_running(target_container):
        print(f"\n🔴 {display_name} is down (not running).")
        print("   mitmweb inspector: not running")
        return retcode

    try:
        fallback_proxy_port = int(os.getenv("HOLON_PROXY_PORT", "8080"))
    except ValueError:
        fallback_proxy_port = 8080
    endpoints = resolve_endpoints(target_container, fallback_proxy_port=fallback_proxy_port)
    proxy_port = endpoints.proxy_port or fallback_proxy_port
    print()
    print_endpoints(endpoints, container_name=target_container)

    try:
        metrics_url = f"http://127.0.0.1:{proxy_port}/holon/api/metrics"
        req = urllib.request.Request(metrics_url, headers={"User-Agent": "holon-coherence-cli"})
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
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError, json.JSONDecodeError) as exc:
        logger.debug("Failed to fetch proxy metrics on port %s: %s", proxy_port, exc)
    return retcode


def handle_logs(args: Any) -> int:
    target_container = getattr(args, "name", None) or get_container_name()
    cmd = ["docker", "logs"]
    if getattr(args, "follow", False):
        cmd.append("-f")
    cmd.append(target_container)
    res = subprocess.run(cmd)
    return res.returncode


def handle(args: Any) -> int:
    cmd = getattr(args, "command", None)
    if cmd == "build":
        return handle_build(args)
    if cmd == "stop":
        return handle_stop(args)
    if cmd == "status":
        return handle_status(args)
    if cmd == "logs":
        return handle_logs(args)
    return 1


def register(subparsers: Any) -> list[argparse.ArgumentParser]:
    status_parser = subparsers.add_parser("status", help="Check status of holon-coherence Docker container")
    status_parser.add_argument(
        "--name",
        default=None,
        help="Container name (defaults to HOLON_CONTAINER_NAME or holon-coherence-proxy)",
    )
    status_parser.set_defaults(handler=handle)

    logs_parser = subparsers.add_parser("logs", help="View logs of holon-coherence Docker container")
    logs_parser.add_argument("-f", "--follow", action="store_true", help="Follow log stream")
    logs_parser.add_argument(
        "--name",
        default=None,
        help="Container name (defaults to HOLON_CONTAINER_NAME or holon-coherence-proxy)",
    )
    logs_parser.set_defaults(handler=handle)

    build_parser = subparsers.add_parser("build", help="Build the holon-coherence Docker image")
    build_parser.add_argument(
        "--tag", default="holon-coherence:latest", help="Docker tag (default: holon-coherence:latest)"
    )
    build_parser.set_defaults(handler=handle)

    return [status_parser, logs_parser, build_parser]
