from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src" / "holon_coherence"
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"

COMPLEXITY_RULES = frozenset({"C901", "PLR0911", "PLR0912", "PLR0913", "PLR0915"})

BASELINE_CEILING = 11

COMPLEXITY_NOQA_PATTERN = re.compile(r"#\s*noqa(?::|\s).*?\b(C901|PLR0911|PLR0912|PLR0913|PLR0915)\b")


def _load_pyproject() -> dict:
    with PYPROJECT_PATH.open("rb") as f:
        return tomllib.load(f)


def test_pyproject_complexity_configuration() -> None:
    config = _load_pyproject()
    ruff_lint = config.get("tool", {}).get("ruff", {}).get("lint", {})

    select = ruff_lint.get("select", [])
    missing_rules = COMPLEXITY_RULES - set(select)
    assert not missing_rules, f"pyproject.toml is missing complexity rules in lint.select: {missing_rules}"

    mccabe = ruff_lint.get("mccabe", {})
    assert mccabe.get("max-complexity") == 10, (
        f"Expected mccabe.max-complexity to be 10, got {mccabe.get('max-complexity')}"
    )

    pylint = ruff_lint.get("pylint", {})
    assert pylint.get("max-args") == 5, f"Expected pylint.max-args to be 5, got {pylint.get('max-args')}"
    assert pylint.get("max-branches") == 12, f"Expected pylint.max-branches to be 12, got {pylint.get('max-branches')}"
    assert pylint.get("max-returns") == 6, f"Expected pylint.max-returns to be 6, got {pylint.get('max-returns')}"
    assert pylint.get("max-statements") == 50, (
        f"Expected pylint.max-statements to be 50, got {pylint.get('max-statements')}"
    )


def test_no_global_or_per_file_suppression_of_complexity_rules() -> None:
    config = _load_pyproject()
    ruff_lint = config.get("tool", {}).get("ruff", {}).get("lint", {})

    ignored = set(ruff_lint.get("ignore", []))
    suppressed_in_ignore = ignored & COMPLEXITY_RULES
    assert not suppressed_in_ignore, f"Complexity rules must not be ignored in pyproject.toml: {suppressed_in_ignore}"

    per_file_ignores = ruff_lint.get("per-file-ignores", {})
    for path_pattern, rules in per_file_ignores.items():
        rules_set = set(rules) if isinstance(rules, list) else {rules}
        suppressed = rules_set & COMPLEXITY_RULES
        assert not suppressed, (
            f"Complexity rules must not be suppressed via per-file-ignores for '{path_pattern}': {suppressed}"
        )


def _collect_complexity_noqa_matches(src_root: Path, repo_root: Path) -> list[tuple[str, int, str]]:
    matches: list[tuple[str, int, str]] = []
    for py_file in sorted(src_root.rglob("*.py")):
        content = py_file.read_text(encoding="utf-8")
        for line_no, line in enumerate(content.splitlines(), start=1):
            if COMPLEXITY_NOQA_PATTERN.search(line):
                rel_path = py_file.relative_to(repo_root).as_posix()
                matches.append((rel_path, line_no, line.strip()))
    return matches


def _assert_complexity_ceiling(src_root: Path, repo_root: Path, ceiling: int) -> list[tuple[str, int, str]]:
    matches = _collect_complexity_noqa_matches(src_root, repo_root)
    total_count = len(matches)
    assert total_count <= ceiling, (
        f"Complexity baseline ratchet ceiling exceeded! Expected <= {ceiling}, got {total_count}.\n"
        f"Violations:\n" + "\n".join(f"  {path}:{lineno} -> {line}" for path, lineno, line in matches)
    )
    return matches


def test_complexity_baseline_ratchet_ceiling() -> None:
    _assert_complexity_ceiling(SRC_ROOT, REPO_ROOT, BASELINE_CEILING)


def test_complexity_ceiling_allows_strict_reduction_and_fails_on_regression(tmp_path: Path) -> None:
    src_dir = tmp_path / "src" / "pkg"
    src_dir.mkdir(parents=True)
    target_file = src_dir / "sample.py"

    target_file.write_text("def alpha() -> int:  # noqa: C901\n    return 1\n", encoding="utf-8")
    matches_below = _assert_complexity_ceiling(src_dir, tmp_path, ceiling=3)
    assert len(matches_below) == 1

    target_file.write_text("def alpha() -> int:\n    return 1\n", encoding="utf-8")
    matches_zero = _assert_complexity_ceiling(src_dir, tmp_path, ceiling=3)
    assert len(matches_zero) == 0

    target_file.write_text(
        "def alpha() -> int:  # noqa: C901\n    return 1\n\ndef beta() -> int:  # noqa: PLR0912\n    return 2\n",
        encoding="utf-8",
    )
    matches_equal = _assert_complexity_ceiling(src_dir, tmp_path, ceiling=2)
    assert len(matches_equal) == 2

    target_file.write_text(
        (
            "def alpha() -> int:  # noqa: C901\n"
            "    return 1\n\n"
            "def beta() -> int:  # noqa: PLR0912\n"
            "    return 2\n\n"
            "def gamma() -> int:  # noqa: PLR0915\n"
            "    return 3\n"
        ),
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match="Complexity baseline ratchet ceiling exceeded"):
        _assert_complexity_ceiling(src_dir, tmp_path, ceiling=2)


def test_ruff_check_clean() -> None:
    ruff_bin = shutil.which("ruff")
    if not ruff_bin:
        candidate = Path(sys.executable).parent / "ruff"
        if candidate.is_file():
            ruff_bin = str(candidate)
    if not ruff_bin:
        pytest.skip("Ruff binary not directly accessible in PATH or virtual environment")

    cmd = [
        ruff_bin,
        "check",
        str(SRC_ROOT),
        "--select",
        ",".join(sorted(COMPLEXITY_RULES)),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert proc.returncode == 0, (
        f"Ruff complexity check failed with return code {proc.returncode}:\n"
        f"STDOUT:\n{proc.stdout}\n"
        f"STDERR:\n{proc.stderr}"
    )
