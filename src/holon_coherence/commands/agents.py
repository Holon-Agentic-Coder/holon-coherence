"""Agent command dispatchers and runner wrappers."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, NamedTuple

from holon_coherence.commands.ca import CA_ENV_VARS
from holon_coherence.commands.docker_ops import stop_proxy_container
from holon_coherence.commands.runner import build_proxy_env, execute_interactive_process
from holon_coherence.commands.start import (
    DEFAULT_PROXY_PORT,
    LocalLlmRoute,
    ensure_proxy_running,
    plan_local_llm_route,
    probe_host_local_reachable,
    report_local_llm_route,
)
from holon_coherence.host_local import GATEWAY_HOSTNAME

SUPPORTED_AGENTS = ("agy", "claude", "codex", "opencode", "pi")

AGENT_BINARY_MAP: dict[str, list[str]] = {
    "agy": ["agy", "antigravity"],
    "claude": ["claude"],
    "codex": ["codex", "chatgpt"],
    "opencode": ["opencode"],
    "pi": ["pi"],
}


class RunnerFlags(NamedTuple):
    """Parsed runner flags extracted from raw argv before argparse takes over."""

    ephemeral: bool
    port: int | None
    agent_args: list[str]
    help_requested: bool = False
    local_llm_base: str | None = None
    model: str | None = None


@dataclass
class _RunnerFlagAccumulator:
    """Accumulates parsed runner flags from CLI arguments."""

    ephemeral: bool = False
    port: int | None = None
    help_requested: bool = False
    local_llm_base: str | None = None
    model: str | None = None
    agent_args: list[str] = field(default_factory=list)


def _parse_flag_value(argv: list[str], idx: int, flag_name: str, hint: str = "") -> tuple[str, int]:
    """Parse option value from `--flag value` or `--flag=value` syntax."""
    arg = argv[idx]
    if "=" in arg:
        val = arg.split("=", 1)[1]
        if not val:
            print(f"Error: Option {flag_name} requires an argument{hint}", file=sys.stderr)
            sys.exit(1)
        return val, idx + 1
    if idx + 1 >= len(argv) or argv[idx + 1] == "--":
        print(f"Error: Option {flag_name} requires an argument{hint}", file=sys.stderr)
        sys.exit(1)
    return argv[idx + 1], idx + 2


def _parse_port_flag(argv: list[str], idx: int) -> tuple[int, int]:
    """Parse and validate `--port` integer flag."""
    arg = argv[idx]
    if "=" in arg:
        val = arg.split("=", 1)[1]
        if not val:
            print("Error: Option --port requires an argument.", file=sys.stderr)
            sys.exit(1)
        new_idx = idx + 1
    else:
        if idx + 1 >= len(argv) or argv[idx + 1] == "--":
            print("Error: Option --port requires an argument.", file=sys.stderr)
            sys.exit(1)
        val = argv[idx + 1]
        new_idx = idx + 2
    try:
        port = int(val)
    except ValueError:
        print(f"Error: Argument to --port must be an integer, got '{val}'.", file=sys.stderr)
        sys.exit(1)
    if not (1 <= port <= 65535):
        print(f"Error: Port must be between 1 and 65535, got {port}.", file=sys.stderr)
        sys.exit(1)
    return port, new_idx


def extract_runner_flags(argv: list[str]) -> RunnerFlags:
    """Extract runner flags and ``--help`` from arguments, preserving agent argument order."""
    acc = _RunnerFlagAccumulator()
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--ephemeral":
            acc.ephemeral = True
            i += 1
        elif arg in ("--help", "-h"):
            acc.help_requested = True
            i += 1
        elif arg in ("--local-llm-base", "--local-llm-endpoint") or arg.startswith(
            ("--local-llm-base=", "--local-llm-endpoint=")
        ):
            flag_name = arg.split("=", 1)[0]
            acc.local_llm_base, i = _parse_flag_value(argv, i, flag_name, ", e.g. localhost:8081.")
        elif arg == "--model" or arg.startswith("--model="):
            model, new_i = _parse_flag_value(argv, i, "--model", ".")
            acc.model = model
            acc.agent_args.extend(argv[i:new_i])
            i = new_i
        elif arg == "--port" or arg.startswith("--port="):
            acc.port, i = _parse_port_flag(argv, i)
        elif arg == "--":
            acc.agent_args.extend(argv[i + 1 :])
            break
        else:
            acc.agent_args.append(arg)
            i += 1
    return RunnerFlags(
        acc.ephemeral,
        acc.port,
        acc.agent_args,
        help_requested=acc.help_requested,
        local_llm_base=acc.local_llm_base,
        model=acc.model,
    )


def resolve_agent_binary(agent_name: str) -> str | None:
    """Find the executable binary for the specified agent on the host PATH."""
    candidates = AGENT_BINARY_MAP.get(agent_name, [agent_name])
    for candidate in candidates:
        path = shutil.which(candidate)
        if path:
            return path
    return None


def _apply_proxy_and_ca_env(
    env: dict[str, str],
    port: int,
    drop_no_proxy: tuple[str, ...],
    env_builder: Callable[..., dict[str, str]],
) -> None:
    """Configure HTTP proxy settings and drop system CA vars if proxy CA is present."""
    proxy_url = f"http://127.0.0.1:{port}"
    proxy_env = env_builder(proxy_url, drop_no_proxy=drop_no_proxy)
    env.update(proxy_env)
    if not all(var in proxy_env for var in CA_ENV_VARS):
        for var in CA_ENV_VARS:
            env.pop(var, None)


def _apply_local_llm_env(
    env: dict[str, str],
    agent_name: str,
    port: int,
    model: str | None,
    holon_key: str | None,
) -> None:
    """Inject provider base URLs and model overrides for local LLM routing."""
    env.setdefault("USER", "holon")
    if agent_name == "claude":
        env["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{port}"
        env["ANTHROPIC_AUTH_TOKEN"] = holon_key or "sk-ant-local"
        env["ANTHROPIC_API_KEY"] = holon_key or "sk-ant-local"
        if model:
            env["ANTHROPIC_MODEL"] = model
        env["ANTHROPIC_DISABLE_TELEMETRY"] = "1"
        env["CLAUDE_SUPPRESS_FALLBACK"] = "1"
    elif agent_name == "agy":
        env["AGY_GATEWAY_URL"] = f"http://127.0.0.1.nip.io:{port}"
        if model:
            env["AGY_MODEL"] = model
        env.setdefault("GEMINI_API_KEY", holon_key or "dummy-local-key")
        env.setdefault("AGY_USER_TOKEN", holon_key or "dummy-local-key")
    elif agent_name in ("codex", "opencode", "pi"):
        env["OPENAI_BASE_URL"] = f"http://127.0.0.1:{port}/v1"
        if model:
            env["OPENAI_MODEL"] = model


def _apply_auth_key_env(env: dict[str, str], agent_name: str, holon_key: str) -> None:
    """Map universal HOLON_AGENT_KEY credential to provider-specific auth variables."""
    if agent_name == "agy":
        env["GEMINI_API_KEY"] = holon_key
        env["AGY_USER_TOKEN"] = holon_key
    elif agent_name == "claude":
        if "ANTHROPIC_API_KEY" not in env:
            env["ANTHROPIC_API_KEY"] = holon_key
    elif agent_name == "codex":
        env["OPENAI_API_KEY"] = holon_key
    elif agent_name == "opencode":
        env["OPENCODE_API_KEY"] = holon_key
    elif agent_name == "pi":
        env["PI_API_KEY"] = holon_key


def build_agent_env(
    agent_name: str,
    port: int,
    drop_no_proxy: tuple[str, ...] = (),
    model: str | None = None,
    local_llm_base: str | None = None,
    **kwargs: Any,
) -> dict[str, str]:
    """Construct environment variables for the child agent subprocess."""
    env = os.environ.copy()
    env_builder = kwargs.get("env_builder_fn") or build_proxy_env
    _apply_proxy_and_ca_env(env, port, drop_no_proxy, env_builder)

    holon_key = env.get("HOLON_AGENT_KEY")
    effective_local_base = local_llm_base or os.getenv("HOLON_LOCAL_LLM_BASE")
    if effective_local_base:
        _apply_local_llm_env(env, agent_name, port, model, holon_key)

    if holon_key:
        _apply_auth_key_env(env, agent_name, holon_key)

    return env


def _resolve_agent_port(port: int | None) -> tuple[int, int | None]:
    """Validate and resolve proxy port from argument or environment."""
    if port is not None:
        if not (1 <= port <= 65535):
            print(f"Error: Port must be between 1 and 65535, got {port}.", file=sys.stderr)
            return 0, 1
        return port, None

    env_port = os.getenv("HOLON_PROXY_PORT")
    if not env_port:
        return DEFAULT_PROXY_PORT, None

    try:
        parsed_port = int(env_port)
        if not (1 <= parsed_port <= 65535):
            raise ValueError(f"Port {parsed_port} out of range")
        return parsed_port, None
    except ValueError:
        print(
            f"⚠️  Invalid HOLON_PROXY_PORT '{env_port}', falling back to {DEFAULT_PROXY_PORT}.",
            file=sys.stderr,
        )
        return DEFAULT_PROXY_PORT, None


def _setup_agent_local_route(
    port: int,
    local_llm_base: str | None,
    plan_route: Callable[[str], LocalLlmRoute | None],
    probe_host: Callable[[int], tuple[bool, str]],
    report_route: Callable[..., tuple[str, ...]],
) -> tuple[LocalLlmRoute | None, tuple[str, ...], int | None]:
    """Plan local LLM route, probe reachability, and report pruning."""
    if local_llm_base is None:
        env_base = os.getenv("HOLON_LOCAL_LLM_BASE")
        if env_base:
            local_llm_base = env_base.strip() or None

    if local_llm_base is None:
        return None, (), None

    route = plan_route(local_llm_base)
    if route is None:
        print(
            f"Error: --local-llm-base '{local_llm_base}' is not a usable endpoint.\n"
            "Expected host:port or a base URL, e.g. localhost:8081, 127.0.0.1:8081, "
            "192.168.2.13:8081, http://localhost:11434/v1.",
            file=sys.stderr,
        )
        return None, (), 1
    if route.target.port == port:
        print(
            f"Error: --local-llm-base port ({route.target.port}) cannot be the same as proxy port ({port}).",
            file=sys.stderr,
        )
        return None, (), 1

    if route.target.port is None:
        print(
            "⚠️  --local-llm-base without a port skips the container reachability preflight; "
            "prefer localhost:8081 so the route can be verified before NO_PROXY is changed.",
            file=sys.stderr,
        )
        reachable, detail = True, "preflight skipped (no port given)"
    else:
        reachable, detail = probe_host(route.target.port)

    drop_no_proxy = report_route(route, reachable, detail)
    return route, drop_no_proxy, None


def _execute_agent_with_cleanup(
    cmd: list[str],
    child_env: dict[str, str],
    should_cleanup: bool,
    exec_proc: Callable[[list[str], dict[str, str]], int],
    stop_container: Callable[..., Any],
) -> int:
    """Execute child agent process and manage ephemeral container teardown."""
    try:
        return exec_proc(cmd, child_env)
    finally:
        if should_cleanup:
            stop_container()


def run_agent(
    agent_name: str,
    agent_args: list[str],
    ephemeral: bool = False,
    port: int | None = None,
    **kwargs: Any,
) -> int:
    """Launch the optimization proxy and execute the requested coding agent with full telemetry."""
    resolve_bin = kwargs.get("resolve_bin_fn") or resolve_agent_binary
    plan_route = kwargs.get("plan_route_fn") or plan_local_llm_route
    ensure_proxy = kwargs.get("ensure_proxy_fn") or ensure_proxy_running
    probe_host = kwargs.get("probe_host_fn") or probe_host_local_reachable
    report_route = kwargs.get("report_route_fn") or report_local_llm_route
    build_env = kwargs.get("build_env_fn") or build_agent_env
    exec_proc = kwargs.get("exec_proc_fn") or execute_interactive_process
    stop_container = kwargs.get("stop_container_fn") or stop_proxy_container

    resolved_port, err_code = _resolve_agent_port(port)
    if err_code is not None:
        return err_code

    binary_path = resolve_bin(agent_name)
    if not binary_path:
        primary_bin = AGENT_BINARY_MAP.get(agent_name, [agent_name])[0]
        print(
            f"Error: Agent CLI binary '{primary_bin}' not found on PATH.\n"
            f"Please install '{primary_bin}' and ensure it is accessible in your PATH.",
            file=sys.stderr,
        )
        return 1

    local_llm_base = kwargs.get("local_llm_base")
    model = kwargs.get("model")
    route, drop_no_proxy, err = _setup_agent_local_route(
        resolved_port, local_llm_base, plan_route, probe_host, report_route
    )
    if err is not None:
        return err

    container_started = ensure_proxy(
        port=resolved_port,
        host_local_spec=route.container_env_value if route else "",
    )

    try:
        child_env = build_env(
            agent_name,
            resolved_port,
            drop_no_proxy=drop_no_proxy,
            model=model,
            local_llm_base=local_llm_base,
        )
    except TypeError:
        child_env = build_env(agent_name, resolved_port, drop_no_proxy=drop_no_proxy)

    cmd = [binary_path, *agent_args]
    should_cleanup = bool(ephemeral and container_started)
    return _execute_agent_with_cleanup(
        cmd,
        child_env,
        should_cleanup,
        exec_proc,
        stop_container,
    )


def _print_agent_help(agent_name: str) -> None:
    """Print help information for running an agent."""
    print(
        f"usage: holon-coherence {agent_name} [--ephemeral] [--port PORT] "
        "[--model MODEL] [--local-llm-base BASE] [--local-llm-endpoint ENDPOINT] [--] [agent_args ...]\n"
    )
    print(f"Run {agent_name} coding agent with automated background proxy and wire optimization.\n")
    print("positional arguments:")
    print("  agent_args            Arguments passed directly to the agent CLI\n")
    print("options:")
    print("  --ephemeral           Stop and remove the proxy container when the agent exits")
    print(f"  --port PORT           Proxy listen port (default: {DEFAULT_PROXY_PORT} or HOLON_PROXY_PORT)")
    print("  --model MODEL         Model identifier to configure for the agent")
    print(
        "  --local-llm-base BASE Host-local model server (e.g. localhost:8081) to intercept\n"
        f"                       and reroute via {GATEWAY_HOSTNAME} instead of bypassing the proxy"
    )
    print("  --local-llm-endpoint ENDPOINT Alias for --local-llm-base\n")
    print("note:")
    print("  Use '--' to pass flags directly to the underlying agent (e.g. '-- --help').")


def _print_run_agent_help() -> None:
    """Print help information for run-agent command."""
    agents_str = ", ".join(sorted(set(SUPPORTED_AGENTS)))
    print(
        "usage: holon-coherence run-agent <agent> [--ephemeral] [--port PORT] "
        "[--model MODEL] [--local-llm-base BASE] [--local-llm-endpoint ENDPOINT] [--] [agent_args ...]\n"
    )
    print("Run a coding agent with automated background proxy and wire optimization.\n")
    print("positional arguments:")
    print(f"  agent                 Target agent ({agents_str})")
    print("  agent_args            Arguments passed directly to the agent CLI\n")
    print("options:")
    print("  --ephemeral           Stop and remove the proxy container when the agent exits")
    print(f"  --port PORT           Proxy listen port (default: {DEFAULT_PROXY_PORT} or HOLON_PROXY_PORT)")
    print("  --model MODEL         Model identifier to configure for the agent")
    print(
        "  --local-llm-base BASE Host-local model server (e.g. localhost:8081) to intercept\n"
        f"                       and reroute via {GATEWAY_HOSTNAME} instead of bypassing the proxy"
    )
    print("  --local-llm-endpoint ENDPOINT Alias for --local-llm-base\n")
    print("note:")
    print("  Use '--' to pass flags directly to the underlying agent (e.g. '-- --help').")


def handle(args: Any) -> int:
    """Dispatch agent execution from parsed arguments."""
    cmd = getattr(args, "command", None)
    agent_name = getattr(args, "agent", None) if cmd == "run-agent" else cmd
    if not agent_name:
        return 1
    local_llm_base = getattr(args, "local_llm_base", None) or getattr(args, "local_llm_endpoint", None)
    return run_agent(
        agent_name,
        getattr(args, "agent_args", []),
        ephemeral=getattr(args, "ephemeral", False),
        port=getattr(args, "port", None),
        local_llm_base=local_llm_base,
        model=getattr(args, "model", None),
    )


def register(subparsers: Any) -> list[argparse.ArgumentParser]:
    """Register run-agent and agent alias subparsers."""
    run_agent_parser = subparsers.add_parser("run-agent", help="Run a coding agent with automated background proxy")
    run_agent_parser.add_argument("agent", choices=sorted(set(SUPPORTED_AGENTS)), help="Target agent")
    run_agent_parser.add_argument(
        "--ephemeral", action="store_true", help="Stop proxy container after agent process exits"
    )
    run_agent_parser.add_argument(
        "--port", type=int, default=None, help=f"Proxy port (default: {DEFAULT_PROXY_PORT} or HOLON_PROXY_PORT)"
    )
    run_agent_parser.add_argument(
        "--model",
        default=None,
        metavar="MODEL",
        help="Model identifier to configure for the agent",
    )
    run_agent_parser.add_argument(
        "--local-llm-base",
        default=None,
        metavar="BASE",
        help="Host-local model server endpoint to intercept and reroute via the Docker host gateway",
    )
    run_agent_parser.add_argument(
        "--local-llm-endpoint",
        default=None,
        metavar="ENDPOINT",
        help="Alias for --local-llm-base",
    )
    run_agent_parser.add_argument("agent_args", nargs=argparse.REMAINDER, help="Arguments passed to the agent")
    run_agent_parser.set_defaults(handler=handle)

    parsers = [run_agent_parser]
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
            "--model",
            default=None,
            metavar="MODEL",
            help="Model identifier to configure for the agent",
        )
        alias_parser.add_argument(
            "--local-llm-base",
            default=None,
            metavar="BASE",
            help="Host-local model server endpoint to intercept and reroute via the Docker host gateway",
        )
        alias_parser.add_argument(
            "--local-llm-endpoint",
            default=None,
            metavar="ENDPOINT",
            help="Alias for --local-llm-base",
        )
        alias_parser.add_argument("agent_args", nargs=argparse.REMAINDER, help="Arguments passed to the agent")
        alias_parser.set_defaults(handler=handle)
        parsers.append(alias_parser)

    return parsers
