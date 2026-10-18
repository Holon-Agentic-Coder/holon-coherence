#!/usr/bin/env python3
"""Pre-commit security hook and hygiene validator.

Scans staged files (or explicitly passed file paths) for:
1. Hardcoded secret credentials (Google AI, GitHub PATs, Anthropic, OpenAI).
2. Disallowed ephemeral scratch and temporary paths (tmp/*, *.tmp, *.log, .index/*).
"""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

# Disallowed ephemeral scratch patterns
DISALLOWED_PATH_PATTERNS = [
    "tmp/*",
    "*/tmp/*",
    "*.tmp",
    "*.log",
    ".index/*",
    "*/.index/*",
]

# Secret detection regexes
SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "Anthropic API Key": re.compile(r"\bsk-ant-[0-9A-Za-z\-_]{20,}\b"),
    "Google AI API Key": re.compile(r"\bAIza[0-9A-Za-z\-_]{30,40}\b"),
    "GitHub PAT (classic)": re.compile(r"\bghp_[0-9A-Za-z]{30,50}\b"),
    "GitHub PAT (fine-grained)": re.compile(r"\bgithub_pat_[0-9A-Za-z_]{20,}\b"),
    "OpenAI API Key": re.compile(r"\bsk-(?!ant-)[0-9A-Za-z\-_]{20,}\b"),
}

# Directories and files always ignored
IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "build",
    "dist",
}


def is_disallowed_path(path: str | Path) -> bool:
    """Return True if the path matches any disallowed ephemeral scratch path pattern."""
    norm = str(path).replace("\\", "/").lstrip("./")
    for pat in DISALLOWED_PATH_PATTERNS:
        if fnmatch.fnmatch(norm, pat):
            return True
    parts = norm.split("/")
    if "tmp" in parts[:-1] or parts[0] == "tmp":
        return True
    if ".index" in parts[:-1] or parts[0] == ".index":
        return True
    if norm.endswith(".tmp") or norm.endswith(".log"):
        return True
    return False


def mask_secret(secret: str) -> str:
    """Mask sensitive secret characters for safe reporting."""
    if len(secret) <= 8:
        return "****"
    return f"{secret[:4]}...{secret[-4:]}"


def check_content(content: str, filename: str = "") -> list[dict[str, Any]]:
    """Scan content line by line for secret patterns."""
    findings: list[dict[str, Any]] = []
    lines = content.splitlines()
    for line_num, line in enumerate(lines, start=1):
        # Allow intentional inline exemptions
        if "holon:allow-secret" in line or "pr-allow-secret" in line:
            continue
        for name, pattern in SECRET_PATTERNS.items():
            for match in pattern.finditer(line):
                secret = match.group(0)
                findings.append(
                    {
                        "file": filename,
                        "line": line_num,
                        "pattern": name,
                        "masked": mask_secret(secret),
                    }
                )
    return findings


def scan_file(path: str | Path) -> list[str]:
    """Scan a single file for path violations and secret credentials."""
    errors: list[str] = []
    str_path = str(path).replace("\\", "/").lstrip("./")

    # 1. Check disallowed scratch path
    if is_disallowed_path(str_path):
        errors.append(f"Disallowed ephemeral scratch path staged: {str_path}")

    # 2. Check content for secrets if file exists and is a regular file
    p = Path(path)
    if not p.is_file():
        return errors

    # Ignore binary files or common non-text extensions
    if p.suffix in {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".pyc", ".db", ".so"}:
        return errors

    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        # Ignore unreadable files
        return errors

    findings = check_content(content, filename=str_path)
    for f in findings:
        errors.append(f"Potential secret credential detected in {f['file']}:{f['line']} [{f['pattern']}]: {f['masked']}")

    return errors


def get_staged_files() -> list[str]:
    """Retrieve list of staged files from git diff."""
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


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for pre-commit check."""
    if argv is None:
        argv = sys.argv[1:]

    files_to_check: list[str] = []
    if argv:
        for arg in argv:
            if not arg.startswith("-"):
                files_to_check.append(arg)
    else:
        files_to_check = get_staged_files()

    if not files_to_check:
        print("✅ No staged files to check.")
        return 0

    all_errors: list[str] = []
    for f in files_to_check:
        norm_f = f.replace("\\", "/").lstrip("./")
        # Skip explicitly ignored directories
        parts = norm_f.split("/")
        if any(ignored in parts for ignored in IGNORED_DIRS):
            continue
        errors = scan_file(f)
        all_errors.extend(errors)

    if all_errors:
        print("❌ Pre-commit validation failed:")
        for err in all_errors:
            print(f"  - {err}")
        print("\nPlease remediate the credential leaks and remove disallowed ephemeral paths before committing.")
        return 1

    print("✅ Pre-commit validation passed cleanly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
