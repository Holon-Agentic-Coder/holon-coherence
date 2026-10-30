"""Pytest suite enforcing Ruff complexity thresholds and inline noqa ratchet ceiling."""

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

# Ratchet ceiling: Maximum permissible legacy function inline noqa suppressions for complexity rules.
# This baseline must NEVER increase. When legacy functions are refactored, reduce this ceiling accordingly.
BASELINE_CEILING = 43

COMPLEXITY_NOQA_PATTERN = re.compile(r"#\s*noqa(?::|\s).*?\b(C901|PLR0911|PLR0912|PLR0913|PLR0915)\b")


def _load_pyproject() -> dict:
    with PYPROJECT_PATH.open("rb") as f:
        return tomllib.load(f)


def test_pyproject_complexity_configuration() -> None:
    """Verify that pyproject.toml defines required complexity rules and exact thresholds."""
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
    """Verify that complexity rules are not blanket-suppressed via ignore or per-file-ignores."""
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


def test_complexity_baseline_ratchet_ceiling() -> None:
    """Verify that inline noqa suppressions for complexity rules do not exceed baseline ceiling."""
    matches: list[tuple[str, int, str]] = []

    for py_file in sorted(SRC_ROOT.rglob("*.py")):
        content = py_file.read_text(encoding="utf-8")
        for line_no, line in enumerate(content.splitlines(), start=1):
            if COMPLEXITY_NOQA_PATTERN.search(line):
                rel_path = py_file.relative_to(REPO_ROOT).as_posix()
                matches.append((rel_path, line_no, line.strip()))

    total_count = len(matches)
    assert total_count <= BASELINE_CEILING, (
        f"Complexity baseline ratchet ceiling exceeded! Expected <= {BASELINE_CEILING}, got {total_count}.\n"
        f"Violations:\n" + "\n".join(f"  {path}:{lineno} -> {line}" for path, lineno, line in matches)
    )
    assert total_count == BASELINE_CEILING, (
        f"Ratchet opportunity: Detected fewer inline complexity suppressions ({total_count}) "
        f"than BASELINE_CEILING ({BASELINE_CEILING}). Update BASELINE_CEILING to {total_count}!"
    )


def test_ruff_check_clean() -> None:
    """Verify that Ruff static analysis passes cleanly with complexity rules enabled."""
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
