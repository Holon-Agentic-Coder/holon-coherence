"""CLI entrypoint for holon-coherence optimization proxy."""

import argparse
import os
import shutil
import subprocess
import sys

from holon_coherence.ca_generator import generate_root_ca


def is_in_container() -> bool:
    """Return True if executing within a Docker container environment."""
    return os.path.exists("/.dockerenv") or os.environ.get("HOLON_IN_CONTAINER") == "1"


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="holon-coherence",
        description="High-coherence, low-entropy optimization gateway for fractal coding agents.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Start proxy
    start_parser = subparsers.add_parser("start", help="Start the optimization proxy sidecar (via Docker by default)")
    start_parser.add_argument("--port", type=int, default=8080, help="Proxy listen port (default: 8080)")
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
    subparsers.add_parser("stop", help="Stop running holon-coherence Docker container")

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

    args = parser.parse_args()

    if args.command == "init-ca":
        ca_dir = generate_root_ca(output_dir=args.output_dir)
        print(f"✅ Root CA generated successfully at: {ca_dir}")

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
        print("🛑 Stopping holon-coherence Docker container...")
        subprocess.run(["docker", "stop", "holon-coherence"])

    elif args.command == "status":
        subprocess.run(["docker", "ps", "-a", "--filter", "name=holon-coherence"])

    elif args.command == "logs":
        cmd = ["docker", "logs"]
        if args.follow:
            cmd.append("-f")
        cmd.append("holon-coherence")
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
        env["NO_PROXY"] = "localhost,127.0.0.1,api.github.com,github.com"
        ca_cert = os.path.expanduser(args.ca_cert)
        if os.path.exists(ca_cert):
            env["SSL_CERT_FILE"] = ca_cert
            env["REQUESTS_CA_BUNDLE"] = ca_cert
            env["NODE_EXTRA_CA_CERTS"] = ca_cert

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

        # On host: wrap docker execution
        if not shutil.which("docker"):
            print("Error: Docker is not installed or not found in PATH.", file=sys.stderr)
            print("holon-coherence runs inside Docker to eliminate host system dependencies.", file=sys.stderr)
            print(
                "Install Docker or use 'holon-coherence start --native' if mitmproxy is installed on the host.",
                file=sys.stderr,
            )
            sys.exit(1)

        daemon_check = subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if daemon_check.returncode != 0:
            print("Error: Docker daemon is not running.", file=sys.stderr)
            print("Please start Docker Desktop / daemon and try again.", file=sys.stderr)
            sys.exit(1)

        ca_dir = os.path.expanduser("~/.holon/proxy-ca")
        cache_dir = os.path.expanduser("~/.holon/cache")
        logs_dir = os.path.expanduser("~/.holon/logs")
        os.makedirs(ca_dir, exist_ok=True)
        os.makedirs(cache_dir, exist_ok=True)
        os.makedirs(logs_dir, exist_ok=True)

        ca_cert = os.path.join(ca_dir, "mitmproxy-ca-cert.pem")
        if not os.path.exists(ca_cert):
            print(f"🔑 Generating Root CA certificates at {ca_dir}...")
            generate_root_ca(output_dir=ca_dir)

        # Check if Docker image exists
        img_check = subprocess.run(
            ["docker", "image", "inspect", args.image],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if img_check.returncode != 0 or args.build:
            print(f"🔨 Building Docker image '{args.image}'...")
            repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            dockerfile = os.path.join(repo_root, "Dockerfile")
            if os.path.exists(dockerfile):
                subprocess.run(["docker", "build", "-t", args.image, repo_root], check=True)
            else:
                print(
                    f"Error: Docker image '{args.image}' not found and Dockerfile not at {dockerfile}.",
                    file=sys.stderr,
                )
                sys.exit(1)

        # Remove existing container with the same name if stopped or stale
        subprocess.run(["docker", "rm", "-f", "holon-coherence"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        docker_cmd = [
            "docker",
            "run",
            "--name",
            "holon-coherence",
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
                    ["docker", "stop", "holon-coherence"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
