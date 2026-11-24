from __future__ import annotations

import ast
import io
import pathlib
import re
import tokenize

import pytest

REPO_ROOT = pathlib.Path(__file__).parent.parent

CONTAINER_SELF_DOC_FILES = (
    "src/holon_coherence/container/__init__.py",
    "src/holon_coherence/container/image.py",
    "src/holon_coherence/container/lifecycle.py",
    "tests/test_proxy_lifecycle.py",
    "tests/test_build_image.py",
    "tests/test_docker_integration.py",
    "tests/test_container_self_doc.py",
)

ALLOWED_PRAGMA_PATTERNS = (
    re.compile(r"^#\s*noqa(\s*:\s*[A-Z0-9,\s]+)?$"),
    re.compile(r"^#\s*type:\s*ignore(\[[a-zA-Z0-9_,\s-]+\])?$"),
    re.compile(r"^#\s*pragma:\s*(no cover|no branch)$"),
    re.compile(r"^#\s*pyright:\s*[a-zA-Z0-9_=\[\],\s-]+$"),
    re.compile(r"^#\s*mypy:\s*[a-zA-Z0-9_=\[\],\s-]+$"),
    re.compile(r"^#\s*fmt:\s*(off|on|skip)$"),
    re.compile(r"^#\s*ruff:\s*noqa(\s*:\s*[A-Z0-9,\s]+)?$"),
    re.compile(r"^#\s*SPDX-License-Identifier:\s*\S+$"),
)

ENCODING_COMMENT_PATTERN = re.compile(r"^#.*coding[:=]\s*[-\w.]+")


def _docstring_nodes(tree: ast.AST) -> list[ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _find_docstrings(source: str) -> list[tuple[int, str]]:
    tree = ast.parse(source)
    offenders: list[tuple[int, str]] = []
    for node in _docstring_nodes(tree):
        if ast.get_docstring(node, clean=False) is not None and node.body:
            offenders.append((node.body[0].lineno, type(node).__name__))
    return sorted(offenders)


def _is_allowed_comment(comment: str, *, lineno: int = 2) -> bool:
    stripped = comment.strip()
    if lineno == 1 and stripped.startswith("#!"):
        return True
    if lineno in (1, 2) and ENCODING_COMMENT_PATTERN.match(stripped):
        return True
    return any(pattern.match(stripped) for pattern in ALLOWED_PRAGMA_PATTERNS)


def _find_disallowed_comments(source: str) -> list[tuple[int, str]]:
    offenders: list[tuple[int, str]] = []
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    for tok in tokens:
        if tok.type == tokenize.COMMENT and not _is_allowed_comment(tok.string, lineno=tok.start[0]):
            offenders.append((tok.start[0], tok.string))
    return offenders


@pytest.mark.parametrize("relative_path", CONTAINER_SELF_DOC_FILES)
def test_container_files_have_no_docstrings(relative_path: str) -> None:
    content = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    assert _find_docstrings(content) == []


@pytest.mark.parametrize("relative_path", CONTAINER_SELF_DOC_FILES)
def test_container_files_have_no_explanatory_comments(relative_path: str) -> None:
    content = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    assert _find_disallowed_comments(content) == []


def test_find_docstrings_detects_module_class_and_function_docstrings() -> None:
    sample = "\n".join(
        [
            '"module doc"',
            "class Box:",
            '    "class doc"',
            "    def run(self) -> int:",
            '        "method doc"',
            "        return 1",
            "async def fetch() -> str:",
            '    "async doc"',
            '    return "ok"',
        ]
    )
    assert _find_docstrings(sample) == [
        (1, "Module"),
        (3, "ClassDef"),
        (5, "FunctionDef"),
        (8, "AsyncFunctionDef"),
    ]


@pytest.mark.parametrize(
    ("comment", "lineno", "expected"),
    [
        ("#!/usr/bin/env python3", 1, True),
        ("#!/usr/bin/env python3", 2, False),
        ("# -*- coding: utf-8 -*-", 1, True),
        ("# noqa: C901, PLR0912", 12, True),
        ("# type: ignore[arg-type]", 34, True),
        ("# pragma: no cover", 5, True),
        ("# fmt: off", 5, True),
        ("# Section banner", 5, False),
        ("# key half missing", 10, False),
    ],
)
def test_is_allowed_comment_classifier(comment: str, lineno: int, expected: bool) -> None:
    assert _is_allowed_comment(comment, lineno=lineno) is expected


def test_find_disallowed_comments_ignores_hash_in_strings_and_flags_prose() -> None:
    hash_char = chr(35)
    sample = "\n".join(
        [
            f"url = 'http://example.com/{hash_char}anchor'",
            f"x = 1  {hash_char} noqa: C901",
            f"y = 2  {hash_char} explanatory comment",
        ]
    )
    assert _find_disallowed_comments(sample) == [(3, f"{hash_char} explanatory comment")]
