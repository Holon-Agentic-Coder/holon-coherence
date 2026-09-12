"""CLI entrypoint for holon-coherence optimization proxy."""

import argparse
import os
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

    args = parser.parse_args()

    if args.command == "init-ca":
        ca_dir = generate_root_ca(output_dir=args.output_dir)
        print(f"✅ Root CA generated successfully at: {ca_dir}")
    elif args.command == "start":
        addon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mitm_addon.py")
        tool = "mitmweb" if args.web else "mitmdump"
        cmd = [tool, "-s", addon_path, "--listen-port", str(args.port)]
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
