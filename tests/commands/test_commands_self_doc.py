from __future__ import annotations

import ast
import io
import tokenize
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

COMMANDS_SELF_DOC_FILES: tuple[str, ...] = (
    "src/holon_coherence/commands/__init__.py",
    "src/holon_coherence/commands/ab_test.py",
    "src/holon_coherence/commands/agents.py",
    "src/holon_coherence/commands/ca.py",
    "src/holon_coherence/commands/docker_ops.py",
    "src/holon_coherence/commands/endpoints.py",
    "src/holon_coherence/commands/metrics.py",
    "src/holon_coherence/commands/runner.py",
    "src/holon_coherence/commands/start.py",
    "src/holon_coherence/commands/stop.py",
    "src/holon_coherence/commands/web_token.py",
    "tests/commands/__init__.py",
    "tests/commands/conftest.py",
    "tests/commands/test_ab_test.py",
    "tests/commands/test_agents.py",
    "tests/commands/test_ca.py",
    "tests/commands/test_docker_ops.py",
    "tests/commands/test_endpoints.py",
    "tests/commands/test_metrics.py",
    "tests/commands/test_runner.py",
    "tests/commands/test_start.py",
    "tests/commands/test_stop.py",
    "tests/commands/test_web_token.py",
    "tests/commands/test_commands_self_doc.py",
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


def _find_docstring_violations(source: str, rel_path: str) -> list[str]:
    tree = ast.parse(source, filename=rel_path)
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            docstring = ast.get_docstring(node, clean=False)
            if docstring is not None:
                lineno = getattr(node, "lineno", 1)
                node_name = getattr(node, "name", "<module>")
                violations.append(f"{rel_path}:{lineno} ({type(node).__name__} {node_name})")
    return violations


def _find_disallowed_comments(source: str, rel_path: str) -> list[str]:
    violations: list[str] = []
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            comment_text = tok.string.strip()
            if not any(comment_text.startswith(prefix) for prefix in ALLOWED_COMMENT_PREFIXES):
                violations.append(f"{rel_path}:{tok.start[0]} ({comment_text})")
    return violations


@pytest.mark.parametrize("rel_path", COMMANDS_SELF_DOC_FILES)
def test_commands_files_have_no_docstrings_or_explanatory_comments(rel_path: str) -> None:
    file_path = REPO_ROOT / rel_path
    assert file_path.is_file(), f"Scoped file missing: {rel_path}"
    source = file_path.read_text(encoding="utf-8")

    docstring_violations = _find_docstring_violations(source, rel_path)
    comment_violations = _find_disallowed_comments(source, rel_path)

    assert not docstring_violations, f"Docstrings found in {rel_path}: {docstring_violations}"
    assert not comment_violations, f"Disallowed comments found in {rel_path}: {comment_violations}"


def test_self_doc_ast_and_comment_classifiers() -> None:
    sample_with_docstring_and_comment = (
        '"""Module docstring."""\n'
        "def sample() -> int:  # noqa: C901\n"
        '    """Function docstring."""\n'
        "    value = '# hash inside string literal'\n"
        "    return len(value)  # explanatory trailing comment\n"
    )
    doc_violations = _find_docstring_violations(sample_with_docstring_and_comment, "sample.py")
    comment_violations = _find_disallowed_comments(sample_with_docstring_and_comment, "sample.py")

    assert len(doc_violations) == 2
    assert len(comment_violations) == 1
    assert "explanatory trailing comment" in comment_violations[0]
