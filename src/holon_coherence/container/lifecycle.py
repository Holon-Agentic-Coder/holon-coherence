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
from holon_coherence.container.image import ensure_docker_image
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
DOCKER_CMD_TIMEOUT_SECONDS = 5.0
CONTAINER_PROXY_PORT = 8080
CA_CERT_FILENAME = "mitmproxy-ca-cert.pem"
CA_PEM_FILENAME = "mitmproxy-ca.pem"
PRIVATE_CA_KEY_FILENAMES = (CA_PEM_FILENAME, "holon-root-ca.key")
PRIVATE_DIR_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
TRUTHY_ENV_VALUES = ("1", "true", "yes", "on")
FALSY_ENV_VALUES = ("0", "false", "no", "off")

_READINESS_PATHS = ("/holon/api/metrics", "/_holon/metrics")
_READINESS_NETWORK_ERRORS = (
    urllib.error.URLError,
    ConnectionRefusedError,
    OSError,
    TimeoutError,
    http.client.RemoteDisconnected,
    http.client.HTTPException,
)


def get_container_name(override: str | None = None) -> str:
    if override:
        return override
    return os.getenv("HOLON_CONTAINER_NAME", DEFAULT_CONTAINER_NAME)


def is_container_running(container_name: str | None = None) -> bool:
    name = container_name or get_container_name()
    try:
        res = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", name],
            capture_output=True,
            text=True,
            timeout=DOCKER_CMD_TIMEOUT_SECONDS,
        )
        return res.returncode == 0 and res.stdout.strip().lower() == "true"
    except (subprocess.TimeoutExpired, OSError):
        return False


def _docker_port_output(name: str) -> str | None:
    try:
        res = subprocess.run(
            ["docker", "port", name, f"{CONTAINER_PROXY_PORT}/tcp"],
            capture_output=True,
            text=True,
            timeout=DOCKER_CMD_TIMEOUT_SECONDS,
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
            timeout=DOCKER_CMD_TIMEOUT_SECONDS,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if fallback_res.returncode != 0:
        return None
    return fallback_res.stdout


def _mapped_host_port(line: str) -> int | None:
    host_part = line.strip().split("->")[-1].strip()
    if ":" not in host_part:
        return None
    try:
        return int(host_part.rsplit(":", 1)[1])
    except ValueError:
        return None


def is_container_bound_to_port(port: int, container_name: str | None = None) -> bool:
    output = _docker_port_output(container_name or get_container_name())
    if output is None:
        return False
    return any(_mapped_host_port(line) == port for line in output.splitlines() if line.strip())


def check_docker_daemon() -> tuple[bool, str]:
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
            timeout=DOCKER_CMD_TIMEOUT_SECONDS,
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
    ok, err_msg = check_docker_daemon()
    if not ok:
        _fail(err_msg)


def is_in_container() -> bool:
    return os.path.exists("/.dockerenv") or os.environ.get("HOLON_IN_CONTAINER") == "1"


def is_start_passive(passive_flag: bool = False) -> bool:
    if passive_flag:
        return True
    if os.getenv("HOLON_PASSIVE_MONITORING", "0").lower().strip() in TRUTHY_ENV_VALUES:
        return True
    return os.getenv("COHERENCE_TOKEN_REDUCTION", "1").lower().strip() in FALSY_ENV_VALUES


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
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
    for p in range(start_port, start_port + max_attempts):
        if not is_port_in_use(p, host=host):
            return p
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def docker_host_alias_args() -> list[str]:
    return ["--add-host", f"{GATEWAY_HOSTNAME}:host-gateway"]


def host_local_container_args(host_local_spec: str) -> list[str]:
    if not host_local_spec:
        return []
    return ["-e", f"{HOST_LOCAL_ENV_VAR}={host_local_spec}"]


def container_host_local_spec(container_name: str | None = None) -> str:
    name = container_name or get_container_name()
    try:
        res = subprocess.run(
            ["docker", "inspect", "-f", "{{range .Config.Env}}{{println .}}{{end}}", name],
            capture_output=True,
            text=True,
            timeout=DOCKER_CMD_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    for line in (res.stdout or "").splitlines():
        if line.startswith(f"{HOST_LOCAL_ENV_VAR}="):
            return line.split("=", 1)[1].strip()
    return ""


def host_local_covered(required_spec: str, existing_spec: str) -> bool:
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
    print(message, file=sys.stderr)
    sys.exit(1)


class _Probe(enum.Enum):
    READY = "ready"
    NEXT_ENDPOINT = "next-endpoint"
    RETRY = "retry"


def _urlopen_no_proxy(req: urllib.request.Request, timeout: float) -> Any:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(req, timeout=timeout)


def _probe_readiness_url(url: str) -> _Probe:
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
    for path in _READINESS_PATHS:
        outcome = _probe_readiness_url(f"http://127.0.0.1:{port}{path}")
        if outcome is _Probe.READY:
            return True
        if outcome is _Probe.RETRY:
            return False
    return False


def _poll_until_ready(port: int, container_name: str, timeout: float, poll_interval: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_container_running(container_name):
            return False
        if _probe_proxy_endpoints(port):
            return True
        time.sleep(poll_interval)
    return False


@dataclass(frozen=True)
class ProxyLifecycleConfig:
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
    return (
        os.path.expanduser(config.ca_dir),
        os.path.expanduser(config.cache_dir),
        os.path.expanduser(config.logs_dir),
    )


def _prepare_proxy_directories(ca_dir: str, cache_dir: str, logs_dir: str) -> None:
    for d in (ca_dir, cache_dir, logs_dir):
        os.makedirs(d, mode=PRIVATE_DIR_MODE, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(d, PRIVATE_DIR_MODE)


def _harden_ca_key_files(ca_dir: str) -> None:
    with contextlib.suppress(OSError):
        for fname in os.listdir(ca_dir):
            if fname in PRIVATE_CA_KEY_FILENAMES or fname.endswith(".key"):
                path = os.path.join(ca_dir, fname)
                with contextlib.suppress(OSError):
                    os.chmod(path, PRIVATE_FILE_MODE)


def _web_inspector_args(actual_web_port: int | None, env_file: str | None = None) -> list[str]:
    if actual_web_port is None:
        return []
    args = ["-p", f"127.0.0.1:{actual_web_port}:{DEFAULT_WEB_PORT}"]
    if env_file:
        args.extend(["--env-file", env_file])
    return args


def _build_docker_run_args(
    config: ProxyLifecycleConfig, actual_port: int, actual_web_port: int | None, env_file: str | None = None
) -> list[str]:
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
        *_web_inspector_args(actual_web_port, env_file),
        config.image,
        "start",
        "--port",
        str(CONTAINER_PROXY_PORT),
    ]
    if actual_web_port is not None:
        cmd.extend(["--web", "--web-port", str(DEFAULT_WEB_PORT)])
    return cmd


def _resolve_proxy_tool(tool: str) -> str:
    candidate = os.path.join(os.path.dirname(sys.executable), tool)
    return candidate if os.path.isfile(candidate) else (shutil.which(tool) or tool)


def _addon_path() -> str:
    pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(pkg_dir, "mitm_addon.py")


class _Existing(enum.Enum):
    NONE = "none"
    REUSE = "reuse"
    RECREATE = "recreate"


class ProxyLifecycle:
    def __init__(self, config: ProxyLifecycleConfig | None = None) -> None:
        self.config = config or ProxyLifecycleConfig()

    @property
    def container_name(self) -> str:
        return self.config.container_name or get_container_name()

    def ensure_ca(self) -> tuple[str, str]:
        ca_path, cache_dir, logs_dir = _mount_dirs(self.config)
        _prepare_proxy_directories(ca_path, cache_dir, logs_dir)

        ca_cert = os.path.join(ca_path, CA_CERT_FILENAME)
        ca_pem = os.path.join(ca_path, CA_PEM_FILENAME)
        if not os.path.exists(ca_cert) or not os.path.exists(ca_pem):
            with contextlib.suppress(Exception):
                generate_root_ca(output_dir=ca_path)

        _harden_ca_key_files(ca_path)
        return ca_cert, ca_pem

    def wait_until_ready(
        self,
        timeout_seconds: float = PROXY_READY_TIMEOUT_SECONDS,
        poll_interval: float = PROXY_POLL_INTERVAL_SECONDS,
    ) -> bool:
        return _poll_until_ready(self.config.port, self.container_name, timeout_seconds, poll_interval)

    def prepare(self) -> None:
        self.ensure_ca()
        ensure_docker_image(self.config.image, rebuild=self.config.rebuild)
        with contextlib.suppress(subprocess.TimeoutExpired, OSError):
            subprocess.run(
                ["docker", "rm", "-f", self.container_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=DOCKER_CMD_TIMEOUT_SECONDS,
            )

    def start(self, recreate_if_mismatch: bool = True) -> bool:
        from holon_coherence.commands.web_token import web_password_env_file

        require_docker_daemon()
        existing = self._reconcile_existing(recreate_if_mismatch)
        if existing is _Existing.REUSE:
            return False

        self.prepare()
        port = self.config.port
        print(f"🐳 Starting background optimization proxy container on port {port}...")
        secret = self.config.web_password if self.config.web_port is not None else None
        with web_password_env_file(secret) as env_file:
            run_res = subprocess.run(
                _build_docker_run_args(self.config, port, self.config.web_port, env_file),
                capture_output=True,
                text=True,
            )
        if run_res.returncode != 0:
            print(f"Error starting proxy container: {run_res.stderr.strip()}", file=sys.stderr)
            sys.exit(run_res.returncode)

        self._verify_container_health()
        return existing is _Existing.NONE

    def launch(self) -> None:
        from holon_coherence.commands.web_token import web_password_env_file

        secret = self.config.web_password if self.config.web_port is not None else None
        with web_password_env_file(secret) as env_file:
            docker_cmd = _build_docker_run_args(self.config, self.config.port, self.config.web_port, env_file)
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
        from holon_coherence.commands.web_token import mitmweb_password_config

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
                    "web_open_browser=false",
                ]
            )
        print(f"🚀 Starting holon-coherence proxy via {tool} on port {self.config.port}...")
        if banner:
            print(banner)
        secret = self.config.web_password if web_port is not None else None
        try:
            with mitmweb_password_config(secret):
                subprocess.run(cmd, check=True)
        except KeyboardInterrupt:
            print("\nShutting down holon-coherence proxy.")

    def stop(self, container_name: str | None = None) -> bool:
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
        return f" '{self.container_name}'" if self.config.container_name else ""

    def _reconcile_existing(self, recreate_if_mismatch: bool) -> _Existing:
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
        web = self.config.web_port if self.config.web_port is not None else "N/A"
        _fail(f"❌ Error: Failed to start Docker container on ports (proxy={self.config.port}, web={web}): {error}")
