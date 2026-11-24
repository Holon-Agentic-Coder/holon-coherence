from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

import pytest

from holon_coherence.proxy.dashboard import render_dashboard_html

REPO_ROOT = Path(__file__).resolve().parents[2]

PROXY_SELF_DOC_FILES: tuple[str, ...] = (
    "src/holon_coherence/proxy/__init__.py",
    "src/holon_coherence/proxy/addon.py",
    "src/holon_coherence/proxy/dashboard.py",
    "src/holon_coherence/proxy/metrics.py",
    "src/holon_coherence/proxy/normalise/__init__.py",
    "src/holon_coherence/proxy/normalise/anthropic.py",
    "src/holon_coherence/proxy/routing.py",
    "src/holon_coherence/proxy/scrubbing.py",
    "src/holon_coherence/proxy/steps/__init__.py",
    "src/holon_coherence/proxy/steps/_compat.py",
    "src/holon_coherence/proxy/steps/_headers.py",
    "src/holon_coherence/proxy/steps/apply_cache.py",
    "src/holon_coherence/proxy/steps/base.py",
    "src/holon_coherence/proxy/steps/clean_payload.py",
    "src/holon_coherence/proxy/steps/identify_provider.py",
    "src/holon_coherence/proxy/steps/load_exchange.py",
    "src/holon_coherence/proxy/steps/record_metrics.py",
    "src/holon_coherence/proxy/steps/route_local_target.py",
    "src/holon_coherence/proxy/steps/serve_dashboard.py",
    "src/holon_coherence/proxy/steps/sse_tap.py",
    "src/holon_coherence/proxy/steps/wire_record.py",
    "src/holon_coherence/proxy/timing.py",
    "src/holon_coherence/proxy/translation/__init__.py",
    "src/holon_coherence/proxy/translation/gemini_openai.py",
    "src/holon_coherence/proxy/wire_log.py",
    "tests/proxy/__init__.py",
    "tests/proxy/test_addon_pipeline_parity.py",
    "tests/proxy/test_dashboard.py",
    "tests/proxy/test_metrics.py",
    "tests/proxy/test_normalise.py",
    "tests/proxy/test_routing.py",
    "tests/proxy/test_scrubbing.py",
    "tests/proxy/test_steps.py",
    "tests/proxy/test_timing.py",
    "tests/proxy/test_translation.py",
    "tests/proxy/test_wire_log.py",
    "tests/proxy/test_proxy_self_doc.py",
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


@pytest.mark.parametrize("rel_path", PROXY_SELF_DOC_FILES)
def test_proxy_file_has_no_docstrings_or_disallowed_comments(rel_path: str) -> None:
    path = REPO_ROOT / rel_path
    assert path.is_file(), f"Scoped file missing: {rel_path}"
    source = path.read_text(encoding="utf-8")
    assert _find_docstring_violations(source, rel_path) == []
    assert _find_disallowed_comments(source, rel_path) == []


def test_proxy_self_doc_scope_covers_all_proxy_python_files() -> None:
    discovered = sorted(
        str(p.relative_to(REPO_ROOT))
        for root in ("src/holon_coherence/proxy", "tests/proxy")
        for p in (REPO_ROOT / root).rglob("*.py")
    )
    assert sorted(PROXY_SELF_DOC_FILES) == discovered


def test_dashboard_html_has_no_inline_comments() -> None:
    html = render_dashboard_html()
    assert "<!--" not in html
    assert "-->" not in html
    assert "/*" not in html
    assert "*/" not in html
    assert re.search(r"(?m)^\s*//", html) is None


def test_docstring_and_comment_classifiers() -> None:
    sample_with_docstring = 'def f():\n    "doc"\n    return 1\n'
    assert len(_find_docstring_violations(sample_with_docstring, "sample.py")) == 1

    sample_with_comments = "x = '#not_a_comment'\ny = 1  # noqa: F401\nz = 2  # explanatory comment\n"
    violations = _find_disallowed_comments(sample_with_comments, "sample.py")
    assert len(violations) == 1
    assert "explanatory comment" in violations[0]
