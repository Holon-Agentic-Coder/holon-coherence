"""Proxy server startup orchestration across host and Docker container."""

from __future__ import annotations

import argparse
import contextlib
import http.client
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any, NamedTuple

from holon_coherence.ca_generator import generate_root_ca
from holon_coherence.commands.docker_ops import (
    check_docker_daemon,
    ensure_docker_image,
    get_container_name,
    is_container_bound_to_port,
    is_container_running,
    stop_proxy_container,
)
from holon_coherence.commands.endpoints import ExposedEndpoints, print_endpoints
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
from holon_coherence.proxy.lifecycle import (
    ProxyLifecycle,
    ProxyLifecycleConfig,
    ProxyLifecycleHooks,
)

DEFAULT_PROXY_PORT = 8080
DEFAULT_WEB_PORT = 8081
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


WEB_INSPECTOR_ENV_VAR = "HOLON_COHERENCE_WEB"


def is_web_inspector_enabled(args: Any, in_container: bool) -> bool:
    """Decide whether ``start`` launches the mitmweb inspector.

    The inspector is opt-in: mitmweb keeps every captured flow (request and response bodies
    included) in memory for the life of the process and mitmproxy offers no option to cap that, so
    a long-running ``start -d`` proxy would grow without bound if it ran by default.

    An explicit ``--web`` / ``--no-web`` always wins. Without either, a host start enables the
    inspector only when ``HOLON_COHERENCE_WEB`` is truthy (``1``/``true``/``yes``/``on``), so it can
    be switched on once in a shell profile. The in-container entrypoint ignores that variable and
    stays headless (mitmdump only) unless ``--web`` is passed: the Dockerfile ``CMD`` and the
    background ``run`` / ``run-agent`` containers publish no inspector port. The host ``start``
    always passes ``--web`` explicitly when it wants the inspector.

    An explicit ``--web-password`` without ``--web`` / ``--no-web`` implies the inspector, since a
    password only protects mitmweb and silently dropping it would surprise the operator. With
    ``--no-web`` the flag still wins and a warning (never the password itself) is printed to stderr.
    The ``HOLON_COHERENCE_WEB_PASSWORD`` variable implies nothing: a shell profile may export it.
    """
    flag = getattr(args, "web", None)
    password_given = getattr(args, "web_password", None) is not None
    if flag is not None:
        if not flag and password_given:
            print(
                "⚠️  --web-password is ignored because --no-web disables the mitmweb inspector.",
                file=sys.stderr,
            )
        return bool(flag)
    if password_given:
        return True
    if in_container:
        return False
    return os.getenv(WEB_INSPECTOR_ENV_VAR, "").lower().strip() in ("1", "true", "yes", "on")


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


def _urlopen_no_proxy(req: urllib.request.Request, timeout: float) -> Any:
    """Open a request directly, ignoring http_proxy/HTTP_PROXY env vars (readiness probes target loopback)."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(req, timeout=timeout)


def wait_for_proxy_ready(
    port: int, timeout: float = PROXY_READY_TIMEOUT_SECONDS, container_name: str | None = None
) -> bool:
    """Poll the proxy HTTP metrics endpoint until it returns HTTP 200 or timeout occurs.

    ``timeout`` is a duration measured on the monotonic clock, so a wall-clock step (NTP
    correction, VM resume, a manual ``date``) can neither stretch nor cut short the cold-start wait.
    """
    name = container_name or get_container_name()
    deadline = time.monotonic() + timeout
    candidate_urls = (
        f"http://127.0.0.1:{port}/holon/api/metrics",
        f"http://127.0.0.1:{port}/_holon/metrics",
    )
    while time.monotonic() < deadline:
        if not is_container_running(name):
            return False

        for url in candidate_urls:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "holon-coherence-readiness"})
                resp = _urlopen_no_proxy(req, timeout=1.0)
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


def probe_host_local_reachable(port: int, timeout: float = 15.0, container_name: str | None = None) -> tuple[bool, str]:
    """Check from inside the container that the Docker host gateway answers on ``port``."""
    name = container_name or get_container_name()
    for interpreter in ("python3", "python"):
        try:
            res = subprocess.run(
                ["docker", "exec", name, interpreter, "-c", _CONTAINER_GATEWAY_PROBE, str(port)],
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


def plan_local_llm_route(
    raw_base: str,
    *,
    merge_no_proxy_fn: Callable[[dict[str, str] | None], str] | None = None,
    detect_addrs_fn: Callable[[], tuple[str, ...]] | None = None,
) -> LocalLlmRoute | None:
    """Turn a ``--local-llm-base`` value into the route a runner session applies."""
    merge_no_proxy = merge_no_proxy_fn or merge_no_proxy_values
    detect_addrs = detect_addrs_fn or detect_host_addresses
    target = parse_local_target(raw_base)
    if target is None:
        return None
    host_addresses = detect_addrs()
    targets = expand_equivalence_class(target, host_addresses)
    return LocalLlmRoute(
        target=target,
        targets=targets,
        container_env_value=encode_targets(targets),
        host_addresses=host_addresses,
        no_proxy_plan=plan_no_proxy_pruning(merge_no_proxy(None), target, host_addresses),
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


def _get_start_hooks() -> ProxyLifecycleHooks:
    """Build lifecycle hooks referencing current start module namespace."""
    return ProxyLifecycleHooks(
        check_daemon_fn=check_docker_daemon,
        is_port_in_use_fn=is_port_in_use,
        is_container_running_fn=is_container_running,
        is_container_bound_to_port_fn=is_container_bound_to_port,
        wait_ready_fn=wait_for_proxy_ready,
        stop_container_fn=stop_proxy_container,
        ensure_image_fn=ensure_docker_image,
        urlopen_no_proxy_fn=_urlopen_no_proxy,
        generate_ca_fn=generate_root_ca,
        container_host_local_spec_fn=container_host_local_spec,
    )


def ensure_proxy_running(
    port: int = DEFAULT_PROXY_PORT,
    image: str = "holon-coherence:latest",
    host_local_spec: str = "",
    container_name: str | None = None,
) -> bool:
    """Ensure the holon-coherence optimization proxy is running in the background and healthy."""
    config = ProxyLifecycleConfig(
        port=port,
        image=image,
        host_local_spec=host_local_spec,
        container_name=container_name,
        detach=True,
    )
    lifecycle = ProxyLifecycle(config, hooks=_get_start_hooks())
    return lifecycle.ensure_running()


def _resolve_start_local_llm(args: Any, initial_spec: str) -> tuple[str, LocalLlmRoute | None]:
    """Validate and plan --local-llm-base route."""
    if not getattr(args, "local_llm_base", None):
        return initial_spec, None

    route = plan_local_llm_route(args.local_llm_base)
    if route is None:
        print(
            f"Error: --local-llm-base '{args.local_llm_base}' is not a usable endpoint.\n"
            "Expected host:port or a base URL, e.g. localhost:8081, 127.0.0.1:8081, "
            "192.168.2.13:8081, http://localhost:11434/v1.",
            file=sys.stderr,
        )
        sys.exit(1)
    if route.target.port == args.port:
        print(
            f"Error: --local-llm-base port ({route.target.port}) cannot be the same as proxy port ({args.port}).",
            file=sys.stderr,
        )
        sys.exit(1)
    merged = (*decode_targets(initial_spec), *route.targets)
    return encode_targets(merged), route


def _resolve_start_ports(
    args: Any,
    route: LocalLlmRoute | None,
    web_enabled: bool,
) -> tuple[int, int | None, str | None]:
    """Handle port conflict detection and inspector fallback mapping."""
    actual_proxy_port = args.port
    if is_port_in_use(actual_proxy_port):
        actual_proxy_port = find_available_port(actual_proxy_port + 1)
        print(f"⚠️  Port {args.port} is already in use on host. Mapping proxy to host port {actual_proxy_port} instead.")

    if not web_enabled:
        return actual_proxy_port, None, None

    web_password = resolve_web_password(getattr(args, "web_password", None))
    save_web_token(web_password)
    reserved_ports = {actual_proxy_port}
    if route is not None and route.target.port is not None:
        reserved_ports.add(route.target.port)

    requested_web_port = getattr(args, "web_port", DEFAULT_WEB_PORT)
    actual_web_port = requested_web_port
    while actual_web_port in reserved_ports or is_port_in_use(actual_web_port):
        actual_web_port = find_available_port(actual_web_port + 1)

    if actual_web_port != requested_web_port:
        print(
            f"⚠️  Port {requested_web_port} is unavailable on host (in use, or taken by the proxy or the "
            f"local LLM endpoint). Mapping mitmweb inspector to host port {actual_web_port} instead."
        )
    return actual_proxy_port, actual_web_port, web_password


def _execute_detached_start(lifecycle: ProxyLifecycle, proxy_port: int, web_port: int | None) -> None:
    """Run container in background mode and report errors."""
    docker_cmd = lifecycle._build_docker_run_args(proxy_port, actual_web_port=web_port)
    try:
        subprocess.run(docker_cmd, check=True)
        print("✅ holon-coherence container running in background.")
        print("Use 'holon-coherence logs -f' to stream logs or 'holon-coherence stop' to shut down.")
    except subprocess.CalledProcessError as e:
        print(
            f"❌ Error: Failed to start Docker container on ports "
            f"(proxy={proxy_port}, web={web_port if web_port is not None else 'N/A'}): {e}",
            file=sys.stderr,
        )
        sys.exit(1)


def _execute_foreground_start(
    lifecycle: ProxyLifecycle,
    proxy_port: int,
    web_port: int | None,
    target_container: str,
) -> None:
    """Run container in foreground mode, cleaning up on keyboard interrupt."""
    docker_cmd = lifecycle._build_docker_run_args(proxy_port, actual_web_port=web_port)
    try:
        subprocess.run(docker_cmd)
    except subprocess.CalledProcessError as e:
        print(
            f"❌ Error: Failed to start Docker container on ports "
            f"(proxy={proxy_port}, web={web_port if web_port is not None else 'N/A'}): {e}",
            file=sys.stderr,
        )
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nShutting down holon-coherence container...")
        subprocess.run(
            ["docker", "stop", target_container],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def _dispatch_proxy_lifecycle(
    args: Any,
    proxy_port: int,
    web_port: int | None,
    web_password: str | None,
    host_local_spec: str,
) -> None:
    """Construct ProxyLifecycleConfig and execute proxy lifecycle start."""
    target_container = getattr(args, "name", None) or get_container_name()
    config = ProxyLifecycleConfig(
        port=proxy_port,
        web_port=web_port,
        container_name=target_container,
        image=args.image,
        host_local_spec=host_local_spec,
        passive=is_start_passive(getattr(args, "passive", False)),
        web_password=web_password,
        detach=args.detach,
        build=getattr(args, "build", False),
    )
    hooks = _get_start_hooks()
    lifecycle = ProxyLifecycle(config, hooks=hooks)

    lifecycle.ensure_ca()
    ensure_image = getattr(hooks, "ensure_image_fn", ensure_docker_image)
    ensure_image(args.image, rebuild=args.build)
    subprocess.run(["docker", "rm", "-f", target_container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    print(f"🐳 Starting holon-coherence proxy via Docker container on port {proxy_port}...")
    print_endpoints(ExposedEndpoints(proxy_port=proxy_port, web_port=web_port, web_token=web_password))

    if args.detach:
        _execute_detached_start(lifecycle, proxy_port, web_port)
    else:
        _execute_foreground_start(lifecycle, proxy_port, web_port, target_container)


def handle_start(args: Any) -> None:
    """Execute proxy start command in container or on host."""
    initial_spec = os.environ.get(HOST_LOCAL_ENV_VAR, "").strip()
    host_local_spec, route = _resolve_start_local_llm(args, initial_spec)

    if is_in_container():
        web_port = args.web_port if is_web_inspector_enabled(args, in_container=True) else None
        config = ProxyLifecycleConfig(
            port=args.port,
            web_port=web_port,
            host_local_spec=host_local_spec,
            web_password=getattr(args, "web_password", None),
        )
        ProxyLifecycle(config, hooks=_get_start_hooks()).start()
        return

    ok, err = check_docker_daemon()
    if not ok:
        print(err, file=sys.stderr)
        sys.exit(1)

    web_enabled = is_web_inspector_enabled(args, in_container=False)
    proxy_port, web_port, web_password = _resolve_start_ports(args, route, web_enabled)
    _dispatch_proxy_lifecycle(args, proxy_port, web_port, web_password, host_local_spec)


def handle(args: Any) -> int:
    """Handle start command."""
    handle_start(args)
    return 0


def register(subparsers: Any) -> argparse.ArgumentParser:
    """Register start subparser."""
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
    start_parser.add_argument(
        "--web",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Launch the mitmweb raw request/response inspector (default: off, or on when HOLON_COHERENCE_WEB=1; "
        "mitmweb keeps every flow in memory, so leave it off for long-running proxies)",
    )
    start_parser.add_argument(
        "--web-port",
        type=int,
        default=DEFAULT_WEB_PORT,
        help=f"mitmweb inspector host port (default: {DEFAULT_WEB_PORT}; falls back to the next free port if occupied)",
    )
    start_parser.add_argument(
        "--web-password",
        default=None,
        help="Token protecting the mitmweb inspector (defaults to HOLON_COHERENCE_WEB_PASSWORD or an "
        "auto-generated token); implies --web unless --no-web is given",
    )
    start_parser.add_argument("-d", "--detach", action="store_true", help="Run Docker container in background")
    start_parser.add_argument(
        "--name",
        default=None,
        help="Container name (defaults to HOLON_CONTAINER_NAME or holon-coherence-proxy)",
    )
    start_parser.add_argument(
        "--image", default="holon-coherence:latest", help="Docker image tag (default: holon-coherence:latest)"
    )
    start_parser.add_argument(
        "--passive",
        action="store_true",
        help="Run proxy in passive monitoring mode (baseline/logging only, no active optimization)",
    )
    start_parser.add_argument("--build", action="store_true", help="Rebuild Docker image before starting")
    start_parser.set_defaults(handler=handle)
    return start_parser
