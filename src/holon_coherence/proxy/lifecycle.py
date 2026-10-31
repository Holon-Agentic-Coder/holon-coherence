"""Proxy lifecycle management and orchestration across Docker and host-local execution."""

from __future__ import annotations

import contextlib
import http.client
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from holon_coherence.ca_generator import generate_root_ca
from holon_coherence.host_local import (
    GATEWAY_HOSTNAME,
    HOST_LOCAL_ENV_VAR,
    LocalTarget,
    decode_targets,
    encode_targets,
)

DEFAULT_PROXY_PORT = 8080
DEFAULT_WEB_PORT = 8081
DEFAULT_CONTAINER_NAME = "holon-coherence-proxy"
PROXY_READY_TIMEOUT_SECONDS = 15.0
PROXY_POLL_INTERVAL_SECONDS = 0.2


@dataclass
class ProxyLifecycleConfig:
    """Configuration parameters for the optimization proxy container lifecycle."""

    port: int = DEFAULT_PROXY_PORT
    web_port: int | None = None
    container_name: str | None = None
    image: str = "holon-coherence:latest"
    host_local_spec: str = ""
    passive: bool = False
    web_password: str | None = None
    ca_dir: str = "~/.holon/proxy-ca"
    cache_dir: str = "~/.holon/cache"
    logs_dir: str = "~/.holon/logs"
    detach: bool = True
    build: bool = False


def is_in_container() -> bool:
    """Return True if executing within a Docker container environment."""
    return os.path.exists("/.dockerenv") or os.environ.get("HOLON_IN_CONTAINER") == "1"


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


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check if the specified TCP port is currently open and accepting connections or cannot be bound."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        if s.connect_ex((host, port)) == 0:
            return True
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True


def find_available_port(start_port: int = 8080, max_attempts: int = 100, host: str = "127.0.0.1") -> int:
    """Find an available TCP port on the host starting from start_port."""
    for p in range(start_port, start_port + max_attempts):
        if not is_port_in_use(p, host=host):
            return p
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def _urlopen_no_proxy(req: urllib.request.Request, timeout: float) -> Any:
    """Open a request directly, ignoring http_proxy/HTTP_PROXY env vars (readiness probes target loopback)."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(req, timeout=timeout)


def docker_host_alias_args() -> list[str]:
    """Flags making the Docker host reachable from inside the proxy container."""
    return ["--add-host", f"{GATEWAY_HOSTNAME}:host-gateway"]


def host_local_container_args(host_local_spec: str) -> list[str]:
    """Environment flags passing the host-local allow list into the container."""
    if not host_local_spec:
        return []
    return ["-e", f"{HOST_LOCAL_ENV_VAR}={host_local_spec}"]


def container_host_local_spec(container_name: str | None = None) -> str:
    """Read back the host-local allow list a running proxy container was started with."""
    name = container_name or get_container_name()
    try:
        res = subprocess.run(
            ["docker", "inspect", "-f", "{{range .Config.Env}}{{println .}}{{end}}", name],
            capture_output=True,
            text=True,
            timeout=5.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    for line in (res.stdout or "").splitlines():
        if line.startswith(f"{HOST_LOCAL_ENV_VAR}="):
            return line.split("=", 1)[1].strip()
    return ""


def host_local_covered(required_spec: str, existing_spec: str) -> bool:
    """True when a container started with ``existing_spec`` already intercepts ``required_spec``."""
    required = decode_targets(required_spec)
    if not required:
        return True
    existing = decode_targets(existing_spec)

    def covered(target: LocalTarget) -> bool:
        return any(
            candidate.host == target.host and (candidate.port is None or candidate.port == target.port)
            for candidate in existing
        )

    return all(covered(target) for target in required)


def _prepare_proxy_directories(ca_dir: str, cache_dir: str, logs_dir: str) -> None:
    """Create directory structure for CA certs, cache, and wire logs with restricted permissions."""
    for d in (ca_dir, cache_dir, logs_dir):
        os.makedirs(d, mode=0o700, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(d, 0o700)


def _chmod_proxy_dirs(ca_dir: str, cache_dir: str, logs_dir: str, ca_files: bool = False) -> None:
    """Make mounted proxy dirs (and optionally CA files) accessible to non-root container users."""
    targets: list[tuple[str, int]] = [(ca_dir, 0o777), (cache_dir, 0o777), (logs_dir, 0o777)]
    if ca_files:
        with contextlib.suppress(OSError):
            targets.extend((os.path.join(ca_dir, fname), 0o666) for fname in os.listdir(ca_dir))
    for path, mode in targets:
        with contextlib.suppress(OSError):
            os.chmod(path, mode)


@dataclass
class ProxyLifecycleHooks:
    """Callable hooks for Docker operations, system calls, and readiness polling."""

    check_daemon_fn: Callable[[], tuple[bool, str]] = check_docker_daemon
    is_port_in_use_fn: Callable[..., bool] = is_port_in_use
    is_container_running_fn: Callable[..., bool] = is_container_running
    is_container_bound_to_port_fn: Callable[..., bool] = is_container_bound_to_port
    wait_ready_fn: Callable[..., bool] | None = None
    stop_container_fn: Callable[..., None] = stop_proxy_container
    ensure_image_fn: Callable[..., None] | None = None
    urlopen_no_proxy_fn: Callable[..., Any] = _urlopen_no_proxy
    generate_ca_fn: Callable[..., Any] = generate_root_ca
    container_host_local_spec_fn: Callable[..., str] = container_host_local_spec


def _resolve_ensure_image(hook: Callable[..., None] | None) -> Callable[..., None]:
    """Resolve docker image provisioning function lazily to prevent module cycle."""
    if hook is not None:
        return hook
    from holon_coherence.commands.docker_ops import ensure_docker_image

    return ensure_docker_image


def _verify_container_health(
    container_name: str,
    port: int,
    timeout: float = PROXY_READY_TIMEOUT_SECONDS,
    hooks: ProxyLifecycleHooks | None = None,
) -> bool:
    """Poll the proxy metrics endpoint until healthy or deadline expires."""
    active_hooks = hooks or ProxyLifecycleHooks()
    is_running = active_hooks.is_container_running_fn
    urlopen = active_hooks.urlopen_no_proxy_fn

    deadline = time.monotonic() + timeout
    candidate_urls = (
        f"http://127.0.0.1:{port}/holon/api/metrics",
        f"http://127.0.0.1:{port}/_holon/metrics",
    )
    while time.monotonic() < deadline:
        if not is_running(container_name):
            return False

        for url in candidate_urls:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "holon-coherence-readiness"})
                resp = urlopen(req, timeout=1.0)
                try:
                    status = getattr(resp, "status", None) or getattr(resp, "code", None)
                    if status == 200:
                        return True
                finally:
                    close = getattr(resp, "close", None)
                    if callable(close):
                        close()
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    continue
                break
            except (
                urllib.error.URLError,
                ConnectionRefusedError,
                OSError,
                TimeoutError,
                http.client.RemoteDisconnected,
                http.client.HTTPException,
            ):
                break

        time.sleep(PROXY_POLL_INTERVAL_SECONDS)
    return False


def wait_for_proxy_ready(
    port: int,
    timeout: float = PROXY_READY_TIMEOUT_SECONDS,
    container_name: str | None = None,
    hooks: ProxyLifecycleHooks | None = None,
) -> bool:
    """Poll the proxy HTTP metrics endpoint until it returns HTTP 200 or timeout occurs."""
    name = container_name or get_container_name()
    return _verify_container_health(name, port, timeout=timeout, hooks=hooks)


def _check_daemon(check_fn: Callable[[], tuple[bool, str]]) -> None:
    """Verify Docker daemon availability, exiting cleanly if unreachable."""
    ok, err_msg = check_fn()
    if not ok:
        print(err_msg, file=sys.stderr)
        sys.exit(1)


def _handle_port_conflict(
    port: int,
    name: str,
    host_local_spec: str,
    hooks: ProxyLifecycleHooks,
    has_custom_name: bool = False,
) -> tuple[bool, str]:
    """Handle port contention when proxy listen port is already occupied."""
    if not (hooks.is_container_running_fn(name) and hooks.is_container_bound_to_port_fn(port, name)):
        print(
            f"Error: Port {port} is already in use by another process.\n"
            "Please free the port or specify another port via --port or HOLON_PROXY_PORT.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not host_local_spec:
        return False, host_local_spec

    existing_spec = (
        hooks.container_host_local_spec_fn(name) if has_custom_name else hooks.container_host_local_spec_fn()
    )
    if host_local_covered(host_local_spec, existing_spec):
        return False, host_local_spec

    merged_targets = (*decode_targets(existing_spec), *decode_targets(host_local_spec))
    new_spec = encode_targets(merged_targets)
    print(
        f"♻️  Running proxy container does not intercept {new_spec}; recreating it. "
        "Other sessions sharing this proxy will briefly lose interception."
    )
    hooks.stop_container_fn(name) if has_custom_name else hooks.stop_container_fn()
    deadline = time.monotonic() + 10.0
    while hooks.is_port_in_use_fn(port) and time.monotonic() < deadline:
        time.sleep(PROXY_POLL_INTERVAL_SECONDS)
    if hooks.is_port_in_use_fn(port):
        print(
            f"Error: Port {port} could not be freed after stopping container.\n"
            "Another process may have bound to this port.",
            file=sys.stderr,
        )
        sys.exit(1)
    return True, new_spec


def _handle_existing_container(
    name: str,
    port: int,
    hooks: ProxyLifecycleHooks,
    has_custom_name: bool = False,
) -> bool:
    """Validate status of an already running container."""
    if not hooks.is_container_bound_to_port_fn(port, name):
        if has_custom_name:
            print(
                f"Error: A holon-coherence proxy container '{name}' is already running on a different port.\n"
                f"Stop it first using 'holon-coherence stop' before launching on port {port}.",
                file=sys.stderr,
            )
        else:
            print(
                "Error: A holon-coherence proxy container is already running on a different port.\n"
                f"Stop it first using 'holon-coherence stop' before launching on port {port}.",
                file=sys.stderr,
            )
        sys.exit(1)

    wait_fn = hooks.wait_ready_fn or wait_for_proxy_ready
    ready = wait_fn(port, container_name=name) if has_custom_name else wait_fn(port)
    if ready:
        return False

    if has_custom_name:
        print(
            f"Error: A holon-coherence proxy container '{name}' is running for port {port}, but is not responding.\n"
            "Please restart it using 'holon-coherence stop' and retry.",
            file=sys.stderr,
        )
    else:
        print(
            f"Error: A holon-coherence proxy container is running for port {port}, but is not responding.\n"
            "Please restart it using 'holon-coherence stop' and retry.",
            file=sys.stderr,
        )
    sys.exit(1)


def _launch_and_verify_container(
    docker_cmd: list[str],
    name: str,
    port: int,
    hooks: ProxyLifecycleHooks,
    has_custom_name: bool = False,
) -> None:
    """Execute docker run and verify readiness within deadline."""
    print(f"🐳 Starting background optimization proxy container on port {port}...")
    run_res = subprocess.run(docker_cmd, capture_output=True, text=True)
    if run_res.returncode != 0:
        print(f"Error starting proxy container: {run_res.stderr.strip()}", file=sys.stderr)
        sys.exit(run_res.returncode)

    wait_fn = hooks.wait_ready_fn or wait_for_proxy_ready
    ready = wait_fn(port, container_name=name) if has_custom_name else wait_fn(port)
    if not ready:
        print(f"Error: Proxy container did not become ready within {PROXY_READY_TIMEOUT_SECONDS}s.", file=sys.stderr)
        logs_res = subprocess.run(["docker", "logs", name], capture_output=True, text=True)
        combined_logs = f"{logs_res.stdout or ''}{logs_res.stderr or ''}".strip()
        if combined_logs:
            print(f"Container logs:\n{combined_logs}", file=sys.stderr)
        hooks.stop_container_fn(name) if has_custom_name else hooks.stop_container_fn()
        sys.exit(1)


class ProxyLifecycle:
    """Encapsulates proxy container lifecycle, CA certificates, and health monitoring."""

    def __init__(
        self,
        config: ProxyLifecycleConfig | None = None,
        hooks: ProxyLifecycleHooks | None = None,
    ) -> None:
        self.config = config or ProxyLifecycleConfig()
        self.hooks = hooks or ProxyLifecycleHooks()

    def ensure_ca(self, ca_dir: str | None = None) -> tuple[str, str]:
        """Ensure proxy root CA certificate and keys exist with secure permissions."""
        target_ca_dir = os.path.expanduser(ca_dir or self.config.ca_dir)
        target_cache_dir = os.path.expanduser(self.config.cache_dir)
        target_logs_dir = os.path.expanduser(self.config.logs_dir)

        _prepare_proxy_directories(target_ca_dir, target_cache_dir, target_logs_dir)
        _chmod_proxy_dirs(target_ca_dir, target_cache_dir, target_logs_dir)

        ca_cert = os.path.join(target_ca_dir, "mitmproxy-ca-cert.pem")
        ca_pem = os.path.join(target_ca_dir, "mitmproxy-ca.pem")
        if not os.path.exists(ca_cert) or not os.path.exists(ca_pem):
            with contextlib.suppress(Exception):
                self.hooks.generate_ca_fn(output_dir=target_ca_dir)

        for cert_file in (ca_cert, ca_pem):
            with contextlib.suppress(OSError):
                if os.path.exists(cert_file):
                    os.chmod(cert_file, 0o600)

        _chmod_proxy_dirs(target_ca_dir, target_cache_dir, target_logs_dir, ca_files=True)
        return ca_cert, ca_pem

    def wait_until_ready(
        self,
        timeout_seconds: float = PROXY_READY_TIMEOUT_SECONDS,
        poll_interval: float = PROXY_POLL_INTERVAL_SECONDS,
    ) -> bool:
        """Poll proxy metrics endpoint until healthy or timeout expires."""
        name = self.config.container_name or get_container_name()
        return _verify_container_health(
            name,
            self.config.port,
            timeout=timeout_seconds,
            hooks=self.hooks,
        )

    def stop(self, container_name: str | None = None) -> bool:
        """Stop and remove running holon-coherence Docker container."""
        target_container = container_name or self.config.container_name or get_container_name()
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
                return True
            if "no such container" in (res.stderr or "").lower():
                print(f"✅ No active {display_name} container found.")
                return True
            print(f"⚠️  Failed to remove container: {res.stderr.strip()}")
            return False
        except OSError as e:
            print(f"⚠️  Failed to remove container: {e}")
            return False

    def _build_docker_run_args(self, actual_port: int, actual_web_port: int | None = None) -> list[str]:
        """Build docker run command arguments list."""
        ca_dir = os.path.expanduser(self.config.ca_dir)
        cache_dir = os.path.expanduser(self.config.cache_dir)
        logs_dir = os.path.expanduser(self.config.logs_dir)
        target_container = self.config.container_name or get_container_name()

        cmd = [
            "docker",
            "run",
            "-d" if self.config.detach else "--rm",
            "--init",
            "--name",
            target_container,
            *docker_host_alias_args(),
            "-p",
            f"127.0.0.1:{actual_port}:8080",
            "-v",
            f"{ca_dir}:/home/mitmproxy/.mitmproxy",
            "-v",
            f"{cache_dir}:/home/mitmproxy/.holon/cache",
            "-v",
            f"{logs_dir}:/tmp/wire_logs",
            "-e",
            "HOLON_IN_CONTAINER=1",
            "-e",
            "WIRE_LOG_DIR=/tmp/wire_logs",
            "-e",
            f"HOLON_PROXY_PORT={actual_port}",
            "-e",
            f"COHERENCE_TOKEN_REDUCTION={'0' if self.config.passive else '1'}",
            "-e",
            f"HOLON_PASSIVE_MONITORING={'1' if self.config.passive else '0'}",
            *host_local_container_args(self.config.host_local_spec),
        ]
        if actual_web_port is not None:
            cmd.extend(["-p", f"127.0.0.1:{actual_web_port}:{DEFAULT_WEB_PORT}"])
            if self.config.web_password:
                cmd.extend(["-e", f"HOLON_COHERENCE_WEB_PASSWORD={self.config.web_password}"])

        cmd.append(self.config.image)
        cmd.extend(["start", "--port", "8080"])
        if actual_web_port is not None:
            cmd.extend(["--web", "--web-port", str(DEFAULT_WEB_PORT)])
        return cmd

    def _start_in_container(self) -> bool:
        """Execute mitmproxy/mitmweb directly inside container environment."""
        from holon_coherence.commands.endpoints import token_recovery_command
        from holon_coherence.commands.web_token import resolve_web_password, save_web_token

        os.environ[HOST_LOCAL_ENV_VAR] = self.config.host_local_spec
        pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        addon_path = os.path.join(pkg_dir, "mitm_addon.py")
        web_enabled = self.config.web_port is not None
        tool = "mitmweb" if web_enabled else "mitmdump"
        tool_candidate = os.path.join(os.path.dirname(sys.executable), tool)
        tool_path = tool_candidate if os.path.isfile(tool_candidate) else (shutil.which(tool) or tool)

        cmd = [tool_path, "-s", addon_path, "--listen-port", str(self.config.port)]
        if web_enabled:
            web_password = resolve_web_password(self.config.web_password)
            save_web_token(web_password)
            cmd.extend(
                [
                    "--web-host",
                    "0.0.0.0",
                    "--web-port",
                    str(self.config.web_port),
                    "--set",
                    f"web_password={web_password}",
                    "--set",
                    "web_open_browser=false",
                ]
            )
        print(f"🚀 Starting holon-coherence proxy via {tool} on port {self.config.port}...")
        if web_enabled:
            print(
                f"🌐 mitmweb inspector listening on container port {self.config.web_port} (token hidden; run "
                "'holon-coherence web-token --name <container>' on the host for the full URL, or recover the "
                f"token with: {token_recovery_command('<container>')})"
            )
        try:
            subprocess.run(cmd, check=True)
            return True
        except KeyboardInterrupt:
            print("\nShutting down holon-coherence proxy.")
            return True

    def ensure_running(self) -> bool:
        """Ensure proxy container is running in the background and healthy."""
        _check_daemon(self.hooks.check_daemon_fn)
        has_custom_name = self.config.container_name is not None
        name = self.config.container_name or get_container_name()
        port = self.config.port
        was_running = False

        if self.hooks.is_port_in_use_fn(port):
            needs_restart, new_spec = _handle_port_conflict(
                port, name, self.config.host_local_spec, self.hooks, has_custom_name
            )
            if not needs_restart:
                return False
            was_running = True
            self.config.host_local_spec = new_spec
        elif self.hooks.is_container_running_fn(name):
            return _handle_existing_container(name, port, self.hooks, has_custom_name)

        self.ensure_ca()
        ensure_image = _resolve_ensure_image(self.hooks.ensure_image_fn)
        ensure_image(self.config.image, rebuild=self.config.build)

        with contextlib.suppress(subprocess.TimeoutExpired, OSError):
            subprocess.run(
                ["docker", "rm", "-f", name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5.0,
            )

        docker_cmd = self._build_docker_run_args(port, actual_web_port=self.config.web_port)
        _launch_and_verify_container(docker_cmd, name, port, self.hooks, has_custom_name)
        return not was_running

    def start(self, recreate_if_mismatch: bool = True) -> bool:
        """Start the proxy server in container or host Docker mode."""
        if is_in_container():
            return self._start_in_container()

        if self.config.detach:
            return self.ensure_running()

        _check_daemon(self.hooks.check_daemon_fn)
        self.ensure_ca()
        ensure_image = _resolve_ensure_image(self.hooks.ensure_image_fn)
        ensure_image(self.config.image, rebuild=self.config.build)

        name = self.config.container_name or get_container_name()
        subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        docker_cmd = self._build_docker_run_args(self.config.port, actual_web_port=self.config.web_port)
        try:
            subprocess.run(docker_cmd)
            return True
        except subprocess.CalledProcessError as e:
            print(f"❌ Error: Failed to start Docker container: {e}", file=sys.stderr)
            sys.exit(1)
        except KeyboardInterrupt:
            print("\nShutting down holon-coherence container...")
            subprocess.run(["docker", "stop", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
