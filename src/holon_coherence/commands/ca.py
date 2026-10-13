"""CA certificate management and initialization commands."""

from __future__ import annotations

import contextlib
import os
import ssl
from typing import Any

from holon_coherence.ca_generator import generate_root_ca
from holon_coherence.commands._dispatch import get_cli

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


def get_or_create_merged_ca_bundle(ca_cert_path: str) -> str:
    """Create or return a merged CA certificate bundle combining system/certifi CA roots and the Holon CA.

    This ensures direct connections via NO_PROXY succeed without TLS failures while still trusting
    the Holon proxy for intercepted endpoints.
    """
    ca_cert_path = os.path.abspath(ca_cert_path)
    target_dir = os.path.dirname(ca_cert_path)
    merged_path = os.path.join(target_dir, "holon-merged-ca-bundle.crt")

    if not os.path.isfile(ca_cert_path):
        return ca_cert_path

    cli = get_cli()
    finder = getattr(cli, "find_system_ca_bundle", find_system_ca_bundle)
    system_ca = finder()
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


def handle_init_ca(args: Any) -> int:
    """Bootstrap self-signed Root CA certificates."""
    ca_cert, ca_key = generate_root_ca(output_dir=args.output_dir)
    print(f"✅ Root CA generated successfully:\n  Certificate: {ca_cert}\n  Key: {ca_key}")
    return 0
