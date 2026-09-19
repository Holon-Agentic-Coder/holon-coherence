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
from typing import Any

from holon_coherence.ca_generator import generate_root_ca

DEFAULT_PROXY_PORT = 8080
PROXY_READY_TIMEOUT_SECONDS = 15.0
PROXY_POLL_INTERVAL_SECONDS = 0.25
NO_PROXY_HOSTS = "localhost,127.0.0.1,::1,169.254.169.254,api.github.com,github.com"
CONTAINER_NAME = "holon-coherence"

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
        if val and not val.endswith("holon-merged-ca-bundle.crt") and os.path.isfile(val):
            return val

    try:
        cafile = ssl.get_default_verify_paths().cafile
        if cafile and not cafile.endswith("holon-merged-ca-bundle.crt") and os.path.isfile(cafile):
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
    res = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
        capture_output=True,
        text=True,
    )
    return res.returncode == 0 and res.stdout.strip().lower() == "true"


def is_container_bound_to_port(port: int, container_name: str = CONTAINER_NAME) -> bool:
    """Check if the container is currently running and bound to the specified host port."""
    res = subprocess.run(
        ["docker", "port", container_name, "8080/tcp"],
        capture_output=True,
        text=True,
    )
    output = res.stdout
    if res.returncode != 0 or not output.strip():
        fallback_res = subprocess.run(
            ["docker", "port", container_name],
            capture_output=True,
            text=True,
        )
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
        build_res = subprocess.run(["docker", "build", "-t", image, repo_root])
        if build_res.returncode != 0:
            print(f"Error: Failed to build Docker image '{image}'.", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"📥 Pulling Docker image '{image}'...")
        pull_res = subprocess.run(
            ["docker", "pull", image],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if pull_res.returncode != 0:
            if "/" not in image:
                ghcr_img = f"ghcr.io/holon-agentic-coder/{image}"
                print(f"📥 Attempting pull from {ghcr_img}...")
                ghcr_res = subprocess.run(["docker", "pull", ghcr_img])
                if ghcr_res.returncode != 0:
                    print(
                        f"Error: Could not find or pull Docker image '{image}' or '{ghcr_img}'.\n"
                        "Please verify your network connection or build the image locally.",
                        file=sys.stderr,
                    )
                    sys.exit(1)
                tag_res = subprocess.run(["docker", "tag", ghcr_img, image])
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


def ensure_proxy_running(
    port: int = DEFAULT_PROXY_PORT,
    image: str = "holon-coherence:latest",
) -> bool:
    """Ensure the holon-coherence optimization proxy is running in the background and healthy.

    Returns:
        bool: True if a new container was launched, False if an existing healthy container was reused.
    """
    ok, err_msg = check_docker_daemon()
    if not ok:
        print(err_msg, file=sys.stderr)
        sys.exit(1)

    # Check if proxy is already healthy and listening on port
    if is_port_in_use(port):
        if is_container_running(CONTAINER_NAME) and is_container_bound_to_port(port, CONTAINER_NAME):
            # Proxy container is running and healthy
            return False
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
    subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    docker_cmd = [
        "docker",
        "run",
        "-d",
        "--name",
        CONTAINER_NAME,
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

    return True


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


def build_agent_env(agent_name: str, port: int) -> dict[str, str]:
    """Construct environment variables for the child agent subprocess.

    Configures proxy routing, merged CA bundle, and maps universal HOLON_AGENT_KEY
    to vendor keys without inspecting or validating native host auth if omitted.
    """
    env = os.environ.copy()
    proxy_url = f"http://127.0.0.1:{port}"

    # Routing
    env["HTTP_PROXY"] = proxy_url
    env["HTTPS_PROXY"] = proxy_url
    env["ALL_PROXY"] = proxy_url
    env["http_proxy"] = proxy_url
    env["https_proxy"] = proxy_url
    env["all_proxy"] = proxy_url

    existing_no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy")
    raw_no_proxy = f"{NO_PROXY_HOSTS},{existing_no_proxy}" if existing_no_proxy else NO_PROXY_HOSTS
    no_proxy_entries = [entry.strip() for entry in raw_no_proxy.split(",") if entry.strip()]
    merged_no_proxy = ",".join(dict.fromkeys(no_proxy_entries))
    env["NO_PROXY"] = merged_no_proxy
    env["no_proxy"] = merged_no_proxy

    # Certificate bundle
    ca_dir = os.path.expanduser("~/.holon/proxy-ca")
    ca_cert = os.path.join(ca_dir, "mitmproxy-ca-cert.pem")
    if not os.path.exists(ca_cert):
        alt_ca = os.path.expanduser("~/.holon/certs/holon-root-ca.crt")
        if os.path.exists(alt_ca):
            ca_cert = alt_ca

    if os.path.exists(ca_cert):
        merged_bundle = get_or_create_merged_ca_bundle(ca_cert)
        env["SSL_CERT_FILE"] = merged_bundle
        env["REQUESTS_CA_BUNDLE"] = merged_bundle
        env["CURL_CA_BUNDLE"] = merged_bundle
        env["NODE_EXTRA_CA_CERTS"] = merged_bundle
    else:
        print(
            f"⚠️  Warning: CA certificate not found at '{ca_cert}'.\n"
            "Outbound TLS requests through the proxy may fail verification.\n"
            "Ensure 'holon-coherence start' has been run at least once or "
            "initialize CA with 'holon-coherence init-ca'.",
            file=sys.stderr,
        )

    # Credential mapping: HOLON_AGENT_KEY -> vendor keys
    # Invariant Rule 5: If HOLON_AGENT_KEY is omitted, runner never validates vendor keys;
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
    """
    try:
        proc = subprocess.Popen(cmd, env=env, stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr)
    except OSError as err:
        print(f"Error: Failed to execute '{cmd[0]}': {err}", file=sys.stderr)
        return 126

    def _forward_signal(sig: int, frame: Any) -> None:
        if proc.poll() is None:
            with contextlib.suppress(ProcessLookupError, ValueError, OSError):
                proc.send_signal(sig)

    old_handlers: dict[int, Any] = {}
    forward_signals = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGWINCH"):
        forward_signals.append(signal.SIGWINCH)

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


class RunnerFlags(tuple):
    """Container for extracted runner flags maintaining tuple backward compatibility."""

    ephemeral: bool
    port: int | None
    agent_args: list[str]
    help_requested: bool

    def __new__(
        cls,
        ephemeral: bool,
        port: int | None,
        agent_args: list[str],
        help_requested: bool = False,
    ) -> RunnerFlags:
        obj = super().__new__(cls, (ephemeral, port, agent_args))
        obj.ephemeral = ephemeral
        obj.port = port
        obj.agent_args = agent_args
        obj.help_requested = help_requested
        return obj


def extract_runner_flags(argv: list[str]) -> RunnerFlags:
    """Extract --ephemeral, --port, and runner --help flags from arguments, preserving agent argument order."""
    ephemeral = False
    port = None
    help_requested = False
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
        elif arg == "--port":
            if i + 1 < len(argv):
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
    return RunnerFlags(ephemeral, port, agent_args, help_requested=help_requested)


def run_agent(
    agent_name: str,
    agent_args: list[str],
    ephemeral: bool = False,
    port: int | None = None,
) -> int:
    """Launch the optimization proxy and execute the requested coding agent with full telemetry."""
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
    container_started = ensure_proxy_running(port=port)

    # Build environment
    child_env = build_agent_env(agent_name, port)

    # Assemble command
    cmd = [binary_path, *agent_args]

    try:
        return execute_interactive_process(cmd, child_env)
    finally:
        if ephemeral and container_started:
            stop_proxy_container()


def _print_agent_help(agent_name: str) -> None:
    """Print help information for running an agent."""
    print(f"usage: holon-coherence {agent_name} [--ephemeral] [--port PORT] [--] [agent_args ...]\n")
    print(f"Run {agent_name} coding agent with automated background proxy and wire optimization.\n")
    print("positional arguments:")
    print("  agent_args            Arguments passed directly to the agent CLI\n")
    print("options:")
    print("  --ephemeral           Stop and remove the proxy container when the agent exits")
    print(f"  --port PORT           Proxy listen port (default: {DEFAULT_PROXY_PORT} or HOLON_PROXY_PORT)\n")
    print("note:")
    print("  Use '--' to pass flags directly to the underlying agent (e.g. '-- --help').")


def _print_run_agent_help() -> None:
    """Print help information for run-agent command."""
    agents_str = ", ".join(sorted(set(SUPPORTED_AGENTS)))
    print("usage: holon-coherence run-agent <agent> [--ephemeral] [--port PORT] [--] [agent_args ...]\n")
    print("Run a coding agent with automated background proxy and wire optimization.\n")
    print("positional arguments:")
    print(f"  agent                 Target agent ({agents_str})")
    print("  agent_args            Arguments passed directly to the agent CLI\n")
    print("options:")
    print("  --ephemeral           Stop and remove the proxy container when the agent exits")
    print(f"  --port PORT           Proxy listen port (default: {DEFAULT_PROXY_PORT} or HOLON_PROXY_PORT)\n")
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
            sys.exit(run_agent(first, flags.agent_args, ephemeral=flags.ephemeral, port=flags.port))
        elif first == "run-agent":
            if not argv[1:]:
                _print_run_agent_help()
                sys.exit(0)
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
            sys.exit(run_agent(agent_target, flags.agent_args[1:], ephemeral=flags.ephemeral, port=flags.port))

    parser = argparse.ArgumentParser(
        prog="holon-coherence",
        description="High-coherence, low-entropy optimization gateway for fractal coding agents.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Start proxy
    start_parser = subparsers.add_parser("start", help="Start the optimization proxy sidecar (via Docker by default)")
    start_parser.add_argument("--port", type=int, default=DEFAULT_PROXY_PORT, help="Proxy listen port (default: 8080)")
    start_parser.add_argument("--web", action="store_true", help="Launch mitmweb dashboard on port 8081")
    start_parser.add_argument("--web-port", type=int, default=8081, help="Web dashboard port (default: 8081)")
    start_parser.add_argument("-d", "--detach", action="store_true", help="Run Docker container in background")
    start_parser.add_argument(
        "--image", default="holon-coherence:latest", help="Docker image tag (default: holon-coherence:latest)"
    )
    start_parser.add_argument("--build", action="store_true", help="Rebuild Docker image before starting")
    start_parser.add_argument(
        "--native", action="store_true", help="Run natively using host mitmproxy instead of Docker"
    )

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

    # Register run-agent and agent aliases in parser so --help describes them
    run_agent_parser = subparsers.add_parser("run-agent", help="Run a coding agent with automated background proxy")
    run_agent_parser.add_argument("agent", choices=sorted(set(SUPPORTED_AGENTS)), help="Target agent")
    run_agent_parser.add_argument(
        "--ephemeral", action="store_true", help="Stop proxy container after agent process exits"
    )
    run_agent_parser.add_argument(
        "--port", type=int, default=None, help=f"Proxy port (default: {DEFAULT_PROXY_PORT} or HOLON_PROXY_PORT)"
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
        alias_parser.add_argument("agent_args", nargs=argparse.REMAINDER, help="Arguments passed to the agent")

    args = parser.parse_args(argv)

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
        env["HTTP_PROXY"] = args.proxy_url
        env["HTTPS_PROXY"] = args.proxy_url
        env["ALL_PROXY"] = args.proxy_url
        env["http_proxy"] = args.proxy_url
        env["https_proxy"] = args.proxy_url
        env["all_proxy"] = args.proxy_url
        existing_no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy")
        raw_no_proxy = f"{NO_PROXY_HOSTS},{existing_no_proxy}" if existing_no_proxy else NO_PROXY_HOSTS
        no_proxy_entries = [entry.strip() for entry in raw_no_proxy.split(",") if entry.strip()]
        merged_no_proxy = ",".join(dict.fromkeys(no_proxy_entries))
        env["NO_PROXY"] = merged_no_proxy
        env["no_proxy"] = merged_no_proxy
        ca_cert = os.path.expanduser(args.ca_cert)
        if not os.path.exists(ca_cert):
            alt_ca = os.path.join(os.path.dirname(ca_cert), "holon-root-ca.crt")
            if os.path.exists(alt_ca):
                ca_cert = alt_ca

        if os.path.exists(ca_cert):
            merged_ca = get_or_create_merged_ca_bundle(ca_cert)
            env["SSL_CERT_FILE"] = merged_ca
            env["REQUESTS_CA_BUNDLE"] = merged_ca
            env["CURL_CA_BUNDLE"] = merged_ca
            env["NODE_EXTRA_CA_CERTS"] = ca_cert
        else:
            print(
                f"⚠️  Warning: CA certificate not found at '{ca_cert}'.\n"
                "Outbound TLS requests through the proxy may fail verification.\n"
                "Ensure 'holon-coherence start' has been run at least once or "
                "initialize CA with 'holon-coherence init-ca'.",
                file=sys.stderr,
            )

        result = subprocess.run(raw_cmd, env=env)
        sys.exit(result.returncode)

    elif args.command == "start":
        # If running inside container or explicitly requested --native, launch mitmproxy directly
        if is_in_container() or args.native:
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
            "--name",
            CONTAINER_NAME,
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
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
