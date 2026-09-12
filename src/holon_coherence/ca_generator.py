"""Root CA generator for the opt-in local token-reduction proxy.

This module owns exactly one job: guarantee that a *valid, trusted-shape, non-expiring* self-signed
Root CA exists on the host so the sandbox can trust the locally-owned MITM proxy.

Actual behaviour:

* ``openssl`` is probed with :func:`shutil.which` before anything is written. When it is
  missing, a :class:`RuntimeError` carrying an actionable install hint is raised.
* The certificate is generated with ``openssl req -x509`` under a 60 second timeout.
  ``subprocess.CalledProcessError`` and ``subprocess.TimeoutExpired`` are translated into
  :class:`RuntimeError` including the captured stderr.
* The generated certificate carries explicit CA extensions (``basicConstraints=critical,CA:TRUE``
  and ``keyUsage=critical,keyCertSign,cRLSign``). A CA certificate without ``keyUsage`` is refused
  as a trust anchor by several TLS stacks (BoringSSL/Node, Go, OpenSSL in strict ``purpose``
  modes), which would break the whole trust bootstrap.
* The private key is created with mode ``0o600`` (owner read/write only).
* Every returned artifact is validated with ``openssl x509 -in <path> -noout`` — both after fresh
  generation and when reusing an existing file — so a previously poisoned cache is reported instead
  of silently trusted.
* ``openssl x509 -noout`` returns 0 for an *expired* certificate, so expiry is checked separately
  with ``openssl x509 -checkend``. A cached CA that expires within the renewal window is deleted
  and regenerated instead of being reused forever.

There is deliberately no "fallback certificate" generator: unparseable PEM blobs would be cached
forever by the existence check and break every TLS client inside the sandbox with an opaque error.
Fail loudly instead.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess

logger = logging.getLogger(__name__)

_OPENSSL_TIMEOUT_SECONDS = 60

#: Lifetime of a freshly generated Root CA, in days. Bounded on purpose: together with
#: ``_CA_RENEWAL_WINDOW_SECONDS`` it guarantees a cached CA is rotated instead of being silently
#: reused forever.
_CA_VALIDITY_DAYS = 397

#: A cached CA expiring inside this window is treated as stale and regenerated (30 days).
_CA_RENEWAL_WINDOW_SECONDS = 30 * 24 * 60 * 60

_CA_CERT_FILENAME = "holon-root-ca.crt"
_CA_KEY_FILENAME = "holon-root-ca.key"

#: Explicit CA extensions. ``keyUsage`` is mandatory in practice: without it several TLS stacks
#: refuse the certificate as a trust anchor even though it is a perfectly valid CA.
_CA_EXTENSIONS = (
    "-addext",
    "basicConstraints=critical,CA:TRUE",
    "-addext",
    "keyUsage=critical,keyCertSign,cRLSign",
    "-addext",
    "subjectKeyIdentifier=hash",
)

_OPENSSL_INSTALL_HINT = (
    "Install OpenSSL and retry: macOS 'brew install openssl', Debian/Ubuntu 'apt-get install openssl'."
)


def _openssl_binary() -> str:
    """Return the absolute path of the ``openssl`` binary or raise with an install hint."""
    openssl_path = shutil.which("openssl")
    if openssl_path is None:
        raise RuntimeError(
            f"openssl binary not found on PATH but is required to manage the Holon Root CA. {_OPENSSL_INSTALL_HINT}"
        )
    return openssl_path


def _run_openssl(*args: str) -> subprocess.CompletedProcess[str]:
    """Run ``openssl`` with captured output and no implicit raising."""
    openssl_path = shutil.which("openssl") or "openssl"
    try:
        return subprocess.run(
            [openssl_path, *args],
            capture_output=True,
            text=True,
            timeout=_OPENSSL_TIMEOUT_SECONDS,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise RuntimeError(f"Could not run 'openssl {' '.join(args)}': {exc}") from exc


def _assert_valid_cert(ca_cert_path: str) -> None:
    """Assert that ``ca_cert_path`` is a parseable X.509 certificate.

    Raises:
        RuntimeError: If ``openssl`` cannot parse the artifact (or times out doing so).
    """
    result = _run_openssl("x509", "-in", ca_cert_path, "-noout")

    if result.returncode != 0:
        raise RuntimeError(
            f"Root CA certificate at {ca_cert_path} is not a parseable X.509 certificate "
            f"(openssl: {result.stderr.strip() or 'unknown error'}). "
            f"Delete {os.path.dirname(ca_cert_path)} and re-run to regenerate a fresh Root CA. {_OPENSSL_INSTALL_HINT}"
        )


def _expires_within(ca_cert_path: str, window_seconds: int) -> bool:
    """True when ``ca_cert_path`` expires within ``window_seconds``.

    ``openssl x509 -noout`` exits 0 for an expired certificate, so expiry needs its own probe:
    ``-checkend`` exits 0 when the certificate stays valid beyond the window and 1 when it does
    not. Any other exit status is an openssl-level failure and is reported, not swallowed.

    Raises:
        RuntimeError: If ``openssl`` cannot evaluate the expiry of the artifact.
    """
    result = _run_openssl("x509", "-in", ca_cert_path, "-noout", "-checkend", str(window_seconds))

    if result.returncode == 0:
        return False
    if result.returncode == 1:
        return True

    raise RuntimeError(
        f"Could not check the expiry of the Root CA certificate at {ca_cert_path} "
        f"(openssl exit {result.returncode}: {result.stderr.strip() or 'unknown error'}). "
        f"Delete {os.path.dirname(ca_cert_path)} and re-run to regenerate a fresh Root CA. {_OPENSSL_INSTALL_HINT}"
    )


def _harden_key_permissions(ca_key_path: str) -> None:
    """Restrict the CA private key to owner read/write (``0o600``)."""
    os.chmod(ca_key_path, 0o600)


def _remove_cached_ca(ca_cert_path: str, ca_key_path: str) -> None:
    """Delete a stale cached CA pair so the next generation step starts from a clean slate."""
    for path in (ca_cert_path, ca_key_path):
        try:
            os.remove(path)
        except FileNotFoundError:
            logger.debug("Stale Root CA artifact %s was already gone", path)


def _generate(openssl_path: str, ca_cert_path: str, ca_key_path: str, cert_dir: str) -> None:
    """Run ``openssl req -x509`` to create a fresh CA pair, translating failures into RuntimeError."""
    # Pre-create the key file with 0o600 so the private key is never world-readable, even briefly,
    # regardless of the caller's umask.
    key_fd = os.open(ca_key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.close(key_fd)

    try:
        subprocess.run(
            [
                openssl_path,
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-keyout",
                ca_key_path,
                "-out",
                ca_cert_path,
                "-days",
                str(_CA_VALIDITY_DAYS),
                "-nodes",
                "-subj",
                "/CN=Holon Agent Root CA/O=Holon Agentic Coder",
                *_CA_EXTENSIONS,
            ],
            capture_output=True,
            text=True,
            timeout=_OPENSSL_TIMEOUT_SECONDS,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise RuntimeError(
            f"OpenSSL failed to generate the Holon Root CA in {cert_dir} (exit {exc.returncode}): {stderr or exc}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"OpenSSL timed out after {_OPENSSL_TIMEOUT_SECONDS}s generating the Holon Root CA in {cert_dir}."
        ) from exc


def _ensure_root_ca(cert_dir: str | None = None) -> tuple[str, str, bool]:
    """Internal implementation shared by :func:`generate_root_ca` and the CLI entry point.

    Returns:
        tuple[str, str, bool]: ``(ca_cert_path, ca_key_path, generated)`` where ``generated`` is
        False only when a still-valid cached CA was reused.
    """
    openssl_path = _openssl_binary()

    if cert_dir is None:
        cert_dir = os.path.expanduser("~/.holon/certs")

    os.makedirs(cert_dir, exist_ok=True)
    ca_cert_path = os.path.join(cert_dir, _CA_CERT_FILENAME)
    ca_key_path = os.path.join(cert_dir, _CA_KEY_FILENAME)

    if os.path.exists(ca_cert_path) and os.path.exists(ca_key_path):
        _assert_valid_cert(ca_cert_path)
        if _expires_within(ca_cert_path, _CA_RENEWAL_WINDOW_SECONDS):
            logger.warning(
                "Cached Root CA at %s expires within %s days; regenerating it instead of reusing a stale trust anchor.",
                ca_cert_path,
                _CA_RENEWAL_WINDOW_SECONDS // 86400,
            )
            _remove_cached_ca(ca_cert_path, ca_key_path)
        else:
            logger.info("Reusing existing Root CA certificate at %s", ca_cert_path)
            _harden_key_permissions(ca_key_path)
            return ca_cert_path, ca_key_path, False

    logger.info("Generating self-signed Root CA certificate at %s", cert_dir)
    _generate(openssl_path, ca_cert_path, ca_key_path, cert_dir)

    _harden_key_permissions(ca_key_path)
    _assert_valid_cert(ca_cert_path)

    return ca_cert_path, ca_key_path, True


def generate_root_ca(cert_dir: str | None = None) -> tuple[str, str]:
    """Ensure a valid, properly extended, non-expiring self-signed Root CA exists.

    Args:
        cert_dir: Directory where certs should be stored. Defaults to ``~/.holon/certs``.

    Returns:
        tuple[str, str]: Paths to ``(ca_cert_path, ca_key_path)``. The certificate is guaranteed to
        be parseable by ``openssl x509``, to carry CA ``basicConstraints``/``keyUsage`` extensions,
        to stay valid for more than 30 days, and the key is mode ``0o600``.

    Raises:
        RuntimeError: If ``openssl`` is unavailable, generation fails or times out, or an existing
            cached certificate is not a parseable X.509 artifact.
    """
    ca_cert_path, ca_key_path, _ = _ensure_root_ca(cert_dir)
    return ca_cert_path, ca_key_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cert, key, was_generated = _ensure_root_ca()
    verdict = "Generated new Root CA" if was_generated else "Reused existing Root CA"
    print(f"{verdict}:\n  Cert: {cert}\n  Key:  {key}")
