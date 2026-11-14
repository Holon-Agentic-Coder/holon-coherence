"""Proxy container lifecycle: CA material, container launch, readiness polling and teardown.

This module owns the Docker container primitives the lifecycle needs and depends only on low-level
helpers (``ca_generator``, ``host_local``). ``holon_coherence.commands`` re-exports it through
``commands.start`` and ``commands.docker_ops``, so importing a command module here at module level
would be circular.
"""

from __future__ import annotations

import contextlib
import enum
import http.client
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from typing import Any, NoReturn

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
DEFAULT_IMAGE = "holon-coherence:latest"
PROXY_READY_TIMEOUT_SECONDS = 15.0
PROXY_POLL_INTERVAL_SECONDS = 0.2
PORT_RELEASE_TIMEOUT_SECONDS = 10.0
CONTAINER_PROXY_PORT = 8080
CA_CERT_FILENAME = "mitmproxy-ca-cert.pem"
CA_PEM_FILENAME = "mitmproxy-ca.pem"

_READINESS_PATHS = ("/holon/api/metrics", "/_holon/metrics")
_READINESS_NETWORK_ERRORS = (
    urllib.error.URLError,
    ConnectionRefusedError,
    OSError,
    TimeoutError,
    http.client.RemoteDisconnected,
    http.client.HTTPException,
)


# --- Docker container primitives -------------------------------------------------------------------


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


def _docker_port_output(name: str) -> str | None:
    """Return ``docker port`` output for the proxy port, falling back to every mapping of the container."""
    try:
        res = subprocess.run(
            ["docker", "port", name, f"{CONTAINER_PROXY_PORT}/tcp"],
            capture_output=True,
            text=True,
            timeout=5.0,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if res.returncode == 0 and res.stdout.strip():
        return res.stdout
    try:
        fallback_res = subprocess.run(
            ["docker", "port", name],
            capture_output=True,
            text=True,
            timeout=5.0,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if fallback_res.returncode != 0:
        return None
    return fallback_res.stdout


def _mapped_host_port(line: str) -> int | None:
    """Parse the host port out of one ``docker port`` line (``8080/tcp -> 127.0.0.1:9090`` or ``127.0.0.1:9090``)."""
    host_part = line.strip().split("->")[-1].strip()
    if ":" not in host_part:
        return None
    try:
        return int(host_part.rsplit(":", 1)[1])
    except ValueError:
        return None


def is_container_bound_to_port(port: int, container_name: str | None = None) -> bool:
    """Check if the container is currently running and bound to the specified host port."""
    output = _docker_port_output(container_name or get_container_name())
    if output is None:
        return False
    return any(_mapped_host_port(line) == port for line in output.splitlines() if line.strip())


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


def require_docker_daemon() -> None:
    """Exit with the daemon diagnostic when Docker cannot run the proxy container."""
    ok, err_msg = check_docker_daemon()
    if not ok:
        _fail(err_msg)


def _ensure_image(image: str, rebuild: bool) -> None:
    """Make sure the proxy image exists locally (build, pull or GHCR fallback)."""
    # Imported here: commands.docker_ops imports this module at the top level (see module docstring).
    from holon_coherence.commands.docker_ops import ensure_docker_image

    ensure_docker_image(image, rebuild=rebuild)


# --- Host environment helpers ----------------------------------------------------------------------


def is_in_container() -> bool:
    """Return True if executing within a Docker container environment."""
    return os.path.exists("/.dockerenv") or os.environ.get("HOLON_IN_CONTAINER") == "1"


def is_start_passive(passive_flag: bool = False) -> bool:
    """Return True if proxy should run in passive monitoring mode (baseline)."""
    if passive_flag:
        return True
    if os.getenv("HOLON_PASSIVE_MONITORING", "0").lower().strip() in ("1", "true", "yes", "on"):
        return True
    return os.getenv("COHERENCE_TOKEN_REDUCTION", "1").lower().strip() in ("0", "false", "no", "off")


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


def _fail(message: str) -> NoReturn:
    """Print ``message`` to stderr and exit with status 1."""
    print(message, file=sys.stderr)
    sys.exit(1)


# --- Readiness polling -----------------------------------------------------------------------------


class _Probe(enum.Enum):
    """Outcome of a single readiness probe against one metrics endpoint."""

    READY = "ready"
    NEXT_ENDPOINT = "next-endpoint"
    RETRY = "retry"


def _urlopen_no_proxy(req: urllib.request.Request, timeout: float) -> Any:
    """Open a request directly, ignoring http_proxy/HTTP_PROXY env vars (readiness probes target loopback)."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(req, timeout=timeout)


def _probe_readiness_url(url: str) -> _Probe:
    """Probe one metrics endpoint: 200 is ready, 404 (or another success code) tries the next path."""
    req = urllib.request.Request(url, headers={"User-Agent": "holon-coherence-readiness"})
    try:
        resp = _urlopen_no_proxy(req, timeout=1.0)
        try:
            status = getattr(resp, "status", None) or getattr(resp, "code", None)
        finally:
            close = getattr(resp, "close", None)
            if callable(close):
                close()
    except urllib.error.HTTPError as exc:
        return _Probe.NEXT_ENDPOINT if exc.code == 404 else _Probe.RETRY
    except _READINESS_NETWORK_ERRORS:
        return _Probe.RETRY
    return _Probe.READY if status == 200 else _Probe.NEXT_ENDPOINT


def _probe_proxy_endpoints(port: int) -> bool:
    """Try each metrics path once; True as soon as one answers HTTP 200."""
    for path in _READINESS_PATHS:
        outcome = _probe_readiness_url(f"http://127.0.0.1:{port}{path}")
        if outcome is _Probe.READY:
            return True
        if outcome is _Probe.RETRY:
            return False
    return False


def _poll_until_ready(port: int, container_name: str, timeout: float, poll_interval: float) -> bool:
    """Poll the proxy until it is healthy, the container stops, or the monotonic deadline passes."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_container_running(container_name):
            return False
        if _probe_proxy_endpoints(port):
            return True
        time.sleep(poll_interval)
    return False


# --- Lifecycle configuration and helpers -----------------------------------------------------------


@dataclass(frozen=True)
class ProxyLifecycleConfig:
    """Settings for one proxy container: published ports, image, mounts and runtime mode.

    ``port`` and ``web_port`` are the host ports to publish (``web_port=None`` keeps the
    mitmweb inspector off). ``world_accessible_mounts`` opens the mounted directories (and CA
    files) to the non-root container user, as the background agent proxy needs; otherwise the
    directories are private to the host user.
    """

    port: int = DEFAULT_PROXY_PORT
    web_port: int | None = None
    container_name: str | None = None
    image: str = DEFAULT_IMAGE
    host_local_spec: str = ""
    passive: bool = False
    web_password: str | None = None
    ca_dir: str = "~/.holon/proxy-ca"
    cache_dir: str = "~/.holon/cache"
    logs_dir: str = "~/.holon/logs"
    detach: bool = True
    rebuild: bool = False
    world_accessible_mounts: bool = False


def _mount_dirs(config: ProxyLifecycleConfig) -> tuple[str, str, str]:
    """Expanded host paths of the CA, cache and wire-log directories."""
    return (
        os.path.expanduser(config.ca_dir),
        os.path.expanduser(config.cache_dir),
        os.path.expanduser(config.logs_dir),
    )


def _chmod_proxy_dirs(ca_dir: str, cache_dir: str, logs_dir: str, ca_files: bool = False) -> None:
    """Make mounted proxy dirs (and optionally CA files) accessible to non-root container users.

    Each chmod is attempted independently so one failure does not skip the rest.
    """
    targets: list[tuple[str, int]] = [(ca_dir, 0o777), (cache_dir, 0o777), (logs_dir, 0o777)]
    if ca_files:
        with contextlib.suppress(OSError):
            targets.extend((os.path.join(ca_dir, fname), 0o666) for fname in os.listdir(ca_dir))
    for path, mode in targets:
        with contextlib.suppress(OSError):
            os.chmod(path, mode)


def _prepare_proxy_directories(ca_dir: str, cache_dir: str, logs_dir: str, *, shared: bool = False) -> None:
    """Create the mounted directories, private (``0o700``) or shared with the container user."""
    if shared:
        for d in (ca_dir, cache_dir, logs_dir):
            os.makedirs(d, exist_ok=True)
        _chmod_proxy_dirs(ca_dir, cache_dir, logs_dir)
        return
    for d in (ca_dir, cache_dir, logs_dir):
        os.makedirs(d, mode=0o700, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(d, 0o700)


def _web_inspector_args(actual_web_port: int | None, web_password: str | None) -> list[str]:
    """Publish the mitmweb inspector on loopback and hand it its token (empty when headless)."""
    if actual_web_port is None:
        return []
    return [
        "-p",
        f"127.0.0.1:{actual_web_port}:{DEFAULT_WEB_PORT}",
        "-e",
        f"HOLON_COHERENCE_WEB_PASSWORD={web_password}",
    ]


def _build_docker_run_args(config: ProxyLifecycleConfig, actual_port: int, actual_web_port: int | None) -> list[str]:
    """Assemble the ``docker run`` command for the proxy container."""
    name = config.container_name or get_container_name()
    ca_dir, cache_dir, logs_dir = _mount_dirs(config)
    passive = is_start_passive(config.passive)
    cmd = [
        "docker",
        "run",
        "-d" if config.detach else "--rm",
        "--init",
        "--name",
        name,
        *docker_host_alias_args(),
        "-p",
        f"127.0.0.1:{actual_port}:{CONTAINER_PROXY_PORT}",
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
        f"COHERENCE_TOKEN_REDUCTION={'0' if passive else '1'}",
        "-e",
        f"HOLON_PASSIVE_MONITORING={'1' if passive else '0'}",
        *host_local_container_args(config.host_local_spec),
        *_web_inspector_args(actual_web_port, config.web_password),
        config.image,
        "start",
        "--port",
        str(CONTAINER_PROXY_PORT),
    ]
    # Without a web port the in-container start is headless mitmdump, so it publishes no inspector
    # port and generates no token (see commands.start.is_web_inspector_enabled).
    if actual_web_port is not None:
        cmd.extend(["--web", "--web-port", str(DEFAULT_WEB_PORT)])
    return cmd


def _resolve_proxy_tool(tool: str) -> str:
    """Prefer the mitmproxy tool installed next to this interpreter, then PATH."""
    candidate = os.path.join(os.path.dirname(sys.executable), tool)
    return candidate if os.path.isfile(candidate) else (shutil.which(tool) or tool)


def _addon_path() -> str:
    """Absolute path of the mitmproxy addon script shipped with the package."""
    pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(pkg_dir, "mitm_addon.py")


class _Existing(enum.Enum):
    """What ``ProxyLifecycle.start`` found already running for its port and container name."""

    NONE = "none"
    REUSE = "reuse"
    RECREATE = "recreate"


class ProxyLifecycle:
    """Start, probe and tear down one holon-coherence proxy (Docker container or in-container mitmproxy)."""

    def __init__(self, config: ProxyLifecycleConfig | None = None) -> None:
        self.config = config or ProxyLifecycleConfig()

    @property
    def container_name(self) -> str:
        """Configured container name, or the ``HOLON_CONTAINER_NAME`` / default name."""
        return self.config.container_name or get_container_name()

    def ensure_ca(self, ca_dir: str | None = None) -> tuple[str, str]:
        """Create the mounted directories and the mitmproxy root CA when missing; return its two files."""
        default_ca_dir, cache_dir, logs_dir = _mount_dirs(self.config)
        ca_path = os.path.expanduser(ca_dir) if ca_dir else default_ca_dir
        shared = self.config.world_accessible_mounts
        _prepare_proxy_directories(ca_path, cache_dir, logs_dir, shared=shared)

        ca_cert = os.path.join(ca_path, CA_CERT_FILENAME)
        ca_pem = os.path.join(ca_path, CA_PEM_FILENAME)
        if not os.path.exists(ca_cert) or not os.path.exists(ca_pem):
            with contextlib.suppress(Exception):
                generate_root_ca(output_dir=ca_path)

        if shared:
            _chmod_proxy_dirs(ca_path, cache_dir, logs_dir, ca_files=True)
        return ca_cert, ca_pem

    def wait_until_ready(
        self,
        timeout_seconds: float = PROXY_READY_TIMEOUT_SECONDS,
        poll_interval: float = PROXY_POLL_INTERVAL_SECONDS,
    ) -> bool:
        """Poll the proxy metrics endpoint until it returns HTTP 200 or the timeout elapses.

        The timeout is measured on the monotonic clock, so a wall-clock step (NTP correction, VM
        resume, a manual ``date``) can neither stretch nor cut short the cold-start wait. The
        container state is checked on every iteration to fail fast when it exits.
        """
        return _poll_until_ready(self.config.port, self.container_name, timeout_seconds, poll_interval)

    def prepare(self) -> None:
        """Make CA material and the image available and clear any stale container of the same name."""
        self.ensure_ca()
        _ensure_image(self.config.image, rebuild=self.config.rebuild)
        with contextlib.suppress(subprocess.TimeoutExpired, OSError):
            subprocess.run(
                ["docker", "rm", "-f", self.container_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5.0,
            )

    def start(self, recreate_if_mismatch: bool = True) -> bool:
        """Ensure a healthy background proxy container serves ``config.port``.

        A running container bound to the port is reused; one that does not intercept the required
        host-local endpoints is recreated with the merged allow list (unless ``recreate_if_mismatch``
        is False). Returns True only when a new container was launched where none ran before.
        """
        require_docker_daemon()
        existing = self._reconcile_existing(recreate_if_mismatch)
        if existing is _Existing.REUSE:
            return False

        self.prepare()
        port = self.config.port
        print(f"🐳 Starting background optimization proxy container on port {port}...")
        run_res = subprocess.run(
            _build_docker_run_args(self.config, port, self.config.web_port), capture_output=True, text=True
        )
        if run_res.returncode != 0:
            print(f"Error starting proxy container: {run_res.stderr.strip()}", file=sys.stderr)
            sys.exit(run_res.returncode)

        self._verify_container_health()
        return existing is _Existing.NONE

    def launch(self) -> None:
        """Run the prepared container for ``holon-coherence start``, detached or attached to the terminal."""
        docker_cmd = _build_docker_run_args(self.config, self.config.port, self.config.web_port)
        if self.config.detach:
            try:
                subprocess.run(docker_cmd, check=True)
            except subprocess.CalledProcessError as e:
                self._launch_failed(e)
            print("✅ holon-coherence container running in background.")
            print("Use 'holon-coherence logs -f' to stream logs or 'holon-coherence stop' to shut down.")
            return
        try:
            subprocess.run(docker_cmd)
        except subprocess.CalledProcessError as e:
            self._launch_failed(e)
        except KeyboardInterrupt:
            print("\nShutting down holon-coherence container...")
            subprocess.run(
                ["docker", "stop", self.container_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def serve_in_container(self, banner: str | None = None) -> None:
        """Run mitmweb (when a web port is configured) or mitmdump in the foreground inside the container."""
        os.environ[HOST_LOCAL_ENV_VAR] = self.config.host_local_spec
        web_port = self.config.web_port
        tool = "mitmweb" if web_port is not None else "mitmdump"
        cmd = [_resolve_proxy_tool(tool), "-s", _addon_path(), "--listen-port", str(self.config.port)]
        if web_port is not None:
            cmd.extend(
                [
                    "--web-host",
                    "0.0.0.0",
                    "--web-port",
                    str(web_port),
                    "--set",
                    f"web_password={self.config.web_password}",
                    "--set",
                    "web_open_browser=false",
                ]
            )
        print(f"🚀 Starting holon-coherence proxy via {tool} on port {self.config.port}...")
        if banner:
            print(banner)
        try:
            subprocess.run(cmd, check=True)
        except KeyboardInterrupt:
            print("\nShutting down holon-coherence proxy.")

    def stop(self, container_name: str | None = None) -> bool:
        """Stop and remove the proxy container; True when it is gone (or never existed)."""
        target_container = container_name or self.container_name
        is_default = target_container in (DEFAULT_CONTAINER_NAME, "holon-coherence")
        display_name = "holon-coherence" if is_default else target_container
        print(f"🛑 Stopping and removing {display_name} Docker container...")
        try:
            res = subprocess.run(
                ["docker", "rm", "-f", target_container],
                capture_output=True,
                text=True,
            )
        except OSError as e:
            print(f"⚠️  Failed to remove container: {e}")
            return False
        if res.returncode == 0:
            print(f"✅ {display_name} container stopped and removed.")
            return True
        if "no such container" in (res.stderr or "").lower():
            print(f"✅ No active {display_name} container found.")
            return True
        print(f"⚠️  Failed to remove container: {res.stderr.strip()}")
        return False

    def _container_label(self) -> str:
        """`` 'name'`` for an explicitly named container, empty for the default one (error messages)."""
        return f" '{self.container_name}'" if self.config.container_name else ""

    def _reconcile_existing(self, recreate_if_mismatch: bool) -> _Existing:
        """Decide whether to reuse, recreate or freshly launch; exit on conflicts that cannot be resolved."""
        port = self.config.port
        name = self.container_name
        if is_port_in_use(port):
            if not (is_container_running(name) and is_container_bound_to_port(port, name)):
                _fail(
                    f"Error: Port {port} is already in use by another process.\n"
                    "Please free the port or specify another port via --port or HOLON_PROXY_PORT."
                )
            return self._reconcile_bound_container(recreate_if_mismatch)
        if is_container_running(name):
            self._adopt_running_container()
            return _Existing.REUSE
        return _Existing.NONE

    def _adopt_running_container(self) -> None:
        """Accept a running container that publishes our port and answers; exit otherwise."""
        port = self.config.port
        label = self._container_label()
        if not is_container_bound_to_port(port, self.container_name):
            _fail(
                f"Error: A holon-coherence proxy container{label} is already running on a different port.\n"
                f"Stop it first using 'holon-coherence stop' before launching on port {port}."
            )
        if not self.wait_until_ready():
            _fail(
                f"Error: A holon-coherence proxy container{label} is running for port {port}, "
                "but is not responding.\n"
                "Please restart it using 'holon-coherence stop' and retry."
            )

    def _reconcile_bound_container(self, recreate_if_mismatch: bool) -> _Existing:
        """Reuse the container on our port unless it misses host-local endpoints we now need."""
        required_spec = self.config.host_local_spec
        if not required_spec:
            return _Existing.REUSE
        existing_spec = container_host_local_spec(self.container_name)
        if host_local_covered(required_spec, existing_spec) or not recreate_if_mismatch:
            return _Existing.REUSE

        merged_spec = encode_targets((*decode_targets(existing_spec), *decode_targets(required_spec)))
        self.config = replace(self.config, host_local_spec=merged_spec)
        print(
            f"♻️  Running proxy container does not intercept {merged_spec}; recreating it. "
            "Other sessions sharing this proxy will briefly lose interception."
        )
        self.stop(self.container_name)
        self._wait_for_port_release()
        return _Existing.RECREATE

    def _wait_for_port_release(self) -> None:
        """Wait for the stopped container to free its port; exit if something else grabs it."""
        port = self.config.port
        deadline = time.monotonic() + PORT_RELEASE_TIMEOUT_SECONDS
        while is_port_in_use(port) and time.monotonic() < deadline:
            time.sleep(PROXY_POLL_INTERVAL_SECONDS)
        if is_port_in_use(port):
            _fail(
                f"Error: Port {port} could not be freed after stopping container.\n"
                "Another process may have bound to this port."
            )

    def _verify_container_health(self) -> None:
        """Wait for the new container; on timeout print its logs, remove it and exit."""
        if self.wait_until_ready():
            return
        name = self.container_name
        print(f"Error: Proxy container did not become ready within {PROXY_READY_TIMEOUT_SECONDS}s.", file=sys.stderr)
        logs_res = subprocess.run(["docker", "logs", name], capture_output=True, text=True)
        combined_logs = f"{logs_res.stdout or ''}{logs_res.stderr or ''}".strip()
        if combined_logs:
            print(f"Container logs:\n{combined_logs}", file=sys.stderr)
        self.stop(name)
        sys.exit(1)

    def _launch_failed(self, error: subprocess.CalledProcessError) -> NoReturn:
        """Report a failed ``docker run`` with the ports it tried to publish, then exit."""
        web = self.config.web_port if self.config.web_port is not None else "N/A"
        _fail(f"❌ Error: Failed to start Docker container on ports (proxy={self.config.port}, web={web}): {error}")
