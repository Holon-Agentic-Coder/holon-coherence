from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE_PATH = REPO_ROOT / "Dockerfile"
DOCKERIGNORE_PATH = REPO_ROOT / ".dockerignore"

EXPECTED_BASE_IMAGE = (
    "mitmproxy/mitmproxy:12.2.3@sha256:00b77b5d8804c8ad18cb6caefbf9d5849e895e8986c5ce011f4ae30f4385962f"
)
EXPECTED_UV_IMAGE = "ghcr.io/astral-sh/uv:0.9.5@sha256:f459f6f73a8c4ef5d69f4e6fbbdb8af751d6fa40ec34b39a1ab469acd6e289b7"
DIGEST_PATTERN = re.compile(r"@sha256:[0-9a-f]{64}$")

REQUIRED_DOCKERIGNORE_ENTRIES = (
    ".git",
    ".venv",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "*.pyc",
    "*.pyo",
    "dist",
    "build",
    "*.egg-info",
    ".holon",
    "tests",
    "docs",
    "plans",
    "executions",
    "holon-knowledge",
    ".github",
    "scripts",
    "config",
    "Makefile",
    "environment.yml",
    "*.md",
    "!README.md",
)


def _read_dockerfile() -> str:
    return DOCKERFILE_PATH.read_text(encoding="utf-8")


def _read_dockerignore_lines() -> list[str]:
    return [line.strip() for line in DOCKERIGNORE_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]


def _unfold_dockerfile_lines(text: str) -> list[str]:
    unfolded: list[str] = []
    buffer: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.endswith("\\"):
            buffer.append(stripped[:-1].strip())
            continue
        buffer.append(stripped)
        unfolded.append(" ".join(part for part in buffer if part))
        buffer.clear()
    if buffer:
        unfolded.append(" ".join(part for part in buffer if part))
    return unfolded


def test_dockerfile_pins_multi_arch_base_and_uv_digests() -> None:
    lines = _unfold_dockerfile_lines(_read_dockerfile())

    assert f"FROM {EXPECTED_BASE_IMAGE}" in lines
    assert f"COPY --from={EXPECTED_UV_IMAGE} /uv /usr/local/bin/uv" in lines

    from_lines = [line for line in lines if line.startswith("FROM ")]
    assert from_lines
    for line in from_lines:
        image_ref = line.split()[1]
        assert DIGEST_PATTERN.search(image_ref), f"Unpinned FROM image: {line}"

    copy_from_refs = re.findall(r"COPY\s+--from=(\S+)", "\n".join(lines))
    assert copy_from_refs
    for ref in copy_from_refs:
        assert DIGEST_PATTERN.search(ref), f"Unpinned COPY --from image: {ref}"


def test_dockerfile_installs_via_frozen_uv_lock_without_pip() -> None:
    text = _read_dockerfile()
    lines = _unfold_dockerfile_lines(text)

    assert "COPY pyproject.toml uv.lock README.md /app/" in lines
    assert "COPY src/ /app/src/" in lines

    run_lines = [line for line in lines if line.startswith("RUN ")]
    combined_runs = "\n".join(run_lines)
    assert "uv export --frozen --no-dev --no-editable --no-hashes --no-header -o /tmp/requirements.txt" in combined_runs
    assert "uv pip install --system --no-cache -r /tmp/requirements.txt" in combined_runs
    assert "rm -f /tmp/requirements.txt" in combined_runs
    assert "uv pip install --system --no-cache --no-deps ." in combined_runs

    assert re.search(r"(?<!uv )\bpip3?\s+install\b", text) is None
    assert re.search(r"\bpython3?\s+-m\s+pip\b", text) is None


def test_dockerfile_defines_tcp_socket_healthcheck() -> None:
    lines = _unfold_dockerfile_lines(_read_dockerfile())
    healthcheck_lines = [line for line in lines if line.startswith("HEALTHCHECK ")]
    assert len(healthcheck_lines) == 1

    healthcheck = healthcheck_lines[0]
    for token in (
        "--interval=30s",
        "--timeout=5s",
        "--start-period=10s",
        "--retries=3",
        "python3",
        "socket",
        "127.0.0.1",
        "${PORT:-8080}",
    ):
        assert token in healthcheck, f"Missing {token!r} in HEALTHCHECK: {healthcheck}"


def test_dockerignore_excludes_non_runtime_trees_and_keeps_readme() -> None:
    lines = _read_dockerignore_lines()
    for entry in REQUIRED_DOCKERIGNORE_ENTRIES:
        assert entry in lines, f"Missing .dockerignore entry: {entry}"

    assert lines.index("!README.md") > lines.index("*.md")

    for required_runtime_path in ("pyproject.toml", "uv.lock", "src", "src/"):
        assert required_runtime_path not in lines
