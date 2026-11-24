from __future__ import annotations

import ast
import io
import tokenize
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

PROVIDERS_AND_PARSERS_SELF_DOC_FILES: tuple[str, ...] = (
    "src/holon_coherence/parsers/__init__.py",
    "src/holon_coherence/parsers/sse.py",
    "src/holon_coherence/parsers/tokens.py",
    "src/holon_coherence/providers/__init__.py",
    "src/holon_coherence/providers/anthropic.py",
    "src/holon_coherence/providers/base.py",
    "src/holon_coherence/providers/gemini.py",
    "src/holon_coherence/providers/openai.py",
    "src/holon_coherence/providers/translation.py",
    "tests/providers/__init__.py",
    "tests/providers/test_anthropic.py",
    "tests/providers/test_gemini.py",
    "tests/providers/test_openai.py",
    "tests/providers/test_registry.py",
    "tests/providers/test_translation.py",
    "tests/providers/test_providers_self_doc.py",
)

ALLOWED_COMMENT_PREFIXES: tuple[str, ...] = (
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


def _is_allowed_comment(comment_text: str) -> bool:
    stripped = comment_text.strip()
    return any(stripped.startswith(prefix) for prefix in ALLOWED_COMMENT_PREFIXES)


def _find_docstring_violations(source: str, rel_path: str) -> list[str]:
    tree = ast.parse(source, filename=rel_path)
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None:
                kind = type(node).__name__
                name = getattr(node, "name", "<module>")
                lineno = getattr(node, "lineno", 1)
                violations.append(f"{rel_path}:{lineno} {kind} '{name}' contains docstring")
    return violations


def _find_disallowed_comments(source: str, rel_path: str) -> list[str]:
    violations: list[str] = []
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    for tok_type, tok_str, (start_line, _), _, _ in tokens:
        if tok_type == tokenize.COMMENT and not _is_allowed_comment(tok_str):
            violations.append(f"{rel_path}:{start_line} disallowed comment: {tok_str}")
    return violations


@pytest.mark.parametrize("rel_path", PROVIDERS_AND_PARSERS_SELF_DOC_FILES)
def test_parsers_and_providers_files_have_no_docstrings_or_explanatory_comments(rel_path: str) -> None:
    file_path = REPO_ROOT / rel_path
    assert file_path.is_file(), f"Missing expected scoped file: {rel_path}"
    source = file_path.read_text(encoding="utf-8")

    docstring_violations = _find_docstring_violations(source, rel_path)
    comment_violations = _find_disallowed_comments(source, rel_path)

    assert not docstring_violations, "Docstring violations found:\n" + "\n".join(docstring_violations)
    assert not comment_violations, "Comment violations found:\n" + "\n".join(comment_violations)


def test_self_doc_ast_and_comment_classifiers() -> None:
    sample_with_docstring_and_comments = (
        '"""Module docstring."""\n'
        "def sample(x: int) -> int:  # noqa: C901\n"
        '    """Function docstring."""\n'
        "    # explanatory comment\n"
        '    literal_with_hash = "# not a comment"\n'
        "    return len(literal_with_hash) + x\n"
    )
    doc_violations = _find_docstring_violations(sample_with_docstring_and_comments, "sample.py")
    assert len(doc_violations) == 2

    comment_violations = _find_disallowed_comments(sample_with_docstring_and_comments, "sample.py")
    assert len(comment_violations) == 1
    assert "explanatory comment" in comment_violations[0]
