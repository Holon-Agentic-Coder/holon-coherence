from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import replace
from typing import Any, NamedTuple

from holon_coherence.commands.endpoints import ExposedEndpoints, print_endpoints, token_recovery_command
from holon_coherence.commands.runner import merge_no_proxy_values
from holon_coherence.commands.web_token import resolve_web_password, save_web_token
from holon_coherence.container.lifecycle import (
    DEFAULT_IMAGE,
    DEFAULT_PROXY_PORT,
    DEFAULT_WEB_PORT,
    PROXY_POLL_INTERVAL_SECONDS,
    PROXY_READY_TIMEOUT_SECONDS,
    ProxyLifecycle,
    ProxyLifecycleConfig,
    container_host_local_spec,
    docker_host_alias_args,
    find_available_port,
    get_container_name,
    host_local_container_args,
    host_local_covered,
    is_in_container,
    is_port_in_use,
    is_start_passive,
    require_docker_daemon,
)
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
from holon_coherence.settings import CoherenceSettings

TRUTHY_WEB_ENV_VALUES = ("1", "true", "yes", "on")

__all__ = [
    "DEFAULT_PROXY_PORT",
    "DEFAULT_WEB_PORT",
    "PROXY_POLL_INTERVAL_SECONDS",
    "PROXY_READY_TIMEOUT_SECONDS",
    "TRUTHY_WEB_ENV_VALUES",
    "WEB_INSPECTOR_ENV_VAR",
    "_CONTAINER_GATEWAY_PROBE",
    "LocalLlmRoute",
    "container_host_local_spec",
    "docker_host_alias_args",
    "ensure_proxy_running",
    "find_available_port",
    "handle",
    "handle_start",
    "host_local_container_args",
    "host_local_covered",
    "is_in_container",
    "is_port_in_use",
    "is_start_passive",
    "is_web_inspector_enabled",
    "plan_local_llm_route",
    "probe_host_local_reachable",
    "register",
    "report_local_llm_route",
    "wait_for_proxy_ready",
]

_CONTAINER_GATEWAY_PROBE = (
    "import socket,sys\n"
    "try:\n"
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
    target: LocalTarget
    targets: tuple[LocalTarget, ...]
    container_env_value: str
    host_addresses: tuple[str, ...]
    no_proxy_plan: PruningPlan

    @property
    def prunes_no_proxy(self) -> tuple[str, ...]:
        return self.no_proxy_plan.remove


WEB_INSPECTOR_ENV_VAR = "HOLON_COHERENCE_WEB"


def is_web_inspector_enabled(args: Any, in_container: bool) -> bool:
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
    return CoherenceSettings.from_env().web_inspector


def probe_host_local_reachable(port: int, timeout: float = 15.0, container_name: str | None = None) -> tuple[bool, str]:
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


def wait_for_proxy_ready(
    port: int, timeout: float = PROXY_READY_TIMEOUT_SECONDS, container_name: str | None = None
) -> bool:
    config = ProxyLifecycleConfig(port=port, container_name=container_name)
    return ProxyLifecycle(config).wait_until_ready(timeout_seconds=timeout)


def ensure_proxy_running(
    port: int = DEFAULT_PROXY_PORT,
    image: str = DEFAULT_IMAGE,
    host_local_spec: str = "",
    container_name: str | None = None,
) -> bool:
    config = ProxyLifecycleConfig(
        port=port,
        image=image,
        host_local_spec=host_local_spec,
        container_name=container_name,
        world_accessible_mounts=False,
    )
    return ProxyLifecycle(config).start()


def _resolve_start_local_llm(args: Any, initial_spec: str) -> tuple[str, LocalLlmRoute | None]:
    raw_base = getattr(args, "local_llm_base", None)
    if not raw_base:
        return initial_spec, None
    route = plan_local_llm_route(raw_base)
    if route is None:
        print(
            f"Error: --local-llm-base '{raw_base}' is not a usable endpoint.\n"
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
    return encode_targets((*decode_targets(initial_spec), *route.targets)), route


def _in_container_inspector_banner(web_port: int) -> str:
    return (
        f"🌐 mitmweb inspector listening on container port {web_port} (token hidden; run "
        "'holon-coherence web-token --name <container>' on the host for the full URL, or recover the "
        f"token with: {token_recovery_command('<container>')})"
    )


def _serve_in_container(args: Any, host_local_spec: str) -> None:
    web_port: int | None = None
    web_password: str | None = None
    if is_web_inspector_enabled(args, in_container=True):
        web_port = getattr(args, "web_port", DEFAULT_WEB_PORT)
        web_password = resolve_web_password(getattr(args, "web_password", None))
        save_web_token(web_password)
    config = ProxyLifecycleConfig(
        port=args.port, web_port=web_port, web_password=web_password, host_local_spec=host_local_spec
    )
    banner = _in_container_inspector_banner(web_port) if web_port is not None else None
    ProxyLifecycle(config).serve_in_container(banner=banner)


def _resolve_start_proxy_port(requested_port: int) -> int:
    if not is_port_in_use(requested_port):
        return requested_port
    actual_port = find_available_port(requested_port + 1)
    print(f"⚠️  Port {requested_port} is already in use on host. Mapping proxy to host port {actual_port} instead.")
    return actual_port


def _resolve_start_web_port(requested_port: int, reserved_ports: set[int]) -> int:
    actual_port = requested_port
    if actual_port in reserved_ports or is_port_in_use(actual_port):
        actual_port = find_available_port(actual_port + 1)
        while actual_port in reserved_ports or is_port_in_use(actual_port):
            actual_port = find_available_port(actual_port + 1)
        print(
            f"⚠️  Port {requested_port} is unavailable on host (in use, or taken by the proxy or the "
            f"local LLM endpoint). Mapping mitmweb inspector to host port {actual_port} instead."
        )
    return actual_port


def _resolve_start_web_inspector(
    args: Any, proxy_port: int, route: LocalLlmRoute | None
) -> tuple[int | None, str | None]:
    if not is_web_inspector_enabled(args, in_container=False):
        return None, None
    web_password = resolve_web_password(getattr(args, "web_password", None))
    save_web_token(web_password)
    reserved_ports = {proxy_port}
    if route is not None and route.target.port is not None:
        reserved_ports.add(route.target.port)
    return _resolve_start_web_port(getattr(args, "web_port", DEFAULT_WEB_PORT), reserved_ports), web_password


def _dispatch_proxy_lifecycle(lifecycle: ProxyLifecycle) -> None:
    config = lifecycle.config
    print(f"🐳 Starting holon-coherence proxy via Docker container on port {config.port}...")
    print_endpoints(ExposedEndpoints(proxy_port=config.port, web_port=config.web_port, web_token=config.web_password))
    lifecycle.launch()


def _start_on_host(args: Any, route: LocalLlmRoute | None, host_local_spec: str) -> None:
    require_docker_daemon()
    config = ProxyLifecycleConfig(
        port=_resolve_start_proxy_port(args.port),
        container_name=getattr(args, "name", None) or get_container_name(),
        image=args.image,
        host_local_spec=host_local_spec,
        passive=getattr(args, "passive", False),
        detach=args.detach,
        rebuild=args.build,
    )
    ProxyLifecycle(config).prepare()
    web_port, web_password = _resolve_start_web_inspector(args, config.port, route)
    _dispatch_proxy_lifecycle(ProxyLifecycle(replace(config, web_port=web_port, web_password=web_password)))


def handle_start(args: Any) -> None:
    host_local_spec, route = _resolve_start_local_llm(args, os.environ.get(HOST_LOCAL_ENV_VAR, "").strip())
    if is_in_container():
        _serve_in_container(args, host_local_spec)
        return
    _start_on_host(args, route, host_local_spec)


def handle(args: Any) -> int:
    handle_start(args)
    return 0


def register(subparsers: Any) -> argparse.ArgumentParser:
    start_parser = subparsers.add_parser("start", help="Start the optimization proxy sidecar (via Docker by default)")
    settings = CoherenceSettings.from_env()
    start_parser.add_argument(
        "--port",
        type=int,
        default=settings.proxy_port,
        help=f"Proxy listen port (default: {DEFAULT_PROXY_PORT} or HOLON_PROXY_PORT)",
    )
    start_parser.add_argument(
        "--local-llm-base",
        default=settings.local_llm_base,
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
    start_parser.add_argument("--image", default=DEFAULT_IMAGE, help=f"Docker image tag (default: {DEFAULT_IMAGE})")
    start_parser.add_argument(
        "--passive",
        action="store_true",
        help="Run proxy in passive monitoring mode (baseline/logging only, no active optimization)",
    )
    start_parser.add_argument("--build", action="store_true", help="Rebuild Docker image before starting")
    start_parser.set_defaults(handler=handle)
    return start_parser
