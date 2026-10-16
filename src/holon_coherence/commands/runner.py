"""Runner command and subprocess execution environment forwarding."""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
from typing import Any

from holon_coherence.commands._dispatch import get_cli
from holon_coherence.commands.ca import CA_ENV_VARS, get_or_create_merged_ca_bundle
from holon_coherence.host_local import parse_no_proxy

NO_PROXY_HOSTS = "localhost,127.0.0.1,::1,169.254.169.254,api.github.com,github.com"


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

    cli = get_cli()
    merger = getattr(cli, "merge_no_proxy_values", merge_no_proxy_values)
    merged_no_proxy = merger()
    if drop_no_proxy:
        dropped = {entry.strip().lower() for entry in drop_no_proxy if entry.strip()}
        merged_no_proxy = ",".join(entry for entry in parse_no_proxy(merged_no_proxy) if entry.lower() not in dropped)
    env["NO_PROXY"] = merged_no_proxy
    env["no_proxy"] = merged_no_proxy
    env["COHERENCE_TOKEN_REDUCTION"] = os.environ.get("COHERENCE_TOKEN_REDUCTION", "1")
    env["HOLON_PASSIVE_MONITORING"] = os.environ.get("HOLON_PASSIVE_MONITORING", "0")

    # Certificate bundle resolution
    if ca_cert_path is None:
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
        bundle_getter = getattr(cli, "get_or_create_merged_ca_bundle", get_or_create_merged_ca_bundle)
        merged_bundle = bundle_getter(ca_cert)
        for var in CA_ENV_VARS:
            env[var] = merged_bundle
    else:
        print(
            f"⚠️  Warning: CA certificate not found at '{ca_cert}'.\n"
            "Outbound TLS requests through the proxy may fail verification.\n"
            "Ensure 'holon-coherence start' has been run at least once or "
            "initialize CA with 'holon-coherence init-ca'.",
            file=sys.stderr,
        )

    return env


def execute_interactive_process(cmd: list[str], env: dict[str, str]) -> int:
    """Execute child process with interactive stdio passthrough, signal forwarding, and exit code propagation."""

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


def handle_run(args: Any) -> int:
    """Run a command with inline proxy properties."""
    if not args.cmd:
        print("Error: No command specified to run.", file=sys.stderr)
        sys.exit(1)
    raw_cmd = args.cmd
    if raw_cmd[0] == "--":
        raw_cmd = raw_cmd[1:]
    if not raw_cmd:
        print("Error: No command specified after '--'.", file=sys.stderr)
        sys.exit(1)

    cli = get_cli()
    env = os.environ.copy()
    env_builder = getattr(cli, "build_proxy_env", build_proxy_env)
    env.update(env_builder(args.proxy_url, args.ca_cert))

    exec_proc = getattr(cli, "execute_interactive_process", execute_interactive_process)
    return exec_proc(raw_cmd, env)
