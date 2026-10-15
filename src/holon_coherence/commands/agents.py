"""Agent command dispatchers and runner wrappers."""

from __future__ import annotations

import os
import shutil
import sys
from typing import NamedTuple

from holon_coherence.commands._dispatch import get_cli
from holon_coherence.commands.ca import CA_ENV_VARS
from holon_coherence.commands.docker_ops import stop_proxy_container
from holon_coherence.commands.runner import build_proxy_env, execute_interactive_process
from holon_coherence.commands.start import (
    DEFAULT_PROXY_PORT,
    ensure_proxy_running,
    plan_local_llm_route,
    probe_host_local_reachable,
    report_local_llm_route,
)
from holon_coherence.host_local import GATEWAY_HOSTNAME

SUPPORTED_AGENTS = ("agy", "antigravity", "claude", "codex", "opencode", "pi")

AGENT_BINARY_MAP: dict[str, list[str]] = {
    "agy": ["agy", "antigravity"],
    "antigravity": ["agy", "antigravity"],
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


def extract_runner_flags(argv: list[str]) -> RunnerFlags:
    """Extract runner flags and ``--help`` from arguments, preserving agent argument order."""
    ephemeral = False
    port = None
    help_requested = False
    local_llm_base = None
    model = None
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
        elif arg in ("--local-llm-base", "--local-llm-endpoint"):
            if i + 1 >= len(argv) or argv[i + 1] == "--":
                print(f"Error: Option {arg} requires an argument, e.g. localhost:8081.", file=sys.stderr)
                sys.exit(1)
            local_llm_base = argv[i + 1]
            i += 2
        elif arg.startswith(("--local-llm-base=", "--local-llm-endpoint=")):
            flag_name = arg.split("=", 1)[0]
            val = arg.split("=", 1)[1]
            if not val:
                print(f"Error: Option {flag_name} requires an argument, e.g. localhost:8081.", file=sys.stderr)
                sys.exit(1)
            local_llm_base = val
            i += 1
        elif arg == "--model":
            if i + 1 >= len(argv) or argv[i + 1] == "--":
                print("Error: Option --model requires an argument.", file=sys.stderr)
                sys.exit(1)
            model = argv[i + 1]
            agent_args.extend([arg, argv[i + 1]])
            i += 2
        elif arg.startswith("--model="):
            val = arg.split("=", 1)[1]
            if not val:
                print("Error: Option --model requires an argument.", file=sys.stderr)
                sys.exit(1)
            model = val
            agent_args.append(arg)
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
    return RunnerFlags(
        ephemeral,
        port,
        agent_args,
        help_requested=help_requested,
        local_llm_base=local_llm_base,
        model=model,
    )


def resolve_agent_binary(agent_name: str) -> str | None:
    """Find the executable binary for the specified agent on the host PATH."""
    candidates = AGENT_BINARY_MAP.get(agent_name, [agent_name])
    for candidate in candidates:
        path = shutil.which(candidate)
        if path:
            return path
    return None


def build_agent_env(
    agent_name: str,
    port: int,
    drop_no_proxy: tuple[str, ...] = (),
    model: str | None = None,
    local_llm_base: str | None = None,
) -> dict[str, str]:
    """Construct environment variables for the child agent subprocess."""
    cli = get_cli()
    env = os.environ.copy()
    proxy_url = f"http://127.0.0.1:{port}"
    env_builder = getattr(cli, "build_proxy_env", build_proxy_env)
    proxy_env = env_builder(proxy_url, drop_no_proxy=drop_no_proxy)
    env.update(proxy_env)
    if not all(var in proxy_env for var in CA_ENV_VARS):
        for var in CA_ENV_VARS:
            env.pop(var, None)

    holon_key = env.get("HOLON_AGENT_KEY")
    normalized_agent = "agy" if agent_name == "antigravity" else agent_name

    effective_local_base = local_llm_base or os.getenv("HOLON_LOCAL_LLM_BASE")
    if effective_local_base:
        env.setdefault("USER", "holon")
        if normalized_agent == "claude":
            env["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{port}"
            env["ANTHROPIC_AUTH_TOKEN"] = holon_key or "sk-ant-local"
            env["ANTHROPIC_API_KEY"] = holon_key or "sk-ant-local"
            if model:
                env["ANTHROPIC_MODEL"] = model
            env["ANTHROPIC_DISABLE_TELEMETRY"] = "1"
            env["CLAUDE_SUPPRESS_FALLBACK"] = "1"
        elif normalized_agent == "agy":
            env["AGY_GATEWAY_URL"] = f"http://127.0.0.1.nip.io:{port}"
            if model:
                env["AGY_MODEL"] = model
            env.setdefault("GEMINI_API_KEY", holon_key or "dummy-local-key")
            env.setdefault("AGY_USER_TOKEN", holon_key or "dummy-local-key")
        elif normalized_agent in ("codex", "opencode", "pi"):
            env["OPENAI_BASE_URL"] = f"http://127.0.0.1:{port}/v1"
            if model:
                env["OPENAI_MODEL"] = model

    if holon_key:
        if normalized_agent == "agy":
            env["GEMINI_API_KEY"] = holon_key
            env["AGY_USER_TOKEN"] = holon_key
        elif normalized_agent == "claude":
            if "ANTHROPIC_API_KEY" not in env:
                env["ANTHROPIC_API_KEY"] = holon_key
        elif normalized_agent == "codex":
            env["OPENAI_API_KEY"] = holon_key
        elif normalized_agent == "opencode":
            env["OPENCODE_API_KEY"] = holon_key
        elif normalized_agent == "pi":
            env["PI_API_KEY"] = holon_key

    return env


def run_agent(
    agent_name: str,
    agent_args: list[str],
    ephemeral: bool = False,
    port: int | None = None,
    local_llm_base: str | None = None,
    model: str | None = None,
) -> int:
    """Launch the optimization proxy and execute the requested coding agent with full telemetry."""
    cli = get_cli()
    resolve_bin = getattr(cli, "resolve_agent_binary", resolve_agent_binary)
    plan_route = getattr(cli, "plan_local_llm_route", plan_local_llm_route)
    ensure_proxy = getattr(cli, "ensure_proxy_running", ensure_proxy_running)
    probe_host = getattr(cli, "probe_host_local_reachable", probe_host_local_reachable)
    report_route = getattr(cli, "report_local_llm_route", report_local_llm_route)
    build_env = getattr(cli, "build_agent_env", build_agent_env)
    exec_proc = getattr(cli, "execute_interactive_process", execute_interactive_process)
    stop_container = getattr(cli, "stop_proxy_container", stop_proxy_container)

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

    binary_path = resolve_bin(agent_name)
    if not binary_path:
        primary_bin = AGENT_BINARY_MAP.get(agent_name, [agent_name])[0]
        print(
            f"Error: Agent CLI binary '{primary_bin}' not found on PATH.\n"
            f"Please install '{primary_bin}' and ensure it is accessible in your PATH.",
            file=sys.stderr,
        )
        return 1

    if local_llm_base is None:
        env_base = os.getenv("HOLON_LOCAL_LLM_BASE")
        if env_base:
            local_llm_base = env_base.strip() or None

    route = None
    if local_llm_base is not None:
        route = plan_route(local_llm_base)
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

    container_started = ensure_proxy(port=port, host_local_spec=route.container_env_value if route else "")

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
            reachable, detail = probe_host(route.target.port)
        drop_no_proxy = report_route(route, reachable, detail)

    try:
        child_env = build_env(
            agent_name,
            port,
            drop_no_proxy=drop_no_proxy,
            model=model,
            local_llm_base=local_llm_base,
        )
    except TypeError:
        child_env = build_env(agent_name, port, drop_no_proxy=drop_no_proxy)

    cmd = [binary_path, *agent_args]

    try:
        return exec_proc(cmd, child_env)
    finally:
        if ephemeral and container_started:
            stop_container()


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
