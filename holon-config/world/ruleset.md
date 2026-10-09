# Holon World Ruleset

This document defines the core runtime rules, coding standards, and testing constraints for `holon-coherence`.

---

## §1 Runtime & Environment Specification

1. **Python Version**: The target runtime environment requires Python `==3.13.*`. All syntax, standard library features,
   and dependencies must be compatible with Python 3.13.
2. **Package & Environment Management**: Package management and execution must be performed strictly via `uv`. Never use
   `pip`, `poetry`, or conda directly.
3. **Single Root Virtual Environment**: Virtual environments must exist exclusively at `.venv` local to the repository
   or worktree root (`<worktree-root>/.venv`). All tool invocations (`pytest`, `ruff`, etc.) must run via `uv run <cmd>`
   from the workspace root.

---

## §2 Coding Conventions & Standards

1. **PEP 8 Compliance**: All Python source code must adhere strictly to PEP 8 standards.
2. **Static Typing**: Explicit type hints must be maintained across all public functions, classes, and method signatures
   using the Python standard library `typing` module.
3. **Documentation & Docstrings**: Comprehensive docstrings following standard conventions (Google or Sphinx/PEP 257
   style) must accompany modules, classes, and public interfaces. Preserve existing docstrings and comments across code
   edits.
4. **Code Quality & Formatting**: Code must conform to Ruff standards (`ruff check` and `ruff format`). No lint errors,
   unused imports, or unformatted code should be introduced.

---

## §3 Testing Constraints

1. **Hermetic Test Isolation**: Tests must be hermetic, deterministic, and isolated from external networks unless
   explicitly testing network proxies with local mock endpoints. Tests must execute cleanly via `uv run pytest`.
2. **Zero Unstaged Regressions**: Any modification must retain 100% pass rate on all pre-existing tests. Unstaged
   regressions or broken test suites are strictly prohibited.
3. **Test-Driven Verification**: New features, bug fixes, and configuration changes must include corresponding unit or
   integration test coverage to validate expected behavior.
