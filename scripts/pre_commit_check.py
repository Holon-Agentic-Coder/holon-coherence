#!/usr/bin/env python3
from __future__ import annotations

import fnmatch
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
BUDGET_CONFIG_REL_PATH = "holon-config/hygiene/module_budgets.json"
DISALLOWED_PATH_PATTERNS = ["tmp/*", "*/tmp/*", "*.tmp", "*.log", ".index/*", "*/.index/*"]
SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "Anthropic API Key": re.compile(r"\bsk-ant-[0-9A-Za-z\-_]{20,}\b"),
    "Google AI API Key": re.compile(r"\bAIza[0-9A-Za-z\-_]{30,40}\b"),
    "GitHub PAT (classic)": re.compile(r"\bghp_[0-9A-Za-z]{30,50}\b"),
    "GitHub PAT (fine-grained)": re.compile(r"\bgithub_pat_[0-9A-Za-z_]{20,}\b"),
    "OpenAI API Key": re.compile(r"\bsk-(?!ant-)[0-9A-Za-z\-_]{20,}\b"),
}
IGNORED_DIRS = {".git", ".venv", "venv", ".pytest_cache", ".ruff_cache", "__pycache__", "build", "dist"}
SCAN_WHITELIST_PATTERNS = ["tests/test_*.py", "docs/*"]
INLINE_SECRET_EXEMPTION_MARKERS = ("holon:allow-secret", "pr-allow-secret")
BINARY_NON_TEXT_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".pyc", ".db", ".so"})


def _normalise_path(path: str | Path) -> str:
    s = str(path).replace("\\", "/")
    while s.startswith("./"):
        s = s[2:]
    return s


def _is_disallowed_external_filename(filename: str) -> bool:
    return any(fnmatch.fnmatch(filename, pat) for pat in ("*.tmp", "*.log")) or filename.endswith((".tmp", ".log"))


def _is_in_ignored_dir(norm_path: str) -> bool:
    return any(ignored in norm_path.split("/") for ignored in IGNORED_DIRS)


def is_disallowed_path(path: str | Path) -> bool:
    p = Path(path)
    if p.is_absolute():
        try:
            p = p.resolve().relative_to(Path.cwd().resolve())
        except ValueError:
            return _is_disallowed_external_filename(p.name)
    norm = _normalise_path(p)
    if any(fnmatch.fnmatch(norm, pat) for pat in DISALLOWED_PATH_PATTERNS):
        return True
    parts = norm.split("/")
    if "tmp" in parts[:-1] or parts[0] == "tmp" or ".index" in parts[:-1] or parts[0] == ".index":
        return True
    return bool(norm.endswith(".tmp") or norm.endswith(".log"))


def mask_secret(secret: str) -> str:
    return "****" if len(secret) <= 8 else f"{secret[:4]}...{secret[-4:]}"


def check_content(content: str, filename: str = "") -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for line_num, line in enumerate(content.splitlines(), start=1):
        if any(marker in line for marker in INLINE_SECRET_EXEMPTION_MARKERS):
            continue
        for name, pattern in SECRET_PATTERNS.items():
            for match in pattern.finditer(line):
                findings.append(
                    {"file": filename, "line": line_num, "pattern": name, "masked": mask_secret(match.group(0))}
                )
    return findings


def is_whitelisted_path(path: str | Path) -> bool:
    norm = _normalise_path(path)
    name = Path(norm).name
    return any(fnmatch.fnmatch(norm, pat) or fnmatch.fnmatch(name, pat) for pat in SCAN_WHITELIST_PATTERNS)


def scan_file(path: str | Path) -> list[str]:
    errors: list[str] = []
    str_path = _normalise_path(path)
    if is_disallowed_path(str_path):
        errors.append(f"Disallowed ephemeral scratch path staged: {str_path}")
    p = Path(path)
    if not p.is_file() or is_whitelisted_path(str_path) or p.suffix in BINARY_NON_TEXT_EXTENSIONS:
        return errors
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return errors
    for f in check_content(content, filename=str_path):
        errors.append(
            f"Potential secret credential detected in {f['file']}:{f['line']} [{f['pattern']}]: {f['masked']}"
        )
    return errors


def get_staged_files() -> list[str]:
    try:
        res = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            capture_output=True,
            text=True,
            check=True,
        )
        return [line.strip() for line in res.stdout.splitlines() if line.strip()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []


def _to_repo_relative(path: str | Path) -> str | None:
    p = Path(path)
    if p.is_absolute():
        try:
            return _normalise_path(p.resolve().relative_to(REPO_ROOT))
        except ValueError:
            return None
    return _normalise_path(p)


def _should_check_module_budgets(files_to_check: list[str], check_all: bool) -> bool:
    if check_all:
        return True
    for f in files_to_check:
        rel = _to_repo_relative(f)
        if rel is None:
            continue
        if rel == BUDGET_CONFIG_REL_PATH or (rel.endswith(".py") and rel.startswith(("src/", "scripts/"))):
            return True
    return False


def _run_module_budget_check() -> list[str]:
    try:
        from scripts.check_module_budgets import check_repo_budgets
    except ModuleNotFoundError:
        from check_module_budgets import check_repo_budgets
    errors, notices = check_repo_budgets(REPO_ROOT)
    for notice in notices:
        print(notice)
    return errors


def _collect_files(argv: list[str]) -> tuple[list[str], bool]:
    if argv and any(a in ("--all", "--all-files") for a in argv):
        try:
            res = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
            return [line.strip() for line in res.stdout.splitlines() if line.strip()], True
        except Exception:
            return [], True
    if argv:
        return [arg for arg in argv if not arg.startswith("-")], False
    return get_staged_files(), False


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    files_to_check, check_all = _collect_files(argv)
    if not files_to_check:
        print("✅ No staged files to check.")
        return 0
    all_errors: list[str] = []
    for f in files_to_check:
        if not _is_in_ignored_dir(_normalise_path(f)):
            all_errors.extend(scan_file(f))
    if _should_check_module_budgets(files_to_check, check_all):
        all_errors.extend(_run_module_budget_check())
    if all_errors:
        print("❌ Pre-commit validation failed:")
        for err in all_errors:
            print(f"  - {err}")
        print("\nPlease remediate the issues above before committing.")
        return 1
    print("✅ Pre-commit validation passed cleanly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
