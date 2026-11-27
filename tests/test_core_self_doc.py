from __future__ import annotations

import ast
import io
import tokenize
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

CORE_SELF_DOC_FILES: tuple[str, ...] = (
    "src/holon_coherence/__init__.py",
    "src/holon_coherence/ca_generator.py",
    "src/holon_coherence/cli.py",
    "src/holon_coherence/host_local.py",
    "src/holon_coherence/hybrid_cache.py",
    "src/holon_coherence/metrics_math.py",
    "src/holon_coherence/mitm_addon.py",
    "src/holon_coherence/openbrain_memory.py",
    "src/holon_coherence/payload_cleaner.py",
    "src/holon_coherence/rag_indexer.py",
    "src/holon_coherence/reduction_passes.py",
    "src/holon_coherence/ringer_orchestrator.py",
    "src/holon_coherence/settings.py",
    "tests/test_core_self_doc.py",
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


@pytest.mark.parametrize("rel_path", CORE_SELF_DOC_FILES)
def test_core_file_has_no_docstrings_or_disallowed_comments(rel_path: str) -> None:
    path = REPO_ROOT / rel_path
    assert path.is_file(), f"Scoped file missing: {rel_path}"
    source = path.read_text(encoding="utf-8")
    assert _find_docstring_violations(source, rel_path) == []
    assert _find_disallowed_comments(source, rel_path) == []


def test_core_self_doc_scope_covers_all_top_level_core_modules() -> None:
    discovered = sorted(
        [
            *(p.relative_to(REPO_ROOT).as_posix() for p in (REPO_ROOT / "src/holon_coherence").glob("*.py")),
            "tests/test_core_self_doc.py",
        ]
    )
    assert sorted(CORE_SELF_DOC_FILES) == discovered


def test_docstring_and_comment_classifiers() -> None:
    sample_with_docstring = 'def f():\n    "doc"\n    return 1\n'
    assert len(_find_docstring_violations(sample_with_docstring, "sample.py")) == 1

    sample_with_comments = (
        "#!/usr/bin/env python3\n"
        "# -*- coding: utf-8 -*-\n"
        "x = '#not_a_comment'\n"
        "y = 1  # noqa: F401\n"
        "a = 2  # type: ignore[assignment]\n"
        "b = 3  # pragma: no cover\n"
        "z = 4  # explanatory comment\n"
    )
    violations = _find_disallowed_comments(sample_with_comments, "sample.py")
    assert len(violations) == 1
    assert "explanatory comment" in violations[0]
