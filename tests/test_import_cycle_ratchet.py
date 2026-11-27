from __future__ import annotations

import ast
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = REPO_ROOT / "src" / "holon_coherence"
PACKAGE_NAME = "holon_coherence"

BASELINE_CYCLE_EDGES: dict[tuple[str, str], int] = {
    ("parsers", "providers"): 3,
    ("providers", "parsers"): 4,
}


def discover_subpackages(package_root: Path) -> frozenset[str]:
    return frozenset(
        child.name for child in package_root.iterdir() if child.is_dir() and (child / "__init__.py").is_file()
    )


def _resolve_absolute_import_from(node: ast.ImportFrom, package_name: str) -> list[str]:
    if node.module == package_name:
        return [alias.name for alias in node.names]
    prefix = f"{package_name}."
    if node.module and node.module.startswith(prefix):
        return [node.module.split(".")[1]]
    return []


def _resolve_relative_import_from(node: ast.ImportFrom, pkg_parts: list[str]) -> list[str]:
    up = node.level - 1
    if up > len(pkg_parts):
        return []
    base = pkg_parts[: len(pkg_parts) - up]
    if node.module:
        resolved = base + node.module.split(".")
        return [resolved[0]] if resolved else []
    if not base:
        return [alias.name for alias in node.names]
    return [base[0]]


def _resolve_import_from_targets(
    node: ast.ImportFrom,
    pkg_parts: list[str],
    package_name: str,
) -> list[str]:
    if node.level == 0:
        return _resolve_absolute_import_from(node, package_name)
    return _resolve_relative_import_from(node, pkg_parts)


def _extract_imported_subpackages(
    tree: ast.AST,
    pkg_parts: list[str],
    package_name: str,
) -> list[str]:
    targets: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if len(parts) >= 2 and parts[0] == package_name:
                    targets.append(parts[1])
        elif isinstance(node, ast.ImportFrom):
            targets.extend(_resolve_import_from_targets(node, pkg_parts, package_name))
    return targets


def collect_subpackage_edges(
    package_root: Path,
    package_name: str = PACKAGE_NAME,
) -> dict[tuple[str, str], int]:
    subpackages = discover_subpackages(package_root)
    counts: Counter[tuple[str, str]] = Counter()
    for py_file in sorted(package_root.rglob("*.py")):
        rel = py_file.relative_to(package_root)
        if len(rel.parts) < 2 or rel.parts[0] not in subpackages:
            continue
        src_pkg = rel.parts[0]
        pkg_parts = list(rel.parts[:-1])
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for target in _extract_imported_subpackages(tree, pkg_parts, package_name):
            if target in subpackages and target != src_pkg:
                counts[(src_pkg, target)] += 1
    return dict(sorted(counts.items()))


def _is_reachable(adjacency: dict[str, set[str]], start: str, goal: str) -> bool:
    visited: set[str] = {start}
    stack: list[str] = [start]
    while stack:
        current = stack.pop()
        for neighbor in adjacency.get(current, ()):
            if neighbor == goal:
                return True
            if neighbor not in visited:
                visited.add(neighbor)
                stack.append(neighbor)
    return False


def find_cyclic_edges(edges: dict[tuple[str, str], int]) -> dict[tuple[str, str], int]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for src, dst in edges:
        adjacency[src].add(dst)
    return {(src, dst): count for (src, dst), count in sorted(edges.items()) if _is_reachable(adjacency, dst, src)}


def find_cycle_regressions(
    observed_cyclic_edges: dict[tuple[str, str], int],
    baseline: dict[tuple[str, str], int],
) -> list[str]:
    regressions: list[str] = []
    for edge, count in sorted(observed_cyclic_edges.items()):
        src, dst = edge
        if edge not in baseline:
            regressions.append(f"New cyclic import edge {src} -> {dst} (count={count})")
        elif count > baseline[edge]:
            regressions.append(
                f"Expanded cyclic import edge {src} -> {dst} (baseline={baseline[edge]}, observed={count})"
            )
    return regressions


def _write_package(tmp_path: Path, files: dict[str, str], package_name: str = "sample_pkg") -> Path:
    package_root = tmp_path / package_name
    package_root.mkdir(parents=True, exist_ok=True)
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    for rel_path, content in files.items():
        target = package_root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return package_root


def test_live_subpackage_import_cycle_ratchet() -> None:
    observed = find_cyclic_edges(collect_subpackage_edges(PACKAGE_ROOT))
    regressions = find_cycle_regressions(observed, BASELINE_CYCLE_EDGES)
    assert regressions == [], "\n".join(regressions)


def test_acyclic_package_graph_has_no_cyclic_edges(tmp_path: Path) -> None:
    pkg_root = _write_package(
        tmp_path,
        {
            "alpha/__init__.py": "",
            "alpha/mod.py": "from sample_pkg.beta import mod\n",
            "beta/__init__.py": "",
            "beta/mod.py": "import sample_pkg.gamma.mod\n",
            "gamma/__init__.py": "",
            "gamma/mod.py": "VALUE = 1\n",
        },
    )
    edges = collect_subpackage_edges(pkg_root, package_name="sample_pkg")
    observed = find_cyclic_edges(edges)
    assert observed == {}
    assert find_cycle_regressions(observed, {}) == []


def test_new_two_node_cycle_fails_ratchet(tmp_path: Path) -> None:
    pkg_root = _write_package(
        tmp_path,
        {
            "alpha/__init__.py": "",
            "alpha/mod.py": "from sample_pkg.beta import mod\n",
            "beta/__init__.py": "",
            "beta/mod.py": "def load() -> None:\n    from sample_pkg import alpha\n    _ = alpha\n",
        },
    )
    observed = find_cyclic_edges(collect_subpackage_edges(pkg_root, package_name="sample_pkg"))
    assert observed == {("alpha", "beta"): 1, ("beta", "alpha"): 1}
    regressions = find_cycle_regressions(observed, {})
    assert len(regressions) == 2
    assert any("alpha -> beta" in msg for msg in regressions)
    assert any("beta -> alpha" in msg for msg in regressions)


def test_new_three_node_cycle_via_relative_imports_fails_ratchet(tmp_path: Path) -> None:
    pkg_root = _write_package(
        tmp_path,
        {
            "alpha/__init__.py": "",
            "alpha/mod.py": "from ..beta import mod\n",
            "beta/__init__.py": "",
            "beta/mod.py": "from ..gamma.mod import VALUE\n",
            "gamma/__init__.py": "",
            "gamma/mod.py": "from .. import alpha\nVALUE = alpha\n",
        },
    )
    observed = find_cyclic_edges(collect_subpackage_edges(pkg_root, package_name="sample_pkg"))
    assert observed == {
        ("alpha", "beta"): 1,
        ("beta", "gamma"): 1,
        ("gamma", "alpha"): 1,
    }
    regressions = find_cycle_regressions(observed, {})
    assert len(regressions) == 3


def test_existing_cycle_edge_increase_fails_ratchet(tmp_path: Path) -> None:
    pkg_root = _write_package(
        tmp_path,
        {
            "alpha/__init__.py": "",
            "alpha/first.py": "from sample_pkg.beta import mod\n",
            "alpha/second.py": "import sample_pkg.beta.mod\n",
            "beta/__init__.py": "",
            "beta/mod.py": "from sample_pkg.alpha import first\n",
        },
    )
    observed = find_cyclic_edges(collect_subpackage_edges(pkg_root, package_name="sample_pkg"))
    baseline = {("alpha", "beta"): 1, ("beta", "alpha"): 1}
    regressions = find_cycle_regressions(observed, baseline)
    assert len(regressions) == 1
    assert "alpha -> beta" in regressions[0]
    assert "baseline=1, observed=2" in regressions[0]


def test_existing_cycle_edge_reduction_and_break_pass_ratchet(tmp_path: Path) -> None:
    reduced_root = _write_package(
        tmp_path / "reduced",
        {
            "alpha/__init__.py": "",
            "alpha/mod.py": "from sample_pkg.beta import mod\n",
            "beta/__init__.py": "",
            "beta/mod.py": "from sample_pkg.alpha import mod\n",
        },
    )
    baseline = {("alpha", "beta"): 2, ("beta", "alpha"): 1}
    reduced_observed = find_cyclic_edges(collect_subpackage_edges(reduced_root, package_name="sample_pkg"))
    assert reduced_observed == {("alpha", "beta"): 1, ("beta", "alpha"): 1}
    assert find_cycle_regressions(reduced_observed, baseline) == []

    broken_root = _write_package(
        tmp_path / "broken",
        {
            "alpha/__init__.py": "",
            "alpha/mod.py": "from sample_pkg.beta import mod\n",
            "beta/__init__.py": "",
            "beta/mod.py": "VALUE = 1\n",
        },
    )
    broken_observed = find_cyclic_edges(collect_subpackage_edges(broken_root, package_name="sample_pkg"))
    assert broken_observed == {}
    assert find_cycle_regressions(broken_observed, baseline) == []
