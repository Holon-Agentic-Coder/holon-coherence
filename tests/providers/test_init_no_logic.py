from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_PACKAGE_ROOT = REPO_ROOT / "src" / "holon_coherence"


def _find_init_logic_violations(source: str, rel_path: str) -> list[str]:
    tree = ast.parse(source, filename=rel_path)
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            violations.append(f"{rel_path}:{node.lineno} {type(node).__name__} '{node.name}'")
    return violations


def _discover_package_init_files() -> list[Path]:
    return sorted(SRC_PACKAGE_ROOT.rglob("__init__.py"))


def test_all_package_init_files_contain_no_function_or_class_definitions() -> None:
    init_files = _discover_package_init_files()
    assert init_files, f"No __init__.py files discovered under {SRC_PACKAGE_ROOT}"
    assert SRC_PACKAGE_ROOT / "providers" / "__init__.py" in init_files

    violations: list[str] = []
    for init_file in init_files:
        rel_path = init_file.relative_to(REPO_ROOT).as_posix()
        source = init_file.read_text(encoding="utf-8")
        violations.extend(_find_init_logic_violations(source, rel_path))

    assert not violations, "Package __init__.py files must not define functions or classes:\n" + "\n".join(violations)


def test_init_no_logic_detects_synthetic_function_async_function_and_class() -> None:
    sample = (
        "def helper() -> None:\n    pass\n\nasync def async_helper() -> None:\n    pass\n\nclass Widget:\n    pass\n"
    )
    violations = _find_init_logic_violations(sample, "synthetic/__init__.py")
    assert len(violations) == 3
    assert any("FunctionDef 'helper'" in v for v in violations)
    assert any("AsyncFunctionDef 'async_helper'" in v for v in violations)
    assert any("ClassDef 'Widget'" in v for v in violations)

    pure_reexport = 'from pkg.mod import Foo\n\n__all__ = ["Foo"]\n'
    assert _find_init_logic_violations(pure_reexport, "synthetic/__init__.py") == []
