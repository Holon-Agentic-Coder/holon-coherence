from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src" / "holon_coherence"

BROAD_EXCEPT_CAPS: dict[str, int] = {
    "src/holon_coherence/commands/ab_test.py": 2,
    "src/holon_coherence/commands/metrics.py": 1,
    "src/holon_coherence/commands/runner.py": 1,
    "src/holon_coherence/hybrid_cache.py": 3,
    "src/holon_coherence/metrics/aggregation.py": 2,
    "src/holon_coherence/payload_cleaner.py": 1,
    "src/holon_coherence/providers/anthropic.py": 1,
    "src/holon_coherence/providers/gemini.py": 1,
    "src/holon_coherence/providers/openai.py": 1,
    "src/holon_coherence/providers/translation.py": 3,
    "src/holon_coherence/proxy/addon.py": 3,
    "src/holon_coherence/proxy/steps/base.py": 1,
    "src/holon_coherence/proxy/steps/identify_provider.py": 1,
    "src/holon_coherence/proxy/steps/load_exchange.py": 1,
    "src/holon_coherence/proxy/steps/record_metrics.py": 1,
    "src/holon_coherence/proxy/steps/sse_tap.py": 1,
    "src/holon_coherence/proxy/steps/wire_record.py": 1,
    "src/holon_coherence/proxy/wire_log.py": 3,
    "src/holon_coherence/rag_indexer.py": 2,
}


def _is_broad_except_handler(node: ast.ExceptHandler) -> bool:
    if node.type is None:
        return True
    if isinstance(node.type, ast.Name):
        return node.type.id in {"Exception", "BaseException"}
    if isinstance(node.type, ast.Tuple):
        return any(isinstance(elt, ast.Name) and elt.id in {"Exception", "BaseException"} for elt in node.type.elts)
    return False


def _is_silent_pass_handler(node: ast.ExceptHandler) -> bool:
    if len(node.body) != 1:
        return False
    stmt = node.body[0]
    if isinstance(stmt, ast.Pass):
        return True
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and stmt.value.value is Ellipsis


def _scan_source_broad_excepts(source: str) -> tuple[list[int], list[int]]:
    tree = ast.parse(source)
    broad_lines: list[int] = []
    silent_pass_lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and _is_broad_except_handler(node):
            broad_lines.append(node.lineno)
            if _is_silent_pass_handler(node):
                silent_pass_lines.append(node.lineno)
    return sorted(broad_lines), sorted(silent_pass_lines)


def _find_ratchet_violations(module_counts: dict[str, list[int]], caps: dict[str, int]) -> list[str]:
    violations: list[str] = []
    for rel_path, lines in sorted(module_counts.items()):
        cap = caps.get(rel_path, 0)
        if len(lines) > cap:
            violations.append(f"{rel_path}: found {len(lines)} broad except handler(s) at lines {lines}, cap is {cap}")
    return violations


def test_no_silent_broad_except_pass_in_src() -> None:
    violations: list[str] = []
    for py_file in sorted(SRC_ROOT.rglob("*.py")):
        rel_path = py_file.relative_to(REPO_ROOT).as_posix()
        _, silent_lines = _scan_source_broad_excepts(py_file.read_text(encoding="utf-8"))
        if silent_lines:
            violations.append(f"{rel_path}: silent broad except pass at lines {silent_lines}")
    assert violations == []


def test_broad_except_counts_within_module_caps() -> None:
    missing = [rel_path for rel_path in sorted(BROAD_EXCEPT_CAPS) if not (REPO_ROOT / rel_path).is_file()]
    assert missing == []

    module_counts: dict[str, list[int]] = {}
    for py_file in sorted(SRC_ROOT.rglob("*.py")):
        rel_path = py_file.relative_to(REPO_ROOT).as_posix()
        broad_lines, _ = _scan_source_broad_excepts(py_file.read_text(encoding="utf-8"))
        module_counts[rel_path] = broad_lines

    assert _find_ratchet_violations(module_counts, BROAD_EXCEPT_CAPS) == []


def test_ratchet_rejects_unratcheted_broad_except_and_bare_except() -> None:
    broad_src = "try:\n    x = 1\nexcept Exception as exc:\n    print(exc)\n"
    bare_src = "try:\n    x = 1\nexcept:\n    print('err')\n"

    broad_lines, _ = _scan_source_broad_excepts(broad_src)
    bare_lines, _ = _scan_source_broad_excepts(bare_src)
    assert broad_lines == [3]
    assert bare_lines == [3]

    violations = _find_ratchet_violations(
        {
            "src/holon_coherence/new_mod.py": broad_lines,
            "src/holon_coherence/bare_mod.py": bare_lines,
            "src/holon_coherence/capped_mod.py": [10, 20],
        },
        {"src/holon_coherence/capped_mod.py": 1},
    )
    assert len(violations) == 3
    assert any("new_mod.py" in v for v in violations)
    assert any("bare_mod.py" in v for v in violations)
    assert any("capped_mod.py" in v for v in violations)


def test_ratchet_allows_equal_or_lower_broad_except_counts() -> None:
    violations = _find_ratchet_violations(
        {
            "src/holon_coherence/equal_mod.py": [10, 20],
            "src/holon_coherence/lower_mod.py": [15],
            "src/holon_coherence/zero_mod.py": [],
        },
        {
            "src/holon_coherence/equal_mod.py": 2,
            "src/holon_coherence/lower_mod.py": 3,
            "src/holon_coherence/zero_mod.py": 1,
        },
    )
    assert violations == []


def test_ratchet_detects_silent_pass_and_ignores_narrowed_except() -> None:
    silent_src = "try:\n    x = 1\nexcept Exception:\n    pass\n"
    ellipsis_src = "try:\n    x = 1\nexcept:\n    ...\n"
    narrowed_src = "try:\n    x = 1\nexcept (OSError, ValueError):\n    pass\n"

    assert _scan_source_broad_excepts(silent_src) == ([3], [3])
    assert _scan_source_broad_excepts(ellipsis_src) == ([3], [3])
    assert _scan_source_broad_excepts(narrowed_src) == ([], [])
