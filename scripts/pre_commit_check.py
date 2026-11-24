#!/usr/bin/env python3
from __future__ import annotations

import fnmatch
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

DISALLOWED_PATH_PATTERNS = [
    "tmp/*",
    "*/tmp/*",
    "*.tmp",
    "*.log",
    ".index/*",
    "*/.index/*",
]

SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "Anthropic API Key": re.compile(r"\bsk-ant-[0-9A-Za-z\-_]{20,}\b"),
    "Google AI API Key": re.compile(r"\bAIza[0-9A-Za-z\-_]{30,40}\b"),
    "GitHub PAT (classic)": re.compile(r"\bghp_[0-9A-Za-z]{30,50}\b"),
    "GitHub PAT (fine-grained)": re.compile(r"\bgithub_pat_[0-9A-Za-z_]{20,}\b"),
    "OpenAI API Key": re.compile(r"\bsk-(?!ant-)[0-9A-Za-z\-_]{20,}\b"),
}

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

SCAN_WHITELIST_PATTERNS = [
    "tests/test_*.py",
    "docs/*",
]

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
    for pat in DISALLOWED_PATH_PATTERNS:
        if fnmatch.fnmatch(norm, pat):
            return True
    parts = norm.split("/")
    if "tmp" in parts[:-1] or parts[0] == "tmp":
        return True
    if ".index" in parts[:-1] or parts[0] == ".index":
        return True
    return bool(norm.endswith(".tmp") or norm.endswith(".log"))


def mask_secret(secret: str) -> str:
    if len(secret) <= 8:
        return "****"
    return f"{secret[:4]}...{secret[-4:]}"


def check_content(content: str, filename: str = "") -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    lines = content.splitlines()
    for line_num, line in enumerate(lines, start=1):
        if any(marker in line for marker in INLINE_SECRET_EXEMPTION_MARKERS):
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


def is_whitelisted_path(path: str | Path) -> bool:
    norm = _normalise_path(path)
    for pat in SCAN_WHITELIST_PATTERNS:
        if fnmatch.fnmatch(norm, pat):
            return True
        if fnmatch.fnmatch(Path(norm).name, pat):
            return True
    return False


def scan_file(path: str | Path) -> list[str]:
    errors: list[str] = []
    str_path = _normalise_path(path)

    if is_disallowed_path(str_path):
        errors.append(f"Disallowed ephemeral scratch path staged: {str_path}")

    p = Path(path)
    if not p.is_file() or is_whitelisted_path(str_path):
        return errors

    if p.suffix in BINARY_NON_TEXT_EXTENSIONS:
        return errors

    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return errors

    findings = check_content(content, filename=str_path)
    for f in findings:
        msg = f"Potential secret credential detected in {f['file']}:{f['line']} [{f['pattern']}]: {f['masked']}"
        errors.append(msg)

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


def main(argv: list[str] | None = None) -> int:  # noqa: C901
    if argv is None:
        argv = sys.argv[1:]

    files_to_check: list[str] = []
    if argv and any(a in ("--all", "--all-files") for a in argv):
        try:
            res = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
            files_to_check = [line.strip() for line in res.stdout.splitlines() if line.strip()]
        except Exception:
            files_to_check = []
    elif argv:
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
        norm_f = _normalise_path(f)
        if _is_in_ignored_dir(norm_f):
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
