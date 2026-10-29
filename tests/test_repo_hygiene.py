"""Repository hygiene: tracked files must not depend on an external harness."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Fragments are joined so that this file never matches its own patterns.
FORBIDDEN_DIRS = frozenset({"to" + "do", "." + "sub" + "agent", "." + "be" + "ans"})
PROVENANCE_PREFIXES = ("holon-knowledge/ledger/", "plans/", "executions/", "intents/")
ALLOWED_FILES = frozenset({"." + "agents/AGENTS.md"})
CONTENT_PATTERNS = (
    re.compile(r"(?<![\w.-])" + "to" + r"do/"),
    re.compile(r"(?<![\w-])\." + "sub" + r"agent/"),
    re.compile(r"(?<![\w-])\." + "be" + r"ans/"),
    re.compile(r"/(?:Users|home)/[^/\s]+/git/"),
    re.compile("holon-agentic-" + "coder-ref"),
    re.compile("Be" + "an" + r"[ _-]?\d{4}\b"),
)


def tracked_files() -> list[str]:
    """List tracked paths relative to the repository root."""
    try:
        result = subprocess.run(["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git is not available for listing tracked files")
    return [path for path in result.stdout.decode("utf-8").split("\0") if path]


def forbidden_dir(path: str) -> bool:
    """True when the first path component is an exact harness directory name."""
    return path.split("/", 1)[0] in FORBIDDEN_DIRS


def is_exempt(path: str) -> bool:
    """Provenance records and explicitly allowed files are not scanned."""
    return path.startswith(PROVENANCE_PREFIXES) or path in ALLOWED_FILES


def leaks_in(text: str) -> list[str]:
    """Return the pattern of every leak pattern found in ``text``."""
    return [pattern.pattern for pattern in CONTENT_PATTERNS if pattern.search(text)]


def read_text(path: str) -> str | None:
    """Read a tracked file as text, returning ``None`` for binary or missing files."""
    file_path = REPO_ROOT / path
    if not file_path.is_file():
        return None
    data = file_path.read_bytes()
    return None if b"\0" in data else data.decode("utf-8", errors="ignore")


def test_no_tracked_file_under_forbidden_dir() -> None:
    assert [path for path in tracked_files() if forbidden_dir(path)] == []


def test_no_tracked_file_contains_harness_leak() -> None:
    offenders = []
    for path in tracked_files():
        text = None if is_exempt(path) else read_text(path)
        offenders.extend(f"{path}:{pattern}" for pattern in leaks_in(text or ""))
    assert offenders == []


@pytest.mark.parametrize("path", [".beads/issues.jsonl", ".beads", "docs/beads.md", "src/" + "to" + "do/x.py"])
def test_similar_paths_are_allowed(path: str) -> None:
    assert not forbidden_dir(path)


@pytest.mark.parametrize("path", ["to" + "do/x.md", "." + "sub" + "agent/run.json", "." + "be" + "ans/0001.md"])
def test_forbidden_dirs_are_detected(path: str) -> None:
    assert forbidden_dir(path)


@pytest.mark.parametrize(
    "text",
    [
        "see .beads/ for issues",
        "/home/mitmproxy/.mitmproxy",
        "Beans are fine",
        "auto" + "to" + "do/x",
        ".holon/mitm_wire_logs",
    ],
)
def test_benign_text_is_allowed(text: str) -> None:
    assert leaks_in(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "logs in " + "to" + "do/mitm_wire_logs",
        "run ." + "sub" + "agent/state.json",
        "tracked in ." + "be" + "ans/0001.md",
        "file:///Us" + "ers/someone/git/project/file.py",
        "the " + "holon-agentic-" + "coder-ref" + " checkout",
        "Be" + "an 0045",
        "Be" + "an0097",
        "Be" + "an-0129",
    ],
)
def test_each_leak_pattern_is_detected(text: str) -> None:
    assert leaks_in(text) != []


def test_hygiene_file_does_not_match_itself() -> None:
    assert leaks_in(Path(__file__).read_text(encoding="utf-8")) == []
