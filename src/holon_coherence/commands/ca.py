"""CA certificate management and initialization commands."""

from __future__ import annotations

import argparse
import contextlib
import os
import ssl
from collections.abc import Callable
from typing import Any

from holon_coherence.ca_generator import generate_root_ca

CA_ENV_VARS = (
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "NODE_EXTRA_CA_CERTS",
    "GIT_SSL_CAINFO",
)


def find_system_ca_bundle() -> str | None:
    """Locate host system or certifi CA certificate bundle."""
    for env_var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        val = os.environ.get(env_var)
        if (
            val
            and not val.endswith(("holon-merged-ca-bundle.crt", "mitmproxy-ca-cert.pem", "holon-root-ca.crt"))
            and os.path.isfile(val)
        ):
            return os.path.abspath(val)

    try:
        cafile = ssl.get_default_verify_paths().cafile
        if (
            cafile
            and not cafile.endswith(("holon-merged-ca-bundle.crt", "mitmproxy-ca-cert.pem", "holon-root-ca.crt"))
            and os.path.isfile(cafile)
        ):
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


def _merged_bundle_is_fresh(merged_path: str, ca_cert_path: str, system_ca: str | None) -> bool:
    """True when the merged bundle on disk is at least as new as its source certificates."""
    if not os.path.isfile(merged_path):
        return False
    try:
        merged_mtime = os.path.getmtime(merged_path)
        ca_mtime = os.path.getmtime(ca_cert_path)
        return merged_mtime >= ca_mtime and (
            not system_ca or not os.path.isfile(system_ca) or merged_mtime >= os.path.getmtime(system_ca)
        )
    except OSError:
        return False


def _read_cert_text(path: str) -> str:
    """Read a certificate file's text, returning an empty string when unreadable."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return ""


def _compose_merged_content(holon_cert: str, system_certs: str) -> str:
    """Combine the system CA roots and the Holon CA, deduplicating an already-included Holon cert."""
    if not system_certs:
        return f"{holon_cert}\n"
    if holon_cert in system_certs:
        return f"{system_certs}\n"
    return f"{system_certs}\n\n{holon_cert}\n"


def get_or_create_merged_ca_bundle(
    ca_cert_path: str,
    find_bundle_fn: Callable[[], str | None] | None = None,
) -> str:
    """Create or return a merged CA certificate bundle combining system/certifi CA roots and the Holon CA.

    This ensures direct connections via NO_PROXY succeed without TLS failures while still trusting
    the Holon proxy for intercepted endpoints.
    """
    find_bundle = find_bundle_fn or find_system_ca_bundle
    ca_cert_path = os.path.abspath(ca_cert_path)
    target_dir = os.path.dirname(ca_cert_path)
    merged_path = os.path.join(target_dir, "holon-merged-ca-bundle.crt")

    if not os.path.isfile(ca_cert_path):
        return ca_cert_path

    system_ca = find_bundle()
    if _merged_bundle_is_fresh(merged_path, ca_cert_path, system_ca):
        return merged_path

    holon_cert = _read_cert_text(ca_cert_path)
    if not holon_cert:
        return ca_cert_path

    system_certs = _read_cert_text(system_ca) if system_ca and os.path.isfile(system_ca) else ""
    merged_content = _compose_merged_content(holon_cert, system_certs)

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


def handle_init_ca(args: Any) -> int:
    """Bootstrap self-signed Root CA certificates."""
    ca_cert, ca_key = generate_root_ca(output_dir=args.output_dir)
    print(f"✅ Root CA generated successfully:\n  Certificate: {ca_cert}\n  Key: {ca_key}")
    return 0


def handle(args: Any) -> int:
    """Handle init-ca command."""
    return handle_init_ca(args)


def register(subparsers: Any) -> argparse.ArgumentParser:
    """Register the init-ca subparser."""
    ca_parser = subparsers.add_parser("init-ca", help="Bootstrap self-signed Root CA certificates")
    ca_parser.add_argument("--output-dir", default=os.path.expanduser("~/.holon/proxy-ca"), help="Target CA directory")
    ca_parser.set_defaults(handler=handle)
    return ca_parser
