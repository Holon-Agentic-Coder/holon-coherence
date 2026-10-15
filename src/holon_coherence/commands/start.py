"""Proxy server startup orchestration across host and Docker container."""

from __future__ import annotations

import contextlib
import os
import shutil
import socket
import subprocess
import sys
import time
from typing import Any, NamedTuple

from holon_coherence.ca_generator import generate_root_ca
from holon_coherence.commands._dispatch import get_cli
from holon_coherence.commands.docker_ops import (
    CONTAINER_NAME,
    check_docker_daemon,
    ensure_docker_image,
    is_container_bound_to_port,
    is_container_running,
    stop_proxy_container,
)
from holon_coherence.commands.runner import merge_no_proxy_values
from holon_coherence.commands.web_token import resolve_web_password, save_web_token
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
    plan_no_proxy_pruning,
)

DEFAULT_PROXY_PORT = 8080
PROXY_READY_TIMEOUT_SECONDS = 15.0
PROXY_POLL_INTERVAL_SECONDS = 0.2

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


def is_in_container() -> bool:
    """Return True if executing within a Docker container environment."""
    return os.path.exists("/.dockerenv") or os.environ.get("HOLON_IN_CONTAINER") == "1"


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
    cli = get_cli()
    in_use = getattr(cli, "is_port_in_use", is_port_in_use)
    for p in range(start_port, start_port + max_attempts):
        if not in_use(p, host=host):
            return p
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def wait_for_proxy_ready(port: int, timeout: float = PROXY_READY_TIMEOUT_SECONDS) -> bool:
    """Poll the proxy port until it accepts TCP connections or timeout occurs."""
    cli = get_cli()
    is_running = getattr(cli, "is_container_running", is_container_running)
    in_use = getattr(cli, "is_port_in_use", is_port_in_use)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not is_running(CONTAINER_NAME):
            return False
        if in_use(port):
            return True
        time.sleep(PROXY_POLL_INTERVAL_SECONDS)
    return False


def docker_host_alias_args() -> list[str]:
    """Flags making the Docker host reachable from inside the proxy container."""
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
    """Check from inside the container that the Docker host gateway answers on ``port``."""
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
    """Turn a ``--local-llm-base`` value into the route a runner session applies."""
    cli = get_cli()
    merger = getattr(cli, "merge_no_proxy_values", merge_no_proxy_values)
    get_addrs = getattr(cli, "detect_host_addresses", detect_host_addresses)

    target = parse_local_target(raw_base)
    if target is None:
        return None
    host_addresses = get_addrs()
    targets = expand_equivalence_class(target, host_addresses)
    return LocalLlmRoute(
        target=target,
        targets=targets,
        container_env_value=encode_targets(targets),
        host_addresses=host_addresses,
        no_proxy_plan=plan_no_proxy_pruning(merger(), target, host_addresses),
    )


def report_local_llm_route(route: LocalLlmRoute, reachable: bool, detail: str) -> tuple[str, ...]:
    """Print what interception means for this session and return entries to drop from ``NO_PROXY``."""
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
    """Ensure the holon-coherence optimization proxy is running in the background and healthy."""
    cli = get_cli()
    check_daemon = getattr(cli, "check_docker_daemon", check_docker_daemon)
    in_use = getattr(cli, "is_port_in_use", is_port_in_use)
    is_running = getattr(cli, "is_container_running", is_container_running)
    is_bound = getattr(cli, "is_container_bound_to_port", is_container_bound_to_port)
    get_spec = getattr(cli, "container_host_local_spec", container_host_local_spec)
    is_covered = getattr(cli, "host_local_covered", host_local_covered)
    stop_container = getattr(cli, "stop_proxy_container", stop_proxy_container)
    ensure_image = getattr(cli, "ensure_docker_image", ensure_docker_image)
    get_alias_args = getattr(cli, "docker_host_alias_args", docker_host_alias_args)
    get_host_local_args = getattr(cli, "host_local_container_args", host_local_container_args)
    wait_ready = getattr(cli, "wait_for_proxy_ready", wait_for_proxy_ready)

    ok, err_msg = check_daemon()
    if not ok:
        print(err_msg, file=sys.stderr)
        sys.exit(1)

    was_running = False
    if in_use(port):
        if is_running(CONTAINER_NAME) and is_bound(port, CONTAINER_NAME):
            if not host_local_spec:
                return False
            existing_spec = get_spec()
            if is_covered(host_local_spec, existing_spec):
                return False
            was_running = True
            merged_targets = (*decode_targets(existing_spec), *decode_targets(host_local_spec))
            host_local_spec = encode_targets(merged_targets)
            print(
                f"♻️  Running proxy container does not intercept {host_local_spec}; recreating it. "
                "Other sessions sharing this proxy will briefly lose interception."
            )
            stop_container()
            deadline = time.monotonic() + 10.0
            while in_use(port) and time.monotonic() < deadline:
                time.sleep(PROXY_POLL_INTERVAL_SECONDS)
            if in_use(port):
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
    elif is_running(CONTAINER_NAME):
        if is_bound(port, CONTAINER_NAME):
            if wait_ready(port):
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

    ensure_image(image, rebuild=False)

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
        *get_alias_args(),
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
        *get_host_local_args(host_local_spec),
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

    if not wait_ready(port):
        print(f"Error: Proxy container did not become ready within {PROXY_READY_TIMEOUT_SECONDS}s.", file=sys.stderr)
        logs_res = subprocess.run(["docker", "logs", CONTAINER_NAME], capture_output=True, text=True)
        combined_logs = f"{logs_res.stdout or ''}{logs_res.stderr or ''}".strip()
        if combined_logs:
            print(f"Container logs:\n{combined_logs}", file=sys.stderr)
        stop_container()
        sys.exit(1)

    return not was_running


def handle_start(args: Any) -> None:
    """Execute proxy start command in container or on host."""
    cli = get_cli()
    in_container = getattr(cli, "is_in_container", is_in_container)
    check_daemon = getattr(cli, "check_docker_daemon", check_docker_daemon)
    plan_route = getattr(cli, "plan_local_llm_route", plan_local_llm_route)
    ensure_image = getattr(cli, "ensure_docker_image", ensure_docker_image)
    get_alias_args = getattr(cli, "docker_host_alias_args", docker_host_alias_args)
    get_host_local_args = getattr(cli, "host_local_container_args", host_local_container_args)
    resolve_pwd = getattr(cli, "resolve_web_password", resolve_web_password)
    save_tok = getattr(cli, "save_web_token", save_web_token)

    start_host_local_spec = os.environ.get(HOST_LOCAL_ENV_VAR, "").strip()
    if getattr(args, "local_llm_base", None):
        start_route = plan_route(args.local_llm_base)
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

    # In-container execution
    if in_container():
        os.environ[HOST_LOCAL_ENV_VAR] = start_host_local_spec
        pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        addon_path = os.path.join(pkg_dir, "mitm_addon.py")
        tool = "mitmweb" if args.web else "mitmdump"
        tool_candidate = os.path.join(os.path.dirname(sys.executable), tool)
        tool_path = tool_candidate if os.path.isfile(tool_candidate) else (shutil.which(tool) or tool)

        cmd = [tool_path, "-s", addon_path, "--listen-port", str(args.port)]
        web_password = None
        if args.web:
            web_password = resolve_pwd(getattr(args, "web_password", None))
            save_tok(web_password)
            cmd.extend(
                [
                    "--web-host",
                    "0.0.0.0",
                    "--web-port",
                    str(args.web_port),
                    "--set",
                    f"web_password={web_password}",
                ]
            )
        print(f"🚀 Starting holon-coherence proxy via {tool} on port {args.port}...")
        if args.web and web_password:
            print(f"🌐 Web dashboard exposed at http://127.0.0.1:{args.web_port}/?token={web_password}")
            print(f"🔑 Web API Key / Password: {web_password}")
        try:
            subprocess.run(cmd, check=True)
        except KeyboardInterrupt:
            print("\nShutting down holon-coherence proxy.")
        return

    # On host: check docker daemon
    ok, err = check_daemon()
    if not ok:
        print(err, file=sys.stderr)
        sys.exit(1)

    in_use = getattr(cli, "is_port_in_use", is_port_in_use)
    find_port = getattr(cli, "find_available_port", find_available_port)

    # Check proxy port conflict and fallback
    actual_proxy_port = args.port
    if in_use(actual_proxy_port):
        actual_proxy_port = find_port(actual_proxy_port + 1)
        print(f"⚠️  Port {args.port} is already in use on host. Mapping proxy to host port {actual_proxy_port} instead.")

    ca_dir = os.path.expanduser("~/.holon/proxy-ca")
    cache_dir = os.path.expanduser("~/.holon/cache")
    logs_dir = os.path.expanduser("~/.holon/logs")
    for d in (ca_dir, cache_dir, logs_dir):
        os.makedirs(d, mode=0o700, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(d, 0o700)

    ca_cert = os.path.join(ca_dir, "mitmproxy-ca-cert.pem")
    if not os.path.exists(ca_cert):
        with contextlib.suppress(Exception):
            generate_root_ca(output_dir=ca_dir)

    ensure_image(args.image, rebuild=args.build)

    subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    docker_cmd = [
        "docker",
        "run",
        "--init",
        "--name",
        CONTAINER_NAME,
        *get_alias_args(),
        "-p",
        f"127.0.0.1:{actual_proxy_port}:8080",
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
        f"HOLON_PROXY_PORT={actual_proxy_port}",
        *get_host_local_args(start_host_local_spec),
    ]

    web_password = None
    actual_web_port = getattr(args, "web_port", 8081)
    if args.web:
        web_password = resolve_pwd(getattr(args, "web_password", None))
        save_tok(web_password)
        if in_use(actual_web_port) or actual_web_port == actual_proxy_port:
            candidate_start = actual_web_port + 1
            actual_web_port = find_port(candidate_start)
            while actual_web_port == actual_proxy_port or in_use(actual_web_port):
                actual_web_port = find_port(actual_web_port + 1)
            print(
                f"⚠️  Port {args.web_port} is already in use on host. "
                f"Mapping web dashboard to host port {actual_web_port} instead."
            )
        docker_cmd.extend(["-p", f"127.0.0.1:{actual_web_port}:8081"])
        docker_cmd.extend(["-e", f"HOLON_COHERENCE_WEB_PASSWORD={web_password}"])

    if args.detach:
        docker_cmd.append("-d")
    else:
        docker_cmd.append("--rm")

    docker_cmd.append(args.image)
    docker_cmd.extend(["start", "--port", "8080"])
    if args.web:
        docker_cmd.extend(["--web", "--web-port", "8081"])

    print(f"🐳 Starting holon-coherence proxy via Docker container on port {actual_proxy_port}...")
    if args.web and web_password:
        print(f"🌐 Web dashboard exposed at http://127.0.0.1:{actual_web_port}/?token={web_password}")
        print(f"🔑 Web API Key / Password: {web_password}")

    if args.detach:
        try:
            subprocess.run(docker_cmd, check=True)
            print("✅ holon-coherence container running in background.")
            print("Use 'holon-coherence logs -f' to stream logs or 'holon-coherence stop' to shut down.")
        except subprocess.CalledProcessError as e:
            print(
                f"❌ Error: Failed to start Docker container on ports "
                f"(proxy={actual_proxy_port}, web={actual_web_port if args.web else 'N/A'}): {e}",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        try:
            subprocess.run(docker_cmd)
        except subprocess.CalledProcessError as e:
            print(
                f"❌ Error: Failed to start Docker container on ports "
                f"(proxy={actual_proxy_port}, web={actual_web_port if args.web else 'N/A'}): {e}",
                file=sys.stderr,
            )
            sys.exit(1)
        except KeyboardInterrupt:
            print("\nShutting down holon-coherence container...")
            subprocess.run(
                ["docker", "stop", CONTAINER_NAME],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
