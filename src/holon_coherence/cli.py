"""CLI wrapper for holon-coherence proxy orchestration and agent execution."""

from __future__ import annotations

import argparse
import os
import sys

from holon_coherence.ca_generator import generate_root_ca
from holon_coherence.commands import (
    _CONTAINER_GATEWAY_PROBE,
    AGENT_BINARY_MAP,
    CA_ENV_VARS,
    CONTAINER_NAME,
    DEFAULT_PROXY_PORT,
    DEFAULT_WEB_PORT,
    DOCKER_BUILD_TIMEOUT_SECONDS,
    NO_PROXY_HOSTS,
    PROXY_POLL_INTERVAL_SECONDS,
    PROXY_READY_TIMEOUT_SECONDS,
    SUPPORTED_AGENTS,
    WEB_TOKEN_PATH,
    ExposedEndpoints,
    LocalLlmRoute,
    RunnerFlags,
    _print_agent_help,
    _print_run_agent_help,
    ab_test,
    agents,
    build_agent_env,
    build_proxy_env,
    ca,
    check_docker_daemon,
    container_host_local_spec,
    docker_host_alias_args,
    docker_ops,
    ensure_docker_image,
    ensure_proxy_running,
    execute_interactive_process,
    extract_runner_flags,
    find_available_port,
    find_system_ca_bundle,
    format_endpoint_rows,
    get_active_web_token,
    get_container_mapped_port,
    get_container_web_token,
    get_or_create_merged_ca_bundle,
    handle_ab_test,
    handle_build,
    handle_init_ca,
    handle_logs,
    handle_metrics,
    handle_run,
    handle_start,
    handle_status,
    handle_stop,
    handle_web_token,
    host_local_container_args,
    host_local_covered,
    is_container_bound_to_port,
    is_container_running,
    is_in_container,
    is_port_in_use,
    is_web_inspector_enabled,
    merge_no_proxy_values,
    metrics,
    plan_local_llm_route,
    print_endpoints,
    probe_host_local_reachable,
    report_local_llm_route,
    resolve_agent_binary,
    resolve_container_endpoints,
    resolve_web_password,
    run_agent,
    runner,
    save_web_token,
    start,
    stop_proxy_container,
    wait_for_proxy_ready,
    web_token,
)
from holon_coherence.host_local import GATEWAY_HOSTNAME, detect_host_addresses

COMMAND_MODULES = (
    start,
    docker_ops,
    agents,
    runner,
    ca,
    metrics,
    ab_test,
    web_token,
)

__all__ = [
    "AGENT_BINARY_MAP",
    "CA_ENV_VARS",
    "COMMAND_MODULES",
    "CONTAINER_NAME",
    "DEFAULT_PROXY_PORT",
    "DEFAULT_WEB_PORT",
    "DOCKER_BUILD_TIMEOUT_SECONDS",
    "NO_PROXY_HOSTS",
    "PROXY_POLL_INTERVAL_SECONDS",
    "PROXY_READY_TIMEOUT_SECONDS",
    "SUPPORTED_AGENTS",
    "WEB_TOKEN_PATH",
    "_CONTAINER_GATEWAY_PROBE",
    "ExposedEndpoints",
    "LocalLlmRoute",
    "RunnerFlags",
    "_print_agent_help",
    "_print_run_agent_help",
    "build_agent_env",
    "build_parser",
    "build_proxy_env",
    "check_docker_daemon",
    "container_host_local_spec",
    "detect_host_addresses",
    "docker_host_alias_args",
    "ensure_docker_image",
    "ensure_proxy_running",
    "execute_interactive_process",
    "extract_runner_flags",
    "find_available_port",
    "find_system_ca_bundle",
    "format_endpoint_rows",
    "generate_root_ca",
    "get_active_web_token",
    "get_container_mapped_port",
    "get_container_web_token",
    "get_or_create_merged_ca_bundle",
    "handle_ab_test",
    "handle_build",
    "handle_init_ca",
    "handle_logs",
    "handle_metrics",
    "handle_run",
    "handle_start",
    "handle_status",
    "handle_stop",
    "handle_web_token",
    "host_local_container_args",
    "host_local_covered",
    "is_container_bound_to_port",
    "is_container_running",
    "is_in_container",
    "is_port_in_use",
    "is_web_inspector_enabled",
    "main",
    "merge_no_proxy_values",
    "plan_local_llm_route",
    "print_endpoints",
    "probe_host_local_reachable",
    "report_local_llm_route",
    "resolve_agent_binary",
    "resolve_container_endpoints",
    "resolve_web_password",
    "run_agent",
    "save_web_token",
    "stop_proxy_container",
    "wait_for_proxy_ready",
]


def build_parser() -> argparse.ArgumentParser:
    """Construct main CLI parser with self-registered command subparsers."""
    parser = argparse.ArgumentParser(
        prog="holon-coherence",
        description="High-coherence, low-entropy optimization gateway for fractal coding agents.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    for cmd_mod in COMMAND_MODULES:
        cmd_mod.register(subparsers)
    return parser


def _dispatch_agent_argv(argv: list[str]) -> bool:
    """Direct agent invocation fast-path or run-agent subcommand dispatch."""
    first = argv[0]
    if first in SUPPORTED_AGENTS:
        flags = extract_runner_flags(argv[1:])
        if flags.help_requested:
            _print_agent_help(first)
            sys.exit(0)
        kwargs = {
            "ephemeral": flags.ephemeral,
            "port": flags.port,
            "local_llm_base": flags.local_llm_base,
        }
        if flags.model is not None:
            kwargs["model"] = flags.model
        sys.exit(run_agent(first, flags.agent_args, **kwargs))
    if first == "run-agent":
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
        kwargs = {
            "ephemeral": flags.ephemeral,
            "port": flags.port,
            "local_llm_base": flags.local_llm_base,
        }
        if flags.model is not None:
            kwargs["model"] = flags.model
        sys.exit(run_agent(agent_target, flags.agent_args[1:], **kwargs))
    return False


def main(argv: list[str] | None = None) -> None:
    """Main CLI entrypoint for holon-coherence."""
    if argv is None:
        argv = sys.argv[1:]

    if argv and _dispatch_agent_argv(argv):
        return

    parser = build_parser()
    args = parser.parse_args(argv)

    if not argv or args.command is None:
        parser.print_help(sys.stderr)
        sys.exit(1)

    handler = getattr(args, "handler", None)
    if handler is not None:
        res = handler(args)
        if args.command in ("run", "metrics", "ab-test", "web-token", "web-key"):
            sys.exit(res if isinstance(res, int) else 0)
        if isinstance(res, int) and res != 0:
            sys.exit(res)
        return

    parser.print_help(sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
