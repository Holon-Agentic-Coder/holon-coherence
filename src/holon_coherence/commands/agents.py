"""Agent command dispatchers and runner wrappers."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, NamedTuple, NoReturn, TypedDict, Unpack

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
    """Mutable state while ``extract_runner_flags`` walks argv."""

    ephemeral: bool = False
    port: int | None = None
    help_requested: bool = False
    local_llm_base: str | None = None
    model: str | None = None
    agent_args: list[str] = field(default_factory=list)

    def to_flags(self) -> RunnerFlags:
        return RunnerFlags(
            self.ephemeral,
            self.port,
            self.agent_args,
            help_requested=self.help_requested,
            local_llm_base=self.local_llm_base,
            model=self.model,
        )


_LOCAL_LLM_FLAGS = ("--local-llm-base", "--local-llm-endpoint")


def _usage_error(message: str) -> NoReturn:
    """Print a runner flag error to stderr and exit with status 1."""
    print(message, file=sys.stderr)
    sys.exit(1)


def _parse_flag_value(argv: list[str], idx: int, flag_name: str, error: str) -> tuple[str, int]:
    """Value of the option at ``argv[idx]`` (``--flag value`` or ``--flag=value``) and the next index."""
    arg = argv[idx]
    if arg.startswith(f"{flag_name}="):
        value = arg.split("=", 1)[1]
        if not value:
            _usage_error(error)
        return value, idx + 1
    if idx + 1 >= len(argv) or argv[idx + 1] == "--":
        _usage_error(error)
    return argv[idx + 1], idx + 2


def _parse_port_flag(argv: list[str], idx: int) -> tuple[int, int]:
    """Parse ``--port`` into a TCP port in 1-65535; returns ``(port, next_index)``."""
    raw, next_idx = _parse_flag_value(argv, idx, "--port", "Error: Option --port requires an argument.")
    try:
        port = int(raw)
    except ValueError:
        _usage_error(f"Error: Argument to --port must be an integer, got '{raw}'.")
    if not (1 <= port <= 65535):
        _usage_error(f"Error: Port must be between 1 and 65535, got {port}.")
    return port, next_idx


def _consume_runner_arg(argv: list[str], idx: int, acc: _RunnerFlagAccumulator) -> int:
    """Record the runner flag (or agent argument) at ``argv[idx]``; returns the next index."""
    arg = argv[idx]
    flag_name = arg.split("=", 1)[0]
    if arg == "--ephemeral":
        acc.ephemeral = True
        return idx + 1
    if arg in ("--help", "-h"):
        acc.help_requested = True
        return idx + 1
    if flag_name in _LOCAL_LLM_FLAGS:
        error = f"Error: Option {flag_name} requires an argument, e.g. localhost:8081."
        acc.local_llm_base, next_idx = _parse_flag_value(argv, idx, flag_name, error)
        return next_idx
    if flag_name == "--model":
        acc.model, next_idx = _parse_flag_value(argv, idx, flag_name, "Error: Option --model requires an argument.")
        # The agent needs --model too, in the exact form the user typed it.
        acc.agent_args.extend(argv[idx:next_idx])
        return next_idx
    if flag_name == "--port":
        acc.port, next_idx = _parse_port_flag(argv, idx)
        return next_idx
    acc.agent_args.append(arg)
    return idx + 1


def extract_runner_flags(argv: list[str]) -> RunnerFlags:
    """Extract runner flags and ``--help`` from arguments, preserving agent argument order."""
    acc = _RunnerFlagAccumulator()
    idx = 0
    while idx < len(argv):
        if argv[idx] == "--":
            acc.agent_args.extend(argv[idx + 1 :])
            break
        idx = _consume_runner_arg(argv, idx, acc)
    return acc.to_flags()


def resolve_agent_binary(agent_name: str) -> str | None:
    """Find the executable binary for the specified agent on the host PATH."""
    candidates = AGENT_BINARY_MAP.get(agent_name, [agent_name])
    for candidate in candidates:
        path = shutil.which(candidate)
        if path:
            return path
    return None


_AGENT_KEY_ENV_VARS: dict[str, tuple[str, ...]] = {
    "agy": ("GEMINI_API_KEY", "AGY_USER_TOKEN"),
    "codex": ("OPENAI_API_KEY",),
    "opencode": ("OPENCODE_API_KEY",),
    "pi": ("PI_API_KEY",),
}


def _apply_proxy_and_ca_env(env: dict[str, str], port: int, drop_no_proxy: tuple[str, ...]) -> None:
    """Route the agent through the proxy; drop CA variables unless the full trust bundle is available."""
    proxy_env = build_proxy_env(f"http://127.0.0.1:{port}", drop_no_proxy=drop_no_proxy)
    env.update(proxy_env)
    if not all(var in proxy_env for var in CA_ENV_VARS):
        for var in CA_ENV_VARS:
            env.pop(var, None)


def _apply_local_llm_env(
    env: dict[str, str], agent_name: str, port: int, model: str | None, holon_key: str | None
) -> None:
    """Point the agent's provider base URL (and model) at the proxy for a host-local model server."""
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
    """Map the universal ``HOLON_AGENT_KEY`` onto the agent's own credential variables."""
    if agent_name == "claude":
        env.setdefault("ANTHROPIC_API_KEY", holon_key)
        return
    for var in _AGENT_KEY_ENV_VARS.get(agent_name, ()):
        env[var] = holon_key


def build_agent_env(
    agent_name: str,
    port: int,
    drop_no_proxy: tuple[str, ...] = (),
    model: str | None = None,
    local_llm_base: str | None = None,
) -> dict[str, str]:
    """Construct environment variables for the child agent subprocess."""
    env = os.environ.copy()
    _apply_proxy_and_ca_env(env, port, drop_no_proxy)
    holon_key = env.get("HOLON_AGENT_KEY")
    if local_llm_base or os.getenv("HOLON_LOCAL_LLM_BASE"):
        _apply_local_llm_env(env, agent_name, port, model, holon_key)
    if holon_key:
        _apply_auth_key_env(env, agent_name, holon_key)
    return env


class AgentRunOptions(TypedDict, total=False):
    """Keyword options accepted by :func:`run_agent`."""

    ephemeral: bool
    port: int | None
    local_llm_base: str | None
    model: str | None


@dataclass(frozen=True)
class AgentRunnerDeps:
    """Optional collaborators for :func:`run_agent`; ``None`` selects this module's default."""

    resolve_bin_fn: Callable[[str], str | None] | None = None
    plan_route_fn: Callable[[str], LocalLlmRoute | None] | None = None
    ensure_proxy_fn: Callable[..., bool] | None = None
    probe_host_fn: Callable[[int], tuple[bool, str]] | None = None
    report_route_fn: Callable[..., tuple[str, ...]] | None = None
    build_env_fn: Callable[..., dict[str, str]] | None = None
    exec_proc_fn: Callable[[list[str], dict[str, str]], int] | None = None
    stop_container_fn: Callable[..., None] | None = None


def _resolve_agent_port(port: int | None) -> int | None:
    """Validate an explicit ``--port`` or fall back to ``HOLON_PROXY_PORT`` / the default; None if invalid."""
    if port is not None:
        if not (1 <= port <= 65535):
            print(f"Error: Port must be between 1 and 65535, got {port}.", file=sys.stderr)
            return None
        return port
    env_port = os.getenv("HOLON_PROXY_PORT")
    if not env_port:
        return DEFAULT_PROXY_PORT
    try:
        parsed_port = int(env_port)
    except ValueError:
        parsed_port = 0
    if 1 <= parsed_port <= 65535:
        return parsed_port
    print(f"⚠️  Invalid HOLON_PROXY_PORT '{env_port}', falling back to {DEFAULT_PROXY_PORT}.", file=sys.stderr)
    return DEFAULT_PROXY_PORT


def _report_missing_binary(agent_name: str) -> None:
    """Explain which agent executable is missing from PATH."""
    primary_bin = AGENT_BINARY_MAP.get(agent_name, [agent_name])[0]
    print(
        f"Error: Agent CLI binary '{primary_bin}' not found on PATH.\n"
        f"Please install '{primary_bin}' and ensure it is accessible in your PATH.",
        file=sys.stderr,
    )


def _resolve_local_llm_base(local_llm_base: str | None) -> str | None:
    """Explicit ``--local-llm-base`` wins; otherwise a non-blank ``HOLON_LOCAL_LLM_BASE``."""
    if local_llm_base is not None:
        return local_llm_base
    return (os.getenv("HOLON_LOCAL_LLM_BASE") or "").strip() or None


def _plan_agent_route(
    local_llm_base: str | None, port: int, plan_route: Callable[[str], LocalLlmRoute | None]
) -> tuple[bool, LocalLlmRoute | None]:
    """Plan the host-local route; ``(False, None)`` after reporting an unusable endpoint."""
    if local_llm_base is None:
        return True, None
    route = plan_route(local_llm_base)
    if route is None:
        print(
            f"Error: --local-llm-base '{local_llm_base}' is not a usable endpoint.\n"
            "Expected host:port or a base URL, e.g. localhost:8081, 127.0.0.1:8081, "
            "192.168.2.13:8081, http://localhost:11434/v1.",
            file=sys.stderr,
        )
        return False, None
    if route.target.port == port:
        print(
            f"Error: --local-llm-base port ({route.target.port}) cannot be the same as proxy port ({port}).",
            file=sys.stderr,
        )
        return False, None
    return True, route


def _setup_agent_local_route(route: LocalLlmRoute | None, deps: AgentRunnerDeps) -> tuple[str, ...]:
    """Probe the host-local endpoint from the container and return the NO_PROXY entries to drop."""
    if route is None:
        return ()
    if route.target.port is None:
        print(
            "⚠️  --local-llm-base without a port skips the container reachability preflight; "
            "prefer localhost:8081 so the route can be verified before NO_PROXY is changed.",
            file=sys.stderr,
        )
        reachable, detail = True, "preflight skipped (no port given)"
    else:
        reachable, detail = (deps.probe_host_fn or probe_host_local_reachable)(route.target.port)
    return (deps.report_route_fn or report_local_llm_route)(route, reachable, detail)


def _build_child_env(
    build_env: Callable[..., dict[str, str]],
    agent_name: str,
    port: int,
    drop_no_proxy: tuple[str, ...],
    options: AgentRunOptions,
) -> dict[str, str]:
    """Build the agent environment, tolerating builders that predate the model/local-LLM keywords."""
    try:
        return build_env(
            agent_name,
            port,
            drop_no_proxy=drop_no_proxy,
            model=options.get("model"),
            local_llm_base=options.get("local_llm_base"),
        )
    except TypeError:
        return build_env(agent_name, port, drop_no_proxy=drop_no_proxy)


def _execute_agent_with_cleanup(cmd: list[str], env: dict[str, str], teardown: bool, deps: AgentRunnerDeps) -> int:
    """Run the agent; with ``teardown`` remove the proxy container this run started, even on failure."""
    try:
        return (deps.exec_proc_fn or execute_interactive_process)(cmd, env)
    finally:
        if teardown:
            (deps.stop_container_fn or stop_proxy_container)()


def run_agent(
    agent_name: str,
    agent_args: list[str],
    *,
    deps: AgentRunnerDeps | None = None,
    **options: Unpack[AgentRunOptions],
) -> int:
    """Launch the optimization proxy and execute the requested coding agent with full telemetry.

    ``options`` carries ``ephemeral``, ``port``, ``local_llm_base`` and ``model``; any other keyword
    (such as the retired ``resolve_bin_fn`` / ``exec_proc_fn``, now on ``deps``) raises ``TypeError``.
    """
    unknown = sorted(set(options) - AgentRunOptions.__optional_keys__ - AgentRunOptions.__required_keys__)
    if unknown:
        raise TypeError(f"run_agent() got unexpected keyword argument(s): {', '.join(unknown)}")
    deps = deps or AgentRunnerDeps()
    port = _resolve_agent_port(options.get("port"))
    if port is None:
        return 1

    binary_path = (deps.resolve_bin_fn or resolve_agent_binary)(agent_name)
    if not binary_path:
        _report_missing_binary(agent_name)
        return 1

    local_llm_base = _resolve_local_llm_base(options.get("local_llm_base"))
    route_ok, route = _plan_agent_route(local_llm_base, port, deps.plan_route_fn or plan_local_llm_route)
    if not route_ok:
        return 1

    ensure_proxy = deps.ensure_proxy_fn or ensure_proxy_running
    container_started = ensure_proxy(port=port, host_local_spec=route.container_env_value if route else "")
    drop_no_proxy = _setup_agent_local_route(route, deps)
    child_env = _build_child_env(
        deps.build_env_fn or build_agent_env,
        agent_name,
        port,
        drop_no_proxy,
        {**options, "local_llm_base": local_llm_base},
    )
    teardown = bool(options.get("ephemeral", False) and container_started)
    return _execute_agent_with_cleanup([binary_path, *agent_args], child_env, teardown, deps)


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
