"""CLI entrypoint for holon-coherence optimization proxy."""

import argparse
import os
import shutil
import subprocess
import sys

from holon_coherence.ca_generator import generate_root_ca


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="holon-coherence",
        description="High-coherence, low-entropy optimization gateway for fractal coding agents.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Start proxy
    start_parser = subparsers.add_parser("start", help="Start the optimization proxy sidecar")
    start_parser.add_argument("--port", type=int, default=8080, help="Proxy listen port (default: 8080)")
    start_parser.add_argument("--web", action="store_true", help="Launch mitmweb dashboard on port 8081")
    start_parser.add_argument("--web-port", type=int, default=8081, help="Web dashboard port (default: 8081)")

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
        addon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mitm_addon.py")
        tool = "mitmweb" if args.web else "mitmdump"
        # Look adjacent to the active python interpreter first, then check PATH
        tool_candidate = os.path.join(os.path.dirname(sys.executable), tool)
        tool_path = tool_candidate if os.path.isfile(tool_candidate) else (shutil.which(tool) or tool)

        cmd = [tool_path, "-s", addon_path, "--listen-port", str(args.port)]
        if args.web:
            cmd.extend(["--web-host", "0.0.0.0", "--web-port", str(args.web_port)])
        print(f"🚀 Starting holon-coherence via {tool} on port {args.port}...")
        try:
            subprocess.run(cmd, check=True)
        except KeyboardInterrupt:
            print("\nShutting down holon-coherence proxy.")
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
