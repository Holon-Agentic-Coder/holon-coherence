from __future__ import annotations

import ast
import io
import os
import tokenize
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        "plans",
        "executions",
        "docs",
        "holon-knowledge",
        "holon-config",
        "tmp",
        "scratch",
        "build",
        "dist",
        "venv",
        "env",
        "ENV",
        ".sandbox",
        ".holon",
        ".holon-cache",
    }
)

ALLOWED_PYTHON_COMMENT_PREFIXES = (
    "# noqa",
    "# type: ignore",
    "# pragma: no cover",
    "# pyright:",
    "# mypy:",
    "# -*-",
    "# vim:",
    "# SPDX-License-Identifier:",
)

ALLOWED_BUILD_DIRECTIVE_PREFIXES = (
    "# syntax=",
    "# escape=",
    "# check=",
    "# shellcheck ",
    "# -*-",
    "# vim:",
    "# SPDX-License-Identifier:",
)

YAML_BLOCK_SCALAR_MARKERS = frozenset({"|", "|-", "|+", ">", ">-", ">+"})


def _walk_repo_files() -> Iterator[tuple[Path, str]]:
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_DIRS)
        base = Path(dirpath)
        for filename in sorted(filenames):
            path = base / filename
            if path.is_file():
                yield path, path.relative_to(REPO_ROOT).as_posix()


def _discover_python_files() -> tuple[str, ...]:
    return tuple(sorted(rel for path, rel in _walk_repo_files() if path.suffix == ".py"))


def _is_build_or_shell_file(path: Path) -> bool:
    name = path.name
    return (
        name.startswith("Makefile")
        or name.startswith("Dockerfile")
        or path.suffix in {".mk", ".sh"}
        or name == "docker-bake.hcl"
    )


def _discover_build_and_shell_files() -> tuple[str, ...]:
    return tuple(sorted(rel for path, rel in _walk_repo_files() if _is_build_or_shell_file(path)))


def _discover_github_yaml_files() -> tuple[str, ...]:
    discovered: list[str] = []
    for subdir in (REPO_ROOT / ".github" / "workflows", REPO_ROOT / ".github" / "actions"):
        if not subdir.exists():
            continue
        for path in subdir.rglob("*"):
            if path.is_file() and path.suffix in {".yml", ".yaml"}:
                discovered.append(path.relative_to(REPO_ROOT).as_posix())
    return tuple(sorted(discovered))


def _find_python_docstring_violations(source: str, rel_path: str) -> list[str]:
    tree = ast.parse(source, filename=rel_path)
    violations: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and ast.get_docstring(node, clean=False) is not None
        ):
            lineno = getattr(node, "lineno", 1)
            violations.append(f"{rel_path}:{lineno}: docstring on {type(node).__name__}")
    return violations


def _is_allowed_python_comment(comment: str, line_no: int) -> bool:
    if line_no == 1 and comment.startswith("#!"):
        return True
    return comment.startswith(ALLOWED_PYTHON_COMMENT_PREFIXES)


def _find_python_comment_violations(source: str, rel_path: str) -> list[str]:
    violations: list[str] = []
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    for token in tokens:
        if token.type != tokenize.COMMENT:
            continue
        if not _is_allowed_python_comment(token.string, token.start[0]):
            violations.append(f"{rel_path}:{token.start[0]}: disallowed comment: {token.string}")
    return violations


def _is_allowed_build_directive(stripped: str, line_no: int) -> bool:
    if line_no == 1 and stripped.startswith("#!"):
        return True
    return stripped.startswith(ALLOWED_BUILD_DIRECTIVE_PREFIXES)


def _find_build_comment_violations(source: str, rel_path: str) -> list[str]:
    violations: list[str] = []
    for line_no, line in enumerate(source.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith(("#", "//", "/*")) and not _is_allowed_build_directive(stripped, line_no):
            violations.append(f"{rel_path}:{line_no}: disallowed comment: {stripped}")
    return violations


def _find_yaml_inline_comment(line: str) -> str | None:
    in_single = False
    in_double = False
    escaped = False
    for index, ch in enumerate(line):
        if escaped:
            escaped = False
            continue
        if ch == "\\" and in_double:
            escaped = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double and index > 0 and line[index - 1].isspace():
            return line[index:]
    return None


def _starts_yaml_block_scalar(code_part: str) -> bool:
    if ":" not in code_part:
        return False
    return code_part.rpartition(":")[2].strip() in YAML_BLOCK_SCALAR_MARKERS


def _find_yaml_comment_violations(source: str, rel_path: str) -> list[str]:
    violations: list[str] = []
    block_indent: int | None = None
    for line_no, line in enumerate(source.splitlines(), start=1):
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if block_indent is not None and stripped and indent <= block_indent:
            block_indent = None
        if stripped.startswith("#"):
            if not _is_allowed_build_directive(stripped, line_no):
                violations.append(f"{rel_path}:{line_no}: disallowed comment: {stripped}")
            continue
        if block_indent is not None or not stripped:
            continue
        inline = _find_yaml_inline_comment(line)
        if inline is not None and not _is_allowed_build_directive(inline, line_no):
            violations.append(f"{rel_path}:{line_no}: disallowed inline comment: {inline}")
        code_part = line[: len(line) - len(inline)] if inline is not None else line
        if _starts_yaml_block_scalar(code_part):
            block_indent = indent
    return violations


def test_repo_discovery_finds_expected_code_categories() -> None:
    python_files = _discover_python_files()
    build_files = _discover_build_and_shell_files()
    yaml_files = _discover_github_yaml_files()

    assert python_files
    assert "tests/test_repo_self_doc.py" in python_files

    assert build_files
    assert {"Makefile", "Dockerfile", "build_image.sh"}.issubset(set(build_files))

    assert yaml_files
    assert {
        ".github/actions/ci-timing-gate/action.yml",
        ".github/workflows/make.yml",
        ".github/workflows/test-integration.yml",
    }.issubset(set(yaml_files))


@pytest.mark.parametrize("rel_path", _discover_python_files())
def test_python_file_has_no_docstrings_or_disallowed_comments(rel_path: str) -> None:
    source = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
    violations = _find_python_docstring_violations(source, rel_path) + _find_python_comment_violations(source, rel_path)
    assert violations == [], "\n".join(violations)


@pytest.mark.parametrize("rel_path", _discover_build_and_shell_files())
def test_build_or_shell_file_has_no_disallowed_comments(rel_path: str) -> None:
    source = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
    violations = _find_build_comment_violations(source, rel_path)
    assert violations == [], "\n".join(violations)


@pytest.mark.parametrize("rel_path", _discover_github_yaml_files())
def test_github_yaml_file_has_no_disallowed_comments(rel_path: str) -> None:
    source = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
    violations = _find_yaml_comment_violations(source, rel_path)
    assert violations == [], "\n".join(violations)


def test_self_doc_classifiers_detect_violations_and_allow_pragmas() -> None:
    py_bad = '"""module doc"""\ndef f():\n    """fn doc"""\n    x = 1  # explanatory\n    #! not line 1\n    return x\n'
    assert len(_find_python_docstring_violations(py_bad, "sample.py")) == 2
    assert len(_find_python_comment_violations(py_bad, "sample.py")) == 2

    py_good = (
        "#!/usr/bin/env python3\n"
        "x = '# not a comment'  # noqa: E501\n"
        "y = 1  # type: ignore[assignment]\n"
        "z = 2  # pragma: no cover\n"
    )
    assert _find_python_docstring_violations(py_good, "ok.py") == []
    assert _find_python_comment_violations(py_good, "ok.py") == []

    build_bad = "# explanatory\n// hcl comment\n/* block */\n"
    assert len(_find_build_comment_violations(build_bad, "build.sh")) == 3

    build_good = (
        "#!/usr/bin/env bash\n"
        "# syntax=docker/dockerfile:1\n"
        "# shellcheck disable=SC2086\n"
        'if [ "$#" -gt 0 ]; then echo "${epoch#*.}" $((10#${usec:0:3})); fi\n'
    )
    assert _find_build_comment_violations(build_good, "build.sh") == []

    yaml_bad = (
        "# header comment\n"
        "permissions:\n"
        "  actions: read # inline comment\n"
        "steps:\n"
        "  - run: |\n"
        "      # shell comment\n"
        "      echo ok\n"
    )
    assert len(_find_yaml_comment_violations(yaml_bad, "wf.yml")) == 3

    yaml_good = 'name: "CI # literal"\nsteps:\n  - run: |\n      if [ "$#" -eq 0 ]; then echo "ok # literal"; fi\n'
    assert _find_yaml_comment_violations(yaml_good, "wf.yml") == []
