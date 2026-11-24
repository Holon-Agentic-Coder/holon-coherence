from __future__ import annotations

import ast
import io
import tokenize
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

SCRIPTS_SELF_DOC_FILES: tuple[str, ...] = (
    "scripts/check_ci_runtime_budget.py",
    "scripts/check_module_budgets.py",
    "scripts/ci_timing_gate.py",
    "scripts/pre_commit_check.py",
    "tests/test_check_ci_runtime_budget.py",
    "tests/test_ci_timing_gate.py",
    "tests/test_complexity_baseline.py",
    "tests/test_pre_commit_check.py",
    "tests/test_repo_hygiene.py",
    "tests/test_makefile.py",
    "tests/test_scripts_self_doc.py",
)

ALLOWED_COMMENT_PREFIXES = (
    "# noqa",
    "# type: ignore",
    "# pragma: no cover",
    "# pyright:",
    "# mypy:",
    "#!",
    "# -*-",
    "# vim:",
    "# SPDX-License-Identifier:",
)

_DOCSTRING_NODE_TYPES = (
    ast.Module,
    ast.ClassDef,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
)


def _find_docstring_violations(source: str, rel_path: str) -> list[str]:
    tree = ast.parse(source, filename=rel_path)
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, _DOCSTRING_NODE_TYPES) and ast.get_docstring(node, clean=False) is not None:
            lineno = getattr(node, "lineno", 1)
            name = getattr(node, "name", "<module>")
            violations.append(f"{rel_path}:{lineno}: docstring present on {type(node).__name__} ({name})")
    return violations


def _is_allowed_comment(comment_text: str) -> bool:
    stripped = comment_text.strip()
    return any(stripped.startswith(prefix) for prefix in ALLOWED_COMMENT_PREFIXES)


def _find_disallowed_comments(source: str, rel_path: str) -> list[str]:
    violations: list[str] = []
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    for tok_type, tok_str, (lineno, _col), _end, _line in tokens:
        if tok_type == tokenize.COMMENT and not _is_allowed_comment(tok_str):
            violations.append(f"{rel_path}:{lineno}: disallowed comment: {tok_str}")
    return violations


@pytest.mark.parametrize("rel_path", SCRIPTS_SELF_DOC_FILES)
def test_scoped_file_has_no_docstrings_or_disallowed_comments(rel_path: str) -> None:
    path = REPO_ROOT / rel_path
    assert path.is_file(), f"Scoped file missing: {rel_path}"
    source = path.read_text(encoding="utf-8")
    assert _find_docstring_violations(source, rel_path) == []
    assert _find_disallowed_comments(source, rel_path) == []


def test_scripts_self_doc_scope_covers_all_scripts() -> None:
    discovered = sorted(p.relative_to(REPO_ROOT).as_posix() for p in (REPO_ROOT / "scripts").glob("*.py"))
    assert discovered
    for rel_path in discovered:
        assert rel_path in SCRIPTS_SELF_DOC_FILES
        first_line = (REPO_ROOT / rel_path).read_text(encoding="utf-8").splitlines()[0]
        assert first_line == "#!/usr/bin/env python3"


def test_docstring_and_comment_classifiers() -> None:
    sample_with_docstring = 'def f():\n    "doc"\n    return 1\n'
    assert len(_find_docstring_violations(sample_with_docstring, "sample.py")) == 1

    sample_with_comments = (
        "#!/usr/bin/env python3\n"
        "x = '#not_a_comment'\n"
        "a = 1  # noqa: F401\n"
        "b = 2  # type: ignore[assignment]\n"
        "c = 3  # pragma: no cover\n"
        "z = 4  # explanatory comment\n"
    )
    violations = _find_disallowed_comments(sample_with_comments, "sample.py")
    assert len(violations) == 1
    assert "explanatory comment" in violations[0]
