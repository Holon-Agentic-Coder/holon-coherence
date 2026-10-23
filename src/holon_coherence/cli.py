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
    build_agent_env,
    build_proxy_env,
    check_docker_daemon,
    container_host_local_spec,
    docker_host_alias_args,
    ensure_docker_image,
    ensure_proxy_running,
    execute_interactive_process,
    extract_runner_flags,
    find_available_port,
    find_system_ca_bundle,
    format_endpoint_rows,
    get_active_web_token,
    get_container_mapped_port,
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
    plan_local_llm_route,
    print_endpoints,
    probe_host_local_reachable,
    report_local_llm_route,
    resolve_agent_binary,
    resolve_container_endpoints,
    resolve_web_password,
    run_agent,
    save_web_token,
    stop_proxy_container,
    wait_for_proxy_ready,
)
from holon_coherence.host_local import GATEWAY_HOSTNAME, detect_host_addresses

__all__ = [
    "AGENT_BINARY_MAP",
    "CA_ENV_VARS",
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
            kwargs = {
                "ephemeral": flags.ephemeral,
                "port": flags.port,
                "local_llm_base": flags.local_llm_base,
            }
            if flags.model is not None:
                kwargs["model"] = flags.model
            sys.exit(run_agent(first, flags.agent_args, **kwargs))
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
            kwargs = {
                "ephemeral": flags.ephemeral,
                "port": flags.port,
                "local_llm_base": flags.local_llm_base,
            }
            if flags.model is not None:
                kwargs["model"] = flags.model
            sys.exit(run_agent(agent_target, flags.agent_args[1:], **kwargs))

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
    start_parser.add_argument(
        "--web",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Launch the mitmweb raw request/response inspector (default: on; use --no-web for a headless "
        "mitmdump-only start)",
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
        "auto-generated token)",
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

    # Stop proxy container
    stop_parser = subparsers.add_parser("stop", help="Stop and remove running holon-coherence Docker container")
    stop_parser.add_argument(
        "--name",
        default=None,
        help="Container name (defaults to HOLON_CONTAINER_NAME or holon-coherence-proxy)",
    )

    # Status of proxy container
    status_parser = subparsers.add_parser("status", help="Check status of holon-coherence Docker container")
    status_parser.add_argument(
        "--name",
        default=None,
        help="Container name (defaults to HOLON_CONTAINER_NAME or holon-coherence-proxy)",
    )

    # Logs of proxy container
    logs_parser = subparsers.add_parser("logs", help="View logs of holon-coherence Docker container")
    logs_parser.add_argument("-f", "--follow", action="store_true", help="Follow log stream")
    logs_parser.add_argument(
        "--name",
        default=None,
        help="Container name (defaults to HOLON_CONTAINER_NAME or holon-coherence-proxy)",
    )

    # Build image
    build_parser = subparsers.add_parser("build", help="Build the holon-coherence Docker image")
    build_parser.add_argument(
        "--tag", default="holon-coherence:latest", help="Docker tag (default: holon-coherence:latest)"
    )

    # Init CA
    ca_parser = subparsers.add_parser("init-ca", help="Bootstrap self-signed Root CA certificates")
    ca_parser.add_argument("--output-dir", default=os.path.expanduser("~/.holon/proxy-ca"), help="Target CA directory")

    # Web dashboard token helpers
    subparsers.add_parser("web-token", help="Display active web dashboard authentication token")
    subparsers.add_parser("web-key", help="Alias for web-token")

    # Metrics reporting
    metrics_parser = subparsers.add_parser("metrics", help="Display cumulative optimization metrics")
    metrics_parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"Proxy listen port (default: {DEFAULT_PROXY_PORT} or HOLON_PROXY_PORT)",
    )
    metrics_parser.add_argument(
        "--name",
        default=None,
        help="Container name (defaults to HOLON_CONTAINER_NAME or holon-coherence-proxy)",
    )
    metrics_parser.add_argument(
        "--offline",
        action="store_true",
        help="Display offline telemetry metrics if live proxy is unreachable",
    )
    metrics_parser.add_argument("--json", action="store_true", help="Output metrics as raw JSON")

    # A/B testing suite
    ab_parser = subparsers.add_parser(
        "ab-test",
        help="Run real-traffic A/B benchmark comparing baseline vs optimized runs",
    )
    ab_parser.add_argument(
        "--command",
        "-c",
        dest="workload_cmd",
        default=None,
        help="Command/agent workload to execute twice through proxy with real LLM traffic",
    )
    ab_parser.add_argument(
        "--trace-file",
        "-f",
        default=None,
        help="Path to authentic trace transactions (.jsonl or .json) file",
    )
    ab_parser.add_argument(
        "--live",
        action="store_true",
        help="Replay trace requests as live HTTP traffic through proxy against real upstream LLM endpoints",
    )
    ab_parser.add_argument(
        "--baseline",
        default=None,
        help="Path to authentic baseline wire log file or directory (Variant A)",
    )
    ab_parser.add_argument(
        "--optimized",
        default=None,
        help="Path to authentic optimized wire log file or directory (Variant B)",
    )
    ab_parser.add_argument(
        "--rounds",
        "-n",
        type=int,
        default=1,
        help="Number of evaluation rounds to run (default: 1)",
    )
    ab_parser.add_argument(
        "--fail-under-reduction",
        type=float,
        default=None,
        help="Enforce minimum token reduction percentage gate (e.g. 15.0 for 15%%)",
    )
    ab_parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON comparison scorecard",
    )

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

    # Register run-agent and agent alias subparsers for discovery
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

    args = parser.parse_args(argv)

    if not argv or args.command is None:
        parser.print_help(sys.stderr)
        sys.exit(1)

    if args.command == "init-ca":
        handle_init_ca(args)

    elif args.command == "build":
        handle_build(args)

    elif args.command == "stop":
        handle_stop(args)

    elif args.command == "status":
        handle_status(args)

    elif args.command == "metrics":
        sys.exit(handle_metrics(args))

    elif args.command == "ab-test":
        sys.exit(handle_ab_test(args))

    elif args.command == "logs":
        handle_logs(args)

    elif args.command == "run":
        sys.exit(handle_run(args))

    elif args.command == "start":
        handle_start(args)

    elif args.command in ("web-token", "web-key"):
        sys.exit(handle_web_token(args))

    else:
        parser.print_help(sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
