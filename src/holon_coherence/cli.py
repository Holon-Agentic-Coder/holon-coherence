"""CLI entrypoint for holon-coherence optimization proxy and coding agent runners."""

from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import time
from typing import Any, NamedTuple

from holon_coherence.ca_generator import generate_root_ca
from holon_coherence.host_local import (
    GATEWAY_HOSTNAME,
    HOST_LOCAL_ENV_VAR,
    LocalTarget,
    PruningPlan,
    decode_targets,
    detect_host_addresses,
    encode_targets,
    expand_equivalence_class,
    parse_local_target,
    parse_no_proxy,
    plan_no_proxy_pruning,
)

DEFAULT_PROXY_PORT = 8080
PROXY_READY_TIMEOUT_SECONDS = 15.0
PROXY_POLL_INTERVAL_SECONDS = 0.25
DOCKER_BUILD_TIMEOUT_SECONDS = 600
NO_PROXY_HOSTS = "localhost,127.0.0.1,::1,169.254.169.254,api.github.com,github.com"
CONTAINER_NAME = "holon-coherence"

# Resolves the Docker host gateway inside the container and dials a TCP port on it.
# Used to prove a host-local endpoint is reachable before NO_PROXY is pruned.
_CONTAINER_GATEWAY_PROBE = (
    "import socket,sys\n"
    "try:\n"
    # SECURITY: GATEWAY_HOSTNAME is a module constant (never user input); !r escaping is safe here.
    # If GATEWAY_HOSTNAME ever becomes configurable, replace this with env/argv to prevent injection.
    f"    infos = socket.getaddrinfo({GATEWAY_HOSTNAME!r}, None, type=socket.SOCK_STREAM)\n"
    "except OSError:\n"
    "    infos = []\n"
    "if not infos:\n"
    "    sys.stderr.write('gateway name does not resolve\\n')\n"
    "    sys.exit(3)\n"
    "candidates = []\n"
    "fallback = None\n"
    "for info in infos:\n"
    "    host = info[4][0].strip('[]')\n"
    "    if host.startswith('127.') or host == '::1':\n"
    "        continue\n"
    "    if '.' in host and host not in candidates:\n"
    "        candidates.append(host)\n"
    "    fallback = fallback or host\n"
    "if fallback and fallback not in candidates:\n"
    "    candidates.append(fallback)\n"
    "if not candidates:\n"
    "    sys.stderr.write('no non-loopback gateway IP found\\n')\n"
    "    sys.exit(3)\n"
    "port = int(sys.argv[1])\n"
    "last_err = None\n"
    "for ip in candidates:\n"
    "    try:\n"
    "        s = socket.create_connection((ip, port), timeout=3)\n"
    "        s.close()\n"
    "        sys.exit(0)\n"
    "    except OSError as err:\n"
    "        last_err = err\n"
    "sys.stderr.write(f'failed to connect to gateway: {last_err}\\n')\n"
    "sys.exit(1)\n"
)


class LocalLlmRoute(NamedTuple):
    """A validated ``--local-llm-base`` declaration, ready to be applied to a session."""

    target: LocalTarget
    targets: tuple[LocalTarget, ...]
    container_env_value: str
    host_addresses: tuple[str, ...]
    no_proxy_plan: PruningPlan

    @property
    def prunes_no_proxy(self) -> tuple[str, ...]:
        """``NO_PROXY`` entries that must go for the proxy to see this endpoint."""
        return self.no_proxy_plan.remove


SUPPORTED_AGENTS = ("agy", "antigravity", "claude", "codex", "opencode", "pi")

AGENT_BINARY_MAP: dict[str, list[str]] = {
    "agy": ["agy", "antigravity"],
    "antigravity": ["agy", "antigravity"],
    "claude": ["claude"],
    "codex": ["codex", "chatgpt"],
    "opencode": ["opencode"],
    "pi": ["pi"],
}


def is_in_container() -> bool:
    """Return True if executing within a Docker container environment."""
    return os.path.exists("/.dockerenv") or os.environ.get("HOLON_IN_CONTAINER") == "1"


def find_system_ca_bundle() -> str | None:
    """Locate host system or certifi CA certificate bundle."""
    for env_var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        val = os.environ.get(env_var)
        if (
            val
            and not val.endswith(("holon-merged-ca-bundle.crt", "mitmproxy-ca-cert.pem", "holon-root-ca.crt"))
            and os.path.isfile(val)
        ):
            return os.path.abspath(val)

    try:
        cafile = ssl.get_default_verify_paths().cafile
        if (
            cafile
            and not cafile.endswith(("holon-merged-ca-bundle.crt", "mitmproxy-ca-cert.pem", "holon-root-ca.crt"))
            and os.path.isfile(cafile)
        ):
            return cafile
    except Exception:
        pass

    try:
        import certifi

        c_path = certifi.where()
        if os.path.isfile(c_path):
            return c_path
    except ImportError:
        pass

    common_paths = [
        "/etc/ssl/cert.pem",  # macOS / FreeBSD
        "/etc/ssl/certs/ca-certificates.crt",  # Debian / Ubuntu
        "/etc/pki/tls/certs/ca-bundle.crt",  # Fedora / RHEL
        "/etc/ssl/ca-bundle.pem",  # OpenSUSE
    ]
    for path in common_paths:
        if os.path.isfile(path):
            return path
    return None


def get_or_create_merged_ca_bundle(ca_cert_path: str) -> str:
    """Create or return a merged CA certificate bundle combining system/certifi CA roots and the Holon CA.

    This ensures direct connections via NO_PROXY succeed without TLS failures while still trusting
    the Holon proxy for intercepted endpoints.
    """
    ca_cert_path = os.path.abspath(ca_cert_path)
    target_dir = os.path.dirname(ca_cert_path)
    merged_path = os.path.join(target_dir, "holon-merged-ca-bundle.crt")

    if not os.path.isfile(ca_cert_path):
        return ca_cert_path

    system_ca = find_system_ca_bundle()
    if os.path.isfile(merged_path):
        try:
            merged_mtime = os.path.getmtime(merged_path)
            ca_mtime = os.path.getmtime(ca_cert_path)
            if merged_mtime >= ca_mtime and (
                not system_ca or not os.path.isfile(system_ca) or merged_mtime >= os.path.getmtime(system_ca)
            ):
                return merged_path
        except OSError:
            pass

    try:
        with open(ca_cert_path, encoding="utf-8", errors="replace") as f:
            holon_cert = f.read().strip()
    except OSError:
        return ca_cert_path

    system_certs = ""
    if system_ca and os.path.isfile(system_ca):
        try:
            with open(system_ca, encoding="utf-8", errors="replace") as f:
                system_certs = f.read().strip()
        except OSError:
            pass

    if not system_certs:
        merged_content = f"{holon_cert}\n"
    elif holon_cert in system_certs:
        merged_content = f"{system_certs}\n"
    else:
        merged_content = f"{system_certs}\n\n{holon_cert}\n"

    try:
        os.makedirs(target_dir, exist_ok=True)
        tmp_path = f"{merged_path}.tmp.{os.getpid()}"
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(merged_content)
        os.replace(tmp_path, merged_path)
        return merged_path
    except OSError:
        with contextlib.suppress(OSError):
            if "tmp_path" in locals() and os.path.exists(tmp_path):
                os.remove(tmp_path)
        return ca_cert_path


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check whether a TCP port is currently open and accepting connections."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


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


def wait_for_proxy_ready(port: int, timeout: float = PROXY_READY_TIMEOUT_SECONDS) -> bool:
    """Poll the proxy port until it accepts TCP connections or timeout occurs."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not is_container_running(CONTAINER_NAME):
            return False
        if is_port_in_use(port):
            return True
        time.sleep(PROXY_POLL_INTERVAL_SECONDS)
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

    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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


def docker_host_alias_args() -> list[str]:
    """Flags making the Docker host reachable from inside the proxy container.

    ``host-gateway`` is honoured by Docker Engine and Docker Desktop alike; without it the
    gateway name exists only as a Docker Desktop convention and Linux containers cannot
    resolve it at all.
    """
    return ["--add-host", f"{GATEWAY_HOSTNAME}:host-gateway"]


def host_local_container_args(host_local_spec: str) -> list[str]:
    """Environment flags passing the host-local allow list into the container."""
    if not host_local_spec:
        return []
    return ["-e", f"{HOST_LOCAL_ENV_VAR}={host_local_spec}"]


def container_host_local_spec(container_name: str = CONTAINER_NAME) -> str:
    """Read back the host-local allow list a running proxy container was started with."""
    try:
        res = subprocess.run(
            ["docker", "inspect", "-f", "{{range .Config.Env}}{{println .}}{{end}}", container_name],
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


def probe_host_local_reachable(
    port: int, timeout: float = 15.0, container_name: str = CONTAINER_NAME
) -> tuple[bool, str]:
    """Check from inside the container that the Docker host gateway answers on ``port``.

    Pruning ``NO_PROXY`` turns a loopback call that works today into one that depends on the
    container reaching the host, so it is only done once this probe succeeds.
    """
    for interpreter in ("python3", "python"):
        try:
            res = subprocess.run(
                ["docker", "exec", container_name, interpreter, "-c", _CONTAINER_GATEWAY_PROBE, str(port)],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return False, "probe timed out"
        except OSError as exc:
            return False, str(exc)

        if res.returncode == 0:
            return True, ""
        err_lower = (res.stderr or "").lower()
        if res.returncode in (126, 127) or any(
            needle in err_lower for needle in ("no such file", "not found", "executable file not found")
        ):
            continue
        detail = (res.stderr or res.stdout or "").strip().splitlines()
        return False, detail[-1] if detail else f"exit code {res.returncode}"
    return False, "unreachable"


def plan_local_llm_route(raw_base: str) -> LocalLlmRoute | None:
    """Turn a ``--local-llm-base`` value into the route a runner session applies.

    Returns ``None`` when the value cannot be parsed; callers report the failure.
    """
    target = parse_local_target(raw_base)
    if target is None:
        return None
    host_addresses = detect_host_addresses()
    targets = expand_equivalence_class(target, host_addresses)
    return LocalLlmRoute(
        target=target,
        targets=targets,
        container_env_value=encode_targets(targets),
        host_addresses=host_addresses,
        no_proxy_plan=plan_no_proxy_pruning(merge_no_proxy_values(), target, host_addresses),
    )


def report_local_llm_route(route: LocalLlmRoute, reachable: bool, detail: str) -> tuple[str, ...]:
    """Print what interception means for this session and return entries to drop from ``NO_PROXY``.

    When the container cannot reach the host the bypass is deliberately left in place:
    keeping the original direct route beats routing a working call into a broken one.
    """
    plan = route.no_proxy_plan
    print(
        f"🔌 Local LLM endpoint {route.target.canonical}: proxy-side allow list "
        f"[{route.container_env_value}] -> {GATEWAY_HOSTNAME}"
    )

    if plan.blocked_by_wildcard:
        print(
            "⚠️  NO_PROXY contains '*', which bypasses the proxy for everything; refusing to "
            "rewrite it. Remove the wildcard to intercept the local endpoint.",
            file=sys.stderr,
        )
        return ()

    if not reachable:
        if plan.remove:
            print(
                f"⚠️  Container cannot reach {route.target.canonical} via {GATEWAY_HOSTNAME} ({detail}).\n"
                f"   Keeping NO_PROXY as-is ({', '.join(plan.remove)} retained), so the agent talks to the "
                "endpoint directly and traffic is NOT intercepted.\n"
                "   A server bound only to 127.0.0.1 is unreachable this way on Linux: bind it to a "
                "non-loopback interface (e.g. OLLAMA_HOST=0.0.0.0, or 'systemctl edit ollama.service') and retry.",
                file=sys.stderr,
            )
        else:
            print(
                f"⚠️  Container cannot reach {route.target.canonical} via {GATEWAY_HOSTNAME} ({detail}).\n"
                f"   Because {route.target.canonical} is not in NO_PROXY, traffic will still be sent to the proxy "
                "and requests may fail (502 Bad Gateway or timeout).\n"
                "   Ensure the target server is listening and reachable from the host gateway, or add it to "
                "NO_PROXY to bypass the proxy directly.",
                file=sys.stderr,
            )
        return ()

    if not plan.remove:
        print(f"✅ {route.target.canonical} is not matched by NO_PROXY, so it is already intercepted.")
        return ()

    print(
        f"✂️  Removing {', '.join(plan.remove)} from the agent's NO_PROXY so {route.target.canonical} "
        "is intercepted (payload cleaning, caching, wire telemetry)."
    )
    print(
        "   Other loopback traffic now transits the proxy and is forwarded to the host unmodified; "
        "it stops working if the proxy is killed."
    )
    return plan.remove


def ensure_proxy_running(
    port: int = DEFAULT_PROXY_PORT,
    image: str = "holon-coherence:latest",
    host_local_spec: str = "",
) -> bool:
    """Ensure the holon-coherence optimization proxy is running in the background and healthy.

    Args:
        port: Host port the proxy is published on.
        image: Docker image to launch when nothing healthy exists yet.
        host_local_spec: Host-local authorities the container must be able to reach.

    Returns:
        bool: True if a brand-new container was launched, False if an existing healthy container was reused
        or recreated from an already-running container.
    """
    ok, err_msg = check_docker_daemon()
    if not ok:
        print(err_msg, file=sys.stderr)
        sys.exit(1)

    was_running = False
    # Check if proxy is already healthy and listening on port
    if is_port_in_use(port):
        if is_container_running(CONTAINER_NAME) and is_container_bound_to_port(port, CONTAINER_NAME):
            if not host_local_spec:
                return False
            existing_spec = container_host_local_spec()
            if host_local_covered(host_local_spec, existing_spec):
                # Proxy container is running and healthy, and already intercepts what we need.
                return False
            was_running = True
            merged_targets = (*decode_targets(existing_spec), *decode_targets(host_local_spec))
            host_local_spec = encode_targets(merged_targets)
            print(
                f"♻️  Running proxy container does not intercept {host_local_spec}; recreating it. "
                "Other sessions sharing this proxy will briefly lose interception."
            )
            stop_proxy_container()
            deadline = time.monotonic() + 10.0
            while is_port_in_use(port) and time.monotonic() < deadline:
                time.sleep(PROXY_POLL_INTERVAL_SECONDS)
            if is_port_in_use(port):
                print(
                    f"Error: Port {port} could not be freed after stopping container.\n"
                    "Another process may have bound to this port.",
                    file=sys.stderr,
                )
                sys.exit(1)
        else:
            print(
                f"Error: Port {port} is already in use by another process.\n"
                "Please free the port or specify another port via --port or HOLON_PROXY_PORT.",
                file=sys.stderr,
            )
            sys.exit(1)
    elif is_container_running(CONTAINER_NAME):
        if is_container_bound_to_port(port, CONTAINER_NAME):
            if wait_for_proxy_ready(port):
                return False
            print(
                f"Error: A holon-coherence proxy container is running for port {port}, but is not responding.\n"
                "Please restart it using 'holon-coherence stop' and retry.",
                file=sys.stderr,
            )
        else:
            print(
                "Error: A holon-coherence proxy container is already running on a different port.\n"
                f"Stop it first using 'holon-coherence stop' before launching on port {port}.",
                file=sys.stderr,
            )
        sys.exit(1)

    # Ensure Root CA and directories exist
    ca_dir = os.path.expanduser("~/.holon/proxy-ca")
    cache_dir = os.path.expanduser("~/.holon/cache")
    logs_dir = os.path.expanduser("~/.holon/logs")
    os.makedirs(ca_dir, exist_ok=True)
    os.makedirs(cache_dir, exist_ok=True)
    os.makedirs(logs_dir, exist_ok=True)

    ca_cert = os.path.join(ca_dir, "mitmproxy-ca-cert.pem")
    if not os.path.exists(ca_cert):
        with contextlib.suppress(Exception):
            generate_root_ca(output_dir=ca_dir)

    # Check / build / pull Docker image
    ensure_docker_image(image, rebuild=False)

    # Remove stopped/stale container
    with contextlib.suppress(subprocess.TimeoutExpired, OSError):
        subprocess.run(
            ["docker", "rm", "-f", CONTAINER_NAME],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5.0,
        )

    docker_cmd = [
        "docker",
        "run",
        "-d",
        "--init",
        "--name",
        CONTAINER_NAME,
        *docker_host_alias_args(),
        "-p",
        f"127.0.0.1:{port}:8080",
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
        f"HOLON_PROXY_PORT={port}",
        *host_local_container_args(host_local_spec),
        image,
        "start",
        "--port",
        "8080",
    ]

    print(f"🐳 Starting background optimization proxy container on port {port}...")
    run_res = subprocess.run(docker_cmd, capture_output=True, text=True)
    if run_res.returncode != 0:
        print(f"Error starting proxy container: {run_res.stderr.strip()}", file=sys.stderr)
        sys.exit(run_res.returncode)

    # Wait for proxy to accept connections
    if not wait_for_proxy_ready(port):
        print(f"Error: Proxy container did not become ready within {PROXY_READY_TIMEOUT_SECONDS}s.", file=sys.stderr)
        logs_res = subprocess.run(["docker", "logs", CONTAINER_NAME], capture_output=True, text=True)
        combined_logs = f"{logs_res.stdout or ''}{logs_res.stderr or ''}".strip()
        if combined_logs:
            print(f"Container logs:\n{combined_logs}", file=sys.stderr)
        stop_proxy_container()
        sys.exit(1)

    return not was_running


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


def resolve_agent_binary(agent_name: str) -> str | None:
    """Find the executable binary for the specified agent on the host PATH."""
    candidates = AGENT_BINARY_MAP.get(agent_name, [agent_name])
    for candidate in candidates:
        path = shutil.which(candidate)
        if path:
            return path
    return None


def merge_no_proxy_values(env: dict[str, str] | None = None) -> str:
    """Combine the built-in ``NO_PROXY`` defaults with whatever the caller's environment sets."""
    environ = os.environ if env is None else env
    entries = [entry.strip() for entry in NO_PROXY_HOSTS.split(",") if entry.strip()]
    for var in ("NO_PROXY", "no_proxy"):
        value = environ.get(var)
        if value:
            entries.extend(entry.strip() for entry in value.split(",") if entry.strip())
    return ",".join(dict.fromkeys(entries))


def build_proxy_env(
    proxy_url: str,
    ca_cert_path: str | None = None,
    drop_no_proxy: tuple[str, ...] = (),
) -> dict[str, str]:
    """Construct environment variables for proxy routing and CA bundle trust.

    ``drop_no_proxy`` removes entries that would keep a declared host-local LLM endpoint
    away from the proxy (see ``plan_no_proxy_pruning``).
    """
    env: dict[str, str] = {
        "HTTP_PROXY": proxy_url,
        "HTTPS_PROXY": proxy_url,
        "ALL_PROXY": proxy_url,
        "http_proxy": proxy_url,
        "https_proxy": proxy_url,
        "all_proxy": proxy_url,
    }

    merged_no_proxy = merge_no_proxy_values()
    if drop_no_proxy:
        dropped = {entry.strip().lower() for entry in drop_no_proxy if entry.strip()}
        merged_no_proxy = ",".join(entry for entry in parse_no_proxy(merged_no_proxy) if entry.lower() not in dropped)
    env["NO_PROXY"] = merged_no_proxy
    env["no_proxy"] = merged_no_proxy

    # Certificate bundle resolution
    if ca_cert_path is None:
        # Allow custom CA certificate path via HOLON_CA_CERT env var (useful in CI/CD or containerized environments)
        env_ca = os.environ.get("HOLON_CA_CERT")
        if env_ca and os.path.exists(os.path.expanduser(env_ca)):
            ca_cert = os.path.expanduser(env_ca)
        else:
            ca_cert = os.path.expanduser("~/.holon/proxy-ca/mitmproxy-ca-cert.pem")
            if not os.path.exists(ca_cert):
                alt_ca = os.path.expanduser("~/.holon/certs/holon-root-ca.crt")
                if os.path.exists(alt_ca):
                    ca_cert = alt_ca
    else:
        ca_cert = os.path.expanduser(ca_cert_path)
        if not os.path.exists(ca_cert):
            alt_ca = os.path.join(os.path.dirname(ca_cert), "holon-root-ca.crt")
            if os.path.exists(alt_ca):
                ca_cert = alt_ca

    if os.path.exists(ca_cert):
        merged_bundle = get_or_create_merged_ca_bundle(ca_cert)
        env["SSL_CERT_FILE"] = merged_bundle
        env["REQUESTS_CA_BUNDLE"] = merged_bundle
        env["CURL_CA_BUNDLE"] = merged_bundle
        env["NODE_EXTRA_CA_CERTS"] = merged_bundle
        env["GIT_SSL_CAINFO"] = merged_bundle
    else:
        print(
            f"⚠️  Warning: CA certificate not found at '{ca_cert}'.\n"
            "Outbound TLS requests through the proxy may fail verification.\n"
            "Ensure 'holon-coherence start' has been run at least once or "
            "initialize CA with 'holon-coherence init-ca'.",
            file=sys.stderr,
        )

    return env


def build_agent_env(
    agent_name: str,
    port: int,
    drop_no_proxy: tuple[str, ...] = (),
) -> dict[str, str]:
    """Construct environment variables for the child agent subprocess.

    Configures proxy routing, merged CA bundle, and maps universal HOLON_AGENT_KEY
    to vendor keys without inspecting or validating native host auth if omitted.
    """
    env = os.environ.copy()
    proxy_url = f"http://127.0.0.1:{port}"
    env.update(build_proxy_env(proxy_url, drop_no_proxy=drop_no_proxy))

    # Credential mapping: HOLON_AGENT_KEY -> vendor keys
    # Invariant Rule 4: If HOLON_AGENT_KEY is omitted, runner never validates vendor keys;
    # child process transparently inherits native host auth sessions (e.g. ~/.gemini, ~/.claude.json).
    holon_key = env.get("HOLON_AGENT_KEY")
    if holon_key:
        normalized_agent = "agy" if agent_name == "antigravity" else agent_name
        if normalized_agent == "agy":
            env["GEMINI_API_KEY"] = holon_key
            env["AGY_USER_TOKEN"] = holon_key
        elif normalized_agent == "claude":
            env["ANTHROPIC_API_KEY"] = holon_key
        elif normalized_agent == "codex":
            env["OPENAI_API_KEY"] = holon_key
        elif normalized_agent == "opencode":
            env["OPENCODE_API_KEY"] = holon_key
        elif normalized_agent == "pi":
            env["PI_API_KEY"] = holon_key

    return env


def execute_interactive_process(cmd: list[str], env: dict[str, str]) -> int:
    """Execute child process with interactive stdio passthrough, signal forwarding, and exit code propagation.

    Preserves standard interactive TTY attachment (stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr)
    and terminal signal passthrough (SIGWINCH for window resizing, SIGINT/SIGTERM for interrupts).
    Falls back to subprocess.PIPE for stdin when sys.stdin is a pseudofile (e.g. in CI or redirected contexts).
    """

    # Determine whether sys.stdin has a real OS file descriptor (TTY or pipe).
    # In some contexts (CI, testing, pytest capture) sys.stdin is a StringIO pseudofile whose
    # fileno() raises io.UnsupportedOperation. Using such an object with Popen raises OSError.
    def _real_fd(stream: Any, default: int) -> Any:
        try:
            return stream if (stream and stream.fileno() >= 0) else default
        except Exception:
            return default

    stdin_fd = _real_fd(sys.stdin, subprocess.PIPE)
    stdout_fd = _real_fd(sys.stdout, subprocess.PIPE)
    stderr_fd = _real_fd(sys.stderr, subprocess.PIPE)

    try:
        proc = subprocess.Popen(cmd, env=env, stdin=stdin_fd, stdout=stdout_fd, stderr=stderr_fd)
    except OSError as err:
        print(f"Error: Failed to execute '{cmd[0]}': {err}", file=sys.stderr)
        return 126

    def _forward_signal(sig: int, frame: Any) -> None:
        if proc.poll() is None:
            with contextlib.suppress(ProcessLookupError, ValueError, OSError):
                proc.send_signal(sig)

    old_handlers: dict[int, Any] = {}
    forward_signals = [signal.SIGTERM]
    if hasattr(signal, "SIGHUP"):
        forward_signals.append(signal.SIGHUP)
    if hasattr(signal, "SIGWINCH"):
        forward_signals.append(signal.SIGWINCH)
    if sys.stdin and sys.stdin.isatty():
        with contextlib.suppress(ValueError, OSError):
            old_handlers[signal.SIGINT] = signal.signal(signal.SIGINT, signal.SIG_IGN)
    else:
        forward_signals.append(signal.SIGINT)

    for sig in forward_signals:
        with contextlib.suppress(ValueError, OSError):
            old_handlers[sig] = signal.signal(sig, _forward_signal)

    try:
        while proc.poll() is None:
            with contextlib.suppress(KeyboardInterrupt):
                proc.wait()
    finally:
        for sig, handler in old_handlers.items():
            with contextlib.suppress(ValueError, OSError):
                signal.signal(sig, handler)

    returncode = proc.returncode
    if returncode is not None and returncode < 0:
        return 128 + abs(returncode)
    return returncode if returncode is not None else 0


class RunnerFlags(NamedTuple):
    """Parsed runner flags extracted from raw argv before argparse takes over."""

    ephemeral: bool
    port: int | None
    agent_args: list[str]
    help_requested: bool = False
    local_llm_base: str | None = None


def extract_runner_flags(argv: list[str]) -> RunnerFlags:
    """Extract runner flags and ``--help`` from arguments, preserving agent argument order."""
    ephemeral = False
    port = None
    help_requested = False
    local_llm_base = None
    agent_args: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--ephemeral":
            ephemeral = True
            i += 1
        elif arg in ("--help", "-h"):
            help_requested = True
            i += 1
        elif arg == "--local-llm-base":
            if i + 1 >= len(argv) or argv[i + 1] == "--":
                print("Error: Option --local-llm-base requires an argument, e.g. localhost:8081.", file=sys.stderr)
                sys.exit(1)
            local_llm_base = argv[i + 1]
            i += 2
        elif arg.startswith("--local-llm-base="):
            val = arg.split("=", 1)[1]
            if not val:
                print("Error: Option --local-llm-base requires an argument, e.g. localhost:8081.", file=sys.stderr)
                sys.exit(1)
            local_llm_base = val
            i += 1
        elif arg == "--port":
            if i + 1 < len(argv) and argv[i + 1] != "--":
                try:
                    port = int(argv[i + 1])
                except ValueError:
                    print(f"Error: Argument to --port must be an integer, got '{argv[i + 1]}'.", file=sys.stderr)
                    sys.exit(1)
                if not (1 <= port <= 65535):
                    print(f"Error: Port must be between 1 and 65535, got {port}.", file=sys.stderr)
                    sys.exit(1)
                i += 2
            else:
                print("Error: Option --port requires an argument.", file=sys.stderr)
                sys.exit(1)
        elif arg.startswith("--port="):
            val = arg.split("=", 1)[1]
            if not val:
                print("Error: Option --port requires an argument.", file=sys.stderr)
                sys.exit(1)
            try:
                port = int(val)
            except ValueError:
                print(f"Error: Argument to --port must be an integer, got '{val}'.", file=sys.stderr)
                sys.exit(1)
            if not (1 <= port <= 65535):
                print(f"Error: Port must be between 1 and 65535, got {port}.", file=sys.stderr)
                sys.exit(1)
            i += 1
        elif arg == "--":
            agent_args.extend(argv[i + 1 :])
            break
        else:
            agent_args.append(arg)
            i += 1
    return RunnerFlags(ephemeral, port, agent_args, help_requested=help_requested, local_llm_base=local_llm_base)


def run_agent(
    agent_name: str,
    agent_args: list[str],
    ephemeral: bool = False,
    port: int | None = None,
    local_llm_base: str | None = None,
) -> int:
    """Launch the optimization proxy and execute the requested coding agent with full telemetry."""
    if port is not None and not (1 <= port <= 65535):
        print(f"Error: Port must be between 1 and 65535, got {port}.", file=sys.stderr)
        return 1

    if port is None:
        env_port = os.getenv("HOLON_PROXY_PORT")
        if env_port:
            try:
                parsed_port = int(env_port)
                if not (1 <= parsed_port <= 65535):
                    raise ValueError(f"Port {parsed_port} out of range")
                port = parsed_port
            except ValueError:
                print(
                    f"⚠️  Invalid HOLON_PROXY_PORT '{env_port}', falling back to {DEFAULT_PROXY_PORT}.", file=sys.stderr
                )
                port = DEFAULT_PROXY_PORT
        else:
            port = DEFAULT_PROXY_PORT

    binary_path = resolve_agent_binary(agent_name)
    if not binary_path:
        primary_bin = AGENT_BINARY_MAP.get(agent_name, [agent_name])[0]
        print(
            f"Error: Agent CLI binary '{primary_bin}' not found on PATH.\n"
            f"Please install '{primary_bin}' and ensure it is accessible in your PATH.",
            file=sys.stderr,
        )
        return 1

    # Ensure proxy is running
    if local_llm_base is None:
        env_base = os.getenv("HOLON_LOCAL_LLM_BASE")
        if env_base:
            local_llm_base = env_base.strip() or None

    route = None
    if local_llm_base is not None:
        route = plan_local_llm_route(local_llm_base)
        if route is None:
            print(
                f"Error: --local-llm-base '{local_llm_base}' is not a usable endpoint.\n"
                "Expected host:port or a base URL, e.g. localhost:8081, 127.0.0.1:8081, "
                "192.168.2.13:8081, http://localhost:11434/v1.",
                file=sys.stderr,
            )
            return 1
        if route.target.port == port:
            print(
                f"Error: --local-llm-base port ({route.target.port}) cannot be the same as proxy port ({port}).",
                file=sys.stderr,
            )
            return 1

    container_started = ensure_proxy_running(port=port, host_local_spec=route.container_env_value if route else "")

    drop_no_proxy: tuple[str, ...] = ()
    if route is not None:
        if route.target.port is None:
            print(
                "⚠️  --local-llm-base without a port skips the container reachability preflight; "
                "prefer localhost:8081 so the route can be verified before NO_PROXY is changed.",
                file=sys.stderr,
            )
            reachable, detail = True, "preflight skipped (no port given)"
        else:
            reachable, detail = probe_host_local_reachable(route.target.port)
        drop_no_proxy = report_local_llm_route(route, reachable, detail)

    # Build environment
    child_env = build_agent_env(agent_name, port, drop_no_proxy=drop_no_proxy)

    # Assemble command
    cmd = [binary_path, *agent_args]

    try:
        return execute_interactive_process(cmd, child_env)
    finally:
        if ephemeral and container_started:
            stop_proxy_container()


def _print_agent_help(agent_name: str) -> None:
    """Print help information for running an agent."""
    print(
        f"usage: holon-coherence {agent_name} [--ephemeral] [--port PORT] "
        "[--local-llm-base BASE] [--] [agent_args ...]\n"
    )
    print(f"Run {agent_name} coding agent with automated background proxy and wire optimization.\n")
    print("positional arguments:")
    print("  agent_args            Arguments passed directly to the agent CLI\n")
    print("options:")
    print("  --ephemeral           Stop and remove the proxy container when the agent exits")
    print(f"  --port PORT           Proxy listen port (default: {DEFAULT_PROXY_PORT} or HOLON_PROXY_PORT)")
    print(
        "  --local-llm-base BASE Host-local model server (e.g. localhost:8081) to intercept\n"
        f"                       and reroute via {GATEWAY_HOSTNAME} instead of bypassing the proxy\n"
    )
    print("note:")
    print("  Use '--' to pass flags directly to the underlying agent (e.g. '-- --help').")


def _print_run_agent_help() -> None:
    """Print help information for run-agent command."""
    agents_str = ", ".join(sorted(set(SUPPORTED_AGENTS)))
    print(
        "usage: holon-coherence run-agent <agent> [--ephemeral] [--port PORT] "
        "[--local-llm-base BASE] [--] [agent_args ...]\n"
    )
    print("Run a coding agent with automated background proxy and wire optimization.\n")
    print("positional arguments:")
    print(f"  agent                 Target agent ({agents_str})")
    print("  agent_args            Arguments passed directly to the agent CLI\n")
    print("options:")
    print("  --ephemeral           Stop and remove the proxy container when the agent exits")
    print(f"  --port PORT           Proxy listen port (default: {DEFAULT_PROXY_PORT} or HOLON_PROXY_PORT)")
    print(
        "  --local-llm-base BASE Host-local model server (e.g. localhost:8081) to intercept\n"
        f"                       and reroute via {GATEWAY_HOSTNAME} instead of bypassing the proxy\n"
    )
    print("note:")
    print("  Use '--' to pass flags directly to the underlying agent (e.g. '-- --help').")


def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv[1:]

    # Check for direct agent invocation or run-agent subcommand
    if argv:
        first = argv[0]
        if first in SUPPORTED_AGENTS:
            flags = extract_runner_flags(argv[1:])
            if flags.help_requested:
                _print_agent_help(first)
                sys.exit(0)
            sys.exit(
                run_agent(
                    first,
                    flags.agent_args,
                    ephemeral=flags.ephemeral,
                    port=flags.port,
                    local_llm_base=flags.local_llm_base,
                )
            )
        elif first == "run-agent":
            if not argv[1:]:
                _print_run_agent_help()
                sys.exit(1)
            flags = extract_runner_flags(argv[1:])
            if flags.help_requested:
                if flags.agent_args and flags.agent_args[0] in SUPPORTED_AGENTS:
                    _print_agent_help(flags.agent_args[0])
                else:
                    _print_run_agent_help()
                sys.exit(0)
            if not flags.agent_args:
                _print_run_agent_help()
                sys.exit(1)
            agent_target = flags.agent_args[0]
            if agent_target not in SUPPORTED_AGENTS:
                supported_list = ", ".join(sorted(set(SUPPORTED_AGENTS)))
                print(
                    f"Error: Unsupported agent '{agent_target}'. Supported agents: {supported_list}.",
                    file=sys.stderr,
                )
                sys.exit(1)
            sys.exit(
                run_agent(
                    agent_target,
                    flags.agent_args[1:],
                    ephemeral=flags.ephemeral,
                    port=flags.port,
                    local_llm_base=flags.local_llm_base,
                )
            )

    parser = argparse.ArgumentParser(
        prog="holon-coherence",
        description="High-coherence, low-entropy optimization gateway for fractal coding agents.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Start proxy
    start_parser = subparsers.add_parser("start", help="Start the optimization proxy sidecar (via Docker by default)")
    default_start_port = DEFAULT_PROXY_PORT
    env_proxy_port = os.getenv("HOLON_PROXY_PORT")
    if env_proxy_port:
        try:
            parsed_port = int(env_proxy_port)
            if 1 <= parsed_port <= 65535:
                default_start_port = parsed_port
        except ValueError:
            pass
    start_parser.add_argument(
        "--port",
        type=int,
        default=default_start_port,
        help=f"Proxy listen port (default: {DEFAULT_PROXY_PORT} or HOLON_PROXY_PORT)",
    )
    start_parser.add_argument(
        "--local-llm-base",
        default=os.getenv("HOLON_LOCAL_LLM_BASE"),
        help=f"Host-local model server (e.g. localhost:8081) to intercept and route via {GATEWAY_HOSTNAME}",
    )
    start_parser.add_argument("--web", action="store_true", help="Launch mitmweb dashboard on port 8081")
    start_parser.add_argument("--web-port", type=int, default=8081, help="Web dashboard port (default: 8081)")
    start_parser.add_argument("-d", "--detach", action="store_true", help="Run Docker container in background")
    start_parser.add_argument(
        "--image", default="holon-coherence:latest", help="Docker image tag (default: holon-coherence:latest)"
    )
    start_parser.add_argument("--build", action="store_true", help="Rebuild Docker image before starting")

    # Stop proxy container
    subparsers.add_parser("stop", help="Stop and remove running holon-coherence Docker container")

    # Status of proxy container
    subparsers.add_parser("status", help="Check status of holon-coherence Docker container")

    # Logs of proxy container
    logs_parser = subparsers.add_parser("logs", help="View logs of holon-coherence Docker container")
    logs_parser.add_argument("-f", "--follow", action="store_true", help="Follow log stream")

    # Build image
    build_parser = subparsers.add_parser("build", help="Build the holon-coherence Docker image")
    build_parser.add_argument(
        "--tag", default="holon-coherence:latest", help="Docker tag (default: holon-coherence:latest)"
    )

    # Init CA
    ca_parser = subparsers.add_parser("init-ca", help="Bootstrap self-signed Root CA certificates")
    ca_parser.add_argument("--output-dir", default=os.path.expanduser("~/.holon/proxy-ca"), help="Target CA directory")

    # Run command with inline proxy properties
    run_parser = subparsers.add_parser(
        "run",
        help="Run a command with inline proxy properties (avoids terminal session contamination)",
    )
    run_parser.add_argument(
        "--proxy-url",
        default="http://127.0.0.1:8080",
        help="Proxy URL (default: http://127.0.0.1:8080)",
    )
    run_parser.add_argument(
        "--ca-cert",
        default=os.path.expanduser("~/.holon/proxy-ca/mitmproxy-ca-cert.pem"),
        help="Path to CA certificate PEM",
    )
    run_parser.add_argument("cmd", nargs=argparse.REMAINDER, help="Command and arguments to execute")

    # Register run-agent and agent alias subparsers so they appear in `holon-coherence --help` output.
    # NOTE: These parsers are intentionally never dispatched here — actual agent invocation is handled
    # by the early-return block above (before parse_args() is reached). The subparsers exist purely
    # for documentation purposes so users can discover supported agents via --help.
    run_agent_parser = subparsers.add_parser("run-agent", help="Run a coding agent with automated background proxy")
    run_agent_parser.add_argument("agent", choices=sorted(set(SUPPORTED_AGENTS)), help="Target agent")
    run_agent_parser.add_argument(
        "--ephemeral", action="store_true", help="Stop proxy container after agent process exits"
    )
    run_agent_parser.add_argument(
        "--port", type=int, default=None, help=f"Proxy port (default: {DEFAULT_PROXY_PORT} or HOLON_PROXY_PORT)"
    )
    run_agent_parser.add_argument(
        "--local-llm-base",
        default=None,
        metavar="BASE",
        help="Host-local model server endpoint to intercept and reroute via the Docker host gateway",
    )
    run_agent_parser.add_argument("agent_args", nargs=argparse.REMAINDER, help="Arguments passed to the agent")

    for agent_alias in sorted(set(SUPPORTED_AGENTS)):
        alias_parser = subparsers.add_parser(
            agent_alias,
            help=f"Run {agent_alias} agent with automated background proxy",
        )
        alias_parser.add_argument(
            "--ephemeral", action="store_true", help="Stop proxy container after agent process exits"
        )
        alias_parser.add_argument(
            "--port", type=int, default=None, help=f"Proxy port (default: {DEFAULT_PROXY_PORT} or HOLON_PROXY_PORT)"
        )
        alias_parser.add_argument(
            "--local-llm-base",
            default=None,
            metavar="BASE",
            help="Host-local model server endpoint to intercept and reroute via the Docker host gateway",
        )
        alias_parser.add_argument("agent_args", nargs=argparse.REMAINDER, help="Arguments passed to the agent")

    args = parser.parse_args(argv)

    if not argv or args.command is None:
        parser.print_help(sys.stderr)
        sys.exit(1)

    if args.command == "init-ca":
        ca_cert, ca_key = generate_root_ca(output_dir=args.output_dir)
        print(f"✅ Root CA generated successfully:\n  Certificate: {ca_cert}\n  Key: {ca_key}")

    elif args.command == "build":
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        dockerfile = os.path.join(repo_root, "Dockerfile")
        if not os.path.exists(dockerfile):
            print(f"Error: Dockerfile not found at {dockerfile}.", file=sys.stderr)
            sys.exit(1)
        print(f"🐳 Building Docker image {args.tag}...")
        subprocess.run(["docker", "build", "-t", args.tag, repo_root], check=True)
        print(f"✅ Docker image '{args.tag}' built successfully.")

    elif args.command == "stop":
        stop_proxy_container()

    elif args.command == "status":
        subprocess.run(["docker", "ps", "-a", "--filter", f"name={CONTAINER_NAME}"])

    elif args.command == "logs":
        cmd = ["docker", "logs"]
        if args.follow:
            cmd.append("-f")
        cmd.append(CONTAINER_NAME)
        subprocess.run(cmd)

    elif args.command == "run":
        if not args.cmd:
            print("Error: No command specified to run.", file=sys.stderr)
            sys.exit(1)
        raw_cmd = args.cmd
        if raw_cmd[0] == "--":
            raw_cmd = raw_cmd[1:]
        if not raw_cmd:
            print("Error: No command specified after '--'.", file=sys.stderr)
            sys.exit(1)

        env = os.environ.copy()
        env.update(build_proxy_env(args.proxy_url, args.ca_cert))

        exit_code = execute_interactive_process(raw_cmd, env)
        sys.exit(exit_code)

    elif args.command == "start":
        start_host_local_spec = os.environ.get(HOST_LOCAL_ENV_VAR, "").strip()
        if getattr(args, "local_llm_base", None):
            start_route = plan_local_llm_route(args.local_llm_base)
            if start_route is None:
                print(
                    f"Error: --local-llm-base '{args.local_llm_base}' is not a usable endpoint.\n"
                    "Expected host:port or a base URL, e.g. localhost:8081, 127.0.0.1:8081, "
                    "192.168.2.13:8081, http://localhost:11434/v1.",
                    file=sys.stderr,
                )
                sys.exit(1)
            if start_route.target.port == args.port:
                print(
                    f"Error: --local-llm-base port ({start_route.target.port}) "
                    f"cannot be the same as proxy port ({args.port}).",
                    file=sys.stderr,
                )
                sys.exit(1)
            merged = (*decode_targets(start_host_local_spec), *start_route.targets)
            start_host_local_spec = encode_targets(merged)

        # Inside the container the image entrypoint runs this command, so mitmproxy is launched directly
        if is_in_container():
            os.environ[HOST_LOCAL_ENV_VAR] = start_host_local_spec
            addon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mitm_addon.py")
            tool = "mitmweb" if args.web else "mitmdump"
            tool_candidate = os.path.join(os.path.dirname(sys.executable), tool)
            tool_path = tool_candidate if os.path.isfile(tool_candidate) else (shutil.which(tool) or tool)

            cmd = [tool_path, "-s", addon_path, "--listen-port", str(args.port)]
            if args.web:
                cmd.extend(["--web-host", "0.0.0.0", "--web-port", str(args.web_port)])
            print(f"🚀 Starting holon-coherence proxy via {tool} on port {args.port}...")
            try:
                subprocess.run(cmd, check=True)
            except KeyboardInterrupt:
                print("\nShutting down holon-coherence proxy.")
            return

        # On host: check docker daemon
        ok, err = check_docker_daemon()
        if not ok:
            print(err, file=sys.stderr)
            sys.exit(1)

        ca_dir = os.path.expanduser("~/.holon/proxy-ca")
        cache_dir = os.path.expanduser("~/.holon/cache")
        logs_dir = os.path.expanduser("~/.holon/logs")
        os.makedirs(ca_dir, exist_ok=True)
        os.makedirs(cache_dir, exist_ok=True)
        os.makedirs(logs_dir, exist_ok=True)

        ca_cert = os.path.join(ca_dir, "mitmproxy-ca-cert.pem")
        if not os.path.exists(ca_cert):
            with contextlib.suppress(Exception):
                generate_root_ca(output_dir=ca_dir)

        # Check / build / pull Docker image
        ensure_docker_image(args.image, rebuild=args.build)

        # Remove existing container with the same name if stopped or stale
        subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        docker_cmd = [
            "docker",
            "run",
            "--init",
            "--name",
            CONTAINER_NAME,
            *docker_host_alias_args(),
            "-p",
            f"127.0.0.1:{args.port}:8080",
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
            f"HOLON_PROXY_PORT={args.port}",
            *host_local_container_args(start_host_local_spec),
        ]
        if args.web:
            docker_cmd.extend(["-p", f"127.0.0.1:{args.web_port}:8081"])
        if args.detach:
            docker_cmd.append("-d")
        else:
            docker_cmd.append("--rm")

        docker_cmd.append(args.image)
        docker_cmd.extend(["start", "--port", "8080"])
        if args.web:
            docker_cmd.extend(["--web", "--web-port", "8081"])

        print(f"🐳 Starting holon-coherence proxy via Docker container on port {args.port}...")
        if args.web:
            print(f"🌐 Web dashboard exposed at http://127.0.0.1:{args.web_port}")

        if args.detach:
            subprocess.run(docker_cmd, check=True)
            print("✅ holon-coherence container running in background.")
            print("Use 'holon-coherence logs -f' to stream logs or 'holon-coherence stop' to shut down.")
        else:
            try:
                subprocess.run(docker_cmd)
            except KeyboardInterrupt:
                print("\nShutting down holon-coherence container...")
                subprocess.run(
                    ["docker", "stop", CONTAINER_NAME],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
    else:
        parser.print_help(sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
