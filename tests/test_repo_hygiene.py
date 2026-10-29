"""Repository hygiene: tracked files must not depend on an external harness."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Fragments are joined so that this file never matches its own patterns.
FORBIDDEN_DIRS = frozenset({"to" + "do", "." + "sub" + "agent", "." + "be" + "ans"})
# Dotted harness directories are never legitimate at any depth; the bare name is only rejected at the root.
NESTED_FORBIDDEN_DIRS = frozenset({"." + "sub" + "agent", "." + "be" + "ans"})
PROVENANCE_PREFIXES = ("holon-knowledge/ledger/", "plans/", "executions/", "intents/")
# Calls nest up to five levels inside a path-call argument, the repository's own deepest idiom
# (dirname(dirname(dirname(dirname(abspath(f)))))).
CALL_NESTING = 5


def call_arguments(depth: int) -> str:
    """Regex for call-argument text whose parenthesised sub-calls nest at most ``depth`` levels."""
    inner = r"[^()]*"
    for _ in range(depth):
        inner = r"(?:[^()]|\(" + inner + r"\))*"
    return inner


# Calls that build a path from their arguments: a join() (qualified or imported bare), os.sep.join() or a
# separator-literal join ("/".join, "\\".join), joinpath() and Path(); a plain str.join() (any other join preceded
# by a dot, os.pathsep.join included) is not one.
PATH_CALL = r"""(?:(?<![\w.])join|path\.join|(?:os|path)\.sep\.join|["'](?:/|\\{1,2})["']\.join|joinpath|Path)\("""
# Prefixes an unquoted path starts from: a parent, current or home directory, a shell variable or parameter expansion
# (${R}, ${R:-..}, ${R%/}), or a command substitution ($(cmd) or `cmd`), optionally quoted before the separator
# ("${R}"/x, "$R"/x, '$(cmd)'/x).
PATH_ORIGIN = r"""(?:(?<![\w.])\.{1,2}|~|\$\w+|\$\{[^{}\n]*\}|\$\([^()\n]*\)|`[^`\n]*`)["']?(?:/|\\{1,2})"""
CONTENT_PATTERNS = (
    re.compile(r"(?<![\w.-])" + "to" + r"do/"),
    # A quoted bare name only counts in a path context: any argument of a PATH_CALL, including after arguments that
    # are themselves calls (up to CALL_NESTING levels) and inside a tuple or list (join(("x", s)), join(*["x", s])), or
    # either side of a "/" operator, string prefixes (f"", r"", rb"") included. A tuple opener must not follow a name or
    # closing bracket, so a literal passed to a call inside the arguments (join(root, d.get(s))) is not a path segment.
    re.compile(
        "(?:"
        + PATH_CALL
        + call_arguments(CALL_NESTING)
        + r"""(?:\*?\s*(?<![\w)\]])\([^()]*)?|/\s*)[rRbBuUfF]{0,2}["']"""
        + "to"
        + r"""do["']|["']"""
        + "to"
        + r"""do["']\s*/"""
    ),
    # A quoted path whose last segment is the bare name ("../x", f"{root}/x", "~/x").
    re.compile(r"""["'`][^"'`\s]*/""" + "to" + r"""do["'`]"""),
    # An unquoted path ending in the bare name (Makefile, shell, YAML, Windows separators): "../x", "~/x", "$(R)/x".
    # A longer name ("xs", "x-list") or a file ("x.md") is not the directory; trailing punctuation still counts.
    re.compile(PATH_ORIGIN + "to" + r"do(?![\w-]|\.\w)"),
    re.compile(r"(?<![\w-])\." + "sub" + r"agent/"),
    re.compile(r"(?<![\w-])\." + "be" + r"ans/"),
    re.compile(r"/(?:Users|home)/[^/\s]+/git/"),
    re.compile("holon-agentic-" + "coder-ref"),
    # Any-case ids need a non-letter before them; a capitalised id may also be joined onto a name (TestFooId0001 style).
    re.compile(r"(?:(?i:(?<![a-z])" + "be" + r"ans?)|" + "Be" + r"ans?)[ _:#-]*\d{4}(?!\d)"),
)


def tracked_files() -> list[str]:
    """List tracked paths relative to the repository root; skip only outside a git checkout."""
    if not (REPO_ROOT / ".git").exists():
        pytest.skip("not a git checkout, so there are no tracked files to list")
    result = subprocess.run(["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, check=True)
    return [path for path in result.stdout.decode("utf-8").split("\0") if path]


def forbidden_dir(path: str) -> bool:
    """True when the root component, or any dotted component, is an exact harness directory name."""
    parts = path.split("/")
    return parts[0] in FORBIDDEN_DIRS or any(part in NESTED_FORBIDDEN_DIRS for part in parts)


def is_exempt(path: str) -> bool:
    """Only provenance records are not scanned; every other tracked file, docs and configs included, is."""
    return path.startswith(PROVENANCE_PREFIXES)


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


@pytest.mark.parametrize(
    "path",
    [
        ".beads/issues.jsonl",
        ".beads",
        "docs/beads.md",
        "docs/.beads/x.md",
        "src/" + "to" + "do/x.py",
        "." + "agents/AGENTS.md",
    ],
)
def test_similar_paths_are_allowed(path: str) -> None:
    assert not forbidden_dir(path)


@pytest.mark.parametrize(
    "path",
    [
        "to" + "do/x.md",
        "." + "sub" + "agent/run.json",
        "." + "be" + "ans/0001.md",
        "docs/." + "be" + "ans/x.md",
        "apps/." + "sub" + "agent/state.json",
    ],
)
def test_forbidden_dirs_are_detected(path: str) -> None:
    assert forbidden_dir(path)


@pytest.mark.parametrize(
    "text",
    [
        "see .beads/ for issues",
        "/home/mitmproxy/.mitmproxy",
        "Beans are fine",
        "a bean counter",
        "2048 beans in 1024 jars",
        "the " + "to" + "do list",
        "TO" + "DO: tidy",
        "auto" + "to" + "do/x",
        ".holon/mitm_wire_logs",
        "jelly" + "be" + "an 2048",
        'status == "' + "to" + 'do"',
        'choices=["done", "' + "to" + 'do"]',
        "{'state': '" + "to" + "do'}",
        'Path("x").name == "' + "to" + 'do"',
        'str(Path("x")) == "' + "to" + 'do"',
        '", ".join([str(x), "' + "to" + 'do"])',
        '", ".join(["done", "' + "to" + 'do"])',
        'help="one of: " + "|".join(("done", "' + "to" + 'do"))',
        'sep.join(["done", "' + "to" + 'do"])',
        '"/api/' + "to" + 'dos"',
        '"/' + "to" + 'do-list"',
        "'x.joinpath'",
        'os.pathsep.join([root, "' + "to" + 'do"])',
        "DIR := ../" + "to" + "dos",
        "cd ../" + "to" + "do-list && ls",
        "see ../" + "to" + "do.md",
        "https://example.com/" + "to" + "do",
        "a/" + "to" + "do b",
        "Path(x).name in ('done', '" + "to" + "do')",
        'os.path.join(root, names.get("' + "to" + 'do"))',
        'Path(out, MAP.get("' + "to" + 'do", "x"))',
        'Path(root, labels.index("' + "to" + 'do"))',
        'os.path.join(d, fmt("' + "to" + 'do"))',
        '"${REPO_ROOT}"/' + "to" + "dos",
        '"$HOME"/' + "to" + "do.md",
        "'$(pwd)'/" + "to" + "do-list",
        '"${REPO_ROOT}/docs"/' + "to" + "do-notes",
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
        "(Be" + "ans 0043 & 0051)",
        "Be" + "ans 0167/0168",
        "be" + "an 0045",
        "BE" + "AN-0045",
        "Be" + "an #0045",
        "Be" + "an: 0045",
        "os.path.join('" + "to" + "do', 'mitm_wire_logs')",
        'Path("' + "to" + 'do") / "x"',
        'os.path.join(root, "' + "to" + 'do")',
        'join(root, "' + "to" + 'do")',
        'from os.path import join; join("' + "to" + 'do", "x")',
        'posixpath.join(root, "' + "to" + 'do")',
        'PurePath(root, "' + "to" + 'do")',
        'Path("' + "to" + 'do", "x")',
        'Path("x", "' + "to" + 'do")',
        "os.path.join(get_root(), '" + "to" + "do')",
        'Path(str(root), "' + "to" + 'do")',
        'os.path.join(a, f(b, c), "' + "to" + 'do", "x")',
        'join(Path.home(), "' + "to" + 'do")',
        'os.path.join(os.path.dirname(os.path.abspath(__file__)), "' + "to" + 'do")',
        'os.path.join(str(get_root()), "' + "to" + 'do")',
        'Path(str(Path.home()), "' + "to" + 'do")',
        'root / "' + "to" + 'do"',
        '"' + "to" + 'do" / "cache"',
        'Path.home().joinpath("' + "to" + 'do")',
        "root.joinpath('" + "to" + "do', 'x')",
        'os.getenv("D", "../' + "to" + 'do")',
        'f"{root}/' + "to" + 'do"',
        '"~/' + "to" + 'do"',
        "`../" + "to" + "do`",
        'root / f"' + "to" + 'do"',
        'root / r"' + "to" + 'do"',
        'Path.home() / rb"' + "to" + 'do"',
        'root / sub / "' + "to" + 'do"',
        'os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "' + "to" + 'do")',
        "os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), '"
        + "to"
        + "do')",
        'os.sep.join([root, "' + "to" + 'do"])',
        '"/".join([root, "' + "to" + 'do"])',
        "'/'.join((root, '" + "to" + "do'))",
        '"/".join(("done", "' + "to" + 'do"))',
        'os.path.join(*["x", "' + "to" + 'do"])',
        'Path(*("x", "' + "to" + 'do"))',
        'join(("x", "' + "to" + 'do"))',
        'os.path.join(a,\n  ("' + "to" + 'do")',
        "DIR := ../" + "to" + "do",
        "cd ../../" + "to" + "do && ls",
        "cd ~/" + "to" + "do",
        "see ../" + "to" + "do.",
        "$(REPO_ROOT)/" + "to" + "do",
        "${ROOT}/" + "to" + "do",
        "${ROOT:-..}/" + "to" + "do",
        "${ROOT%/}/" + "to" + "do",
        "`pwd`/" + "to" + "do",
        "cd `git rev-parse --show-toplevel`/" + "to" + "do",
        "$(git rev-parse --show-toplevel)/" + "to" + "do",
        "..\\" + "to" + "do\\x.md",
        '"${REPO_ROOT}"/' + "to" + "do",
        '"$HOME"/' + "to" + "do",
        "'$(pwd)'/" + "to" + "do",
        'cd "`pwd`"/' + "to" + "do",
        "TestFoo" + "Be" + "an0097",
        "fix_" + "be" + "an_0097",
    ],
)
def test_each_leak_pattern_is_detected(text: str) -> None:
    assert leaks_in(text) != []


@pytest.mark.parametrize(
    "path",
    [
        "holon-knowledge/ledger/intents.jsonl",
        "plans/P-1.md",
        "executions/E-1.md",
        "intents/I-1.json",
    ],
)
def test_provenance_files_are_exempt(path: str) -> None:
    assert is_exempt(path)


@pytest.mark.parametrize(
    "path",
    [
        "docs/plans/x.md",
        "src/executions/x.py",
        "plansx/a.md",
        "holon-knowledge/notes.md",
        "docs/holon-knowledge/ledger/x.jsonl",
        "." + "agents/other.md",
        "." + "agents/AGENTS.md",
    ],
)
def test_exemption_is_root_anchored_and_exact(path: str) -> None:
    assert not is_exempt(path)


def test_hygiene_file_does_not_match_itself() -> None:
    assert leaks_in(Path(__file__).read_text(encoding="utf-8")) == []
