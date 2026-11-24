from __future__ import annotations

import contextlib
import logging
import os
import shutil
import subprocess

logger = logging.getLogger(__name__)

_OPENSSL_TIMEOUT_SECONDS = 60
_CA_VALIDITY_DAYS = 397
_CA_RENEWAL_WINDOW_SECONDS = 30 * 24 * 60 * 60
_CA_CERT_FILENAME = "holon-root-ca.crt"
_CA_KEY_FILENAME = "holon-root-ca.key"
_OWNER_ONLY_KEY_FILE_MODE = 0o600
_OWNER_ONLY_DIR_MODE = 0o700

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
    openssl_path = shutil.which("openssl")
    if openssl_path is None:
        raise RuntimeError(
            f"openssl binary not found on PATH but is required to manage the Holon Root CA. {_OPENSSL_INSTALL_HINT}"
        )
    return openssl_path


def _run_openssl(*args: str) -> subprocess.CompletedProcess[str]:
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
    result = _run_openssl("x509", "-in", ca_cert_path, "-noout")

    if result.returncode != 0:
        raise RuntimeError(
            f"Root CA certificate at {ca_cert_path} is not a parseable X.509 certificate "
            f"(openssl: {result.stderr.strip() or 'unknown error'}). "
            f"Delete {os.path.dirname(ca_cert_path)} and re-run to regenerate a fresh Root CA. {_OPENSSL_INSTALL_HINT}"
        )


def _expires_within(ca_cert_path: str, window_seconds: int) -> bool:
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
    os.chmod(ca_key_path, _OWNER_ONLY_KEY_FILE_MODE)


def _precreate_owner_only_key_file(ca_key_path: str) -> None:
    key_fd = os.open(ca_key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _OWNER_ONLY_KEY_FILE_MODE)
    os.close(key_fd)


def _remove_cached_ca(ca_cert_path: str, ca_key_path: str) -> None:
    cert_dir = os.path.dirname(ca_cert_path)
    mitm_ca_cert = os.path.join(cert_dir, "mitmproxy-ca-cert.pem")
    mitm_ca_pem = os.path.join(cert_dir, "mitmproxy-ca.pem")
    for path in (ca_cert_path, ca_key_path, mitm_ca_cert, mitm_ca_pem):
        try:
            os.remove(path)
        except FileNotFoundError:
            logger.debug("Stale Root CA artifact %s was already gone", path)


def _generate(openssl_path: str, ca_cert_path: str, ca_key_path: str, cert_dir: str) -> None:
    _precreate_owner_only_key_file(ca_key_path)

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


def _sync_mitmproxy_ca(ca_cert_path: str, ca_key_path: str, cert_dir: str) -> None:
    mitm_ca_cert = os.path.join(cert_dir, "mitmproxy-ca-cert.pem")
    mitm_ca_pem = os.path.join(cert_dir, "mitmproxy-ca.pem")

    with contextlib.suppress(OSError):
        shutil.copyfile(ca_cert_path, mitm_ca_cert)

    with contextlib.suppress(OSError):
        with open(ca_key_path, encoding="utf-8") as kf, open(ca_cert_path, encoding="utf-8") as cf:
            combined = f"{kf.read().strip()}\n{cf.read().strip()}\n"
        pem_fd = os.open(mitm_ca_pem, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _OWNER_ONLY_KEY_FILE_MODE)
        with os.fdopen(pem_fd, "w", encoding="utf-8") as pf:
            pf.write(combined)
        os.chmod(mitm_ca_pem, _OWNER_ONLY_KEY_FILE_MODE)


def _ensure_root_ca(cert_dir: str | None = None) -> tuple[str, str, bool]:
    openssl_path = _openssl_binary()

    if cert_dir is None:
        cert_dir = os.path.expanduser("~/.holon/certs")

    os.makedirs(cert_dir, mode=_OWNER_ONLY_DIR_MODE, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(cert_dir, _OWNER_ONLY_DIR_MODE)
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
            _sync_mitmproxy_ca(ca_cert_path, ca_key_path, cert_dir)
            return ca_cert_path, ca_key_path, False

    logger.info("Generating self-signed Root CA certificate at %s", cert_dir)
    _generate(openssl_path, ca_cert_path, ca_key_path, cert_dir)

    _harden_key_permissions(ca_key_path)
    _assert_valid_cert(ca_cert_path)
    _sync_mitmproxy_ca(ca_cert_path, ca_key_path, cert_dir)

    return ca_cert_path, ca_key_path, True


def generate_root_ca(cert_dir: str | None = None, output_dir: str | None = None) -> tuple[str, str]:
    target_dir = cert_dir or output_dir
    ca_cert_path, ca_key_path, _ = _ensure_root_ca(target_dir)
    return ca_cert_path, ca_key_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cert, key, was_generated = _ensure_root_ca()
    verdict = "Generated new Root CA" if was_generated else "Reused existing Root CA"
    print(f"{verdict}:\n  Cert: {cert}\n  Key:  {key}")
