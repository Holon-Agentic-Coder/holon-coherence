#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    from scripts.harness_reference_patterns import Finding, scan_line, scan_text
except ModuleNotFoundError:
    from harness_reference_patterns import Finding, scan_line, scan_text

_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_WALK_SKIP_DIRS = frozenset({".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules"})


class CheckExecutionError(RuntimeError):
    pass


def _run_git(repo: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        raise CheckExecutionError(f"failed to execute git: {exc}") from exc


def _extract_diff_target(header_line: str) -> str | None:
    target = header_line[4:].split("\t", 1)[0]
    if target == "/dev/null":
        return None
    return target[2:] if target.startswith("b/") else target


def scan_unified_diff(diff_text: str) -> list[Finding]:
    findings: list[Finding] = []
    current_file: str | None = None
    line_number = 0
    remaining_old = 0
    remaining_new = 0
    for line in diff_text.splitlines():
        if remaining_old > 0 or remaining_new > 0:
            if line.startswith("+"):
                if current_file is not None:
                    findings.extend(scan_line(line[1:], current_file, line_number))
                line_number += 1
                remaining_new = max(remaining_new - 1, 0)
            elif line.startswith("-"):
                remaining_old = max(remaining_old - 1, 0)
            continue
        if line.startswith("diff --git "):
            current_file = None
        elif line.startswith("+++ "):
            current_file = _extract_diff_target(line)
        elif line.startswith("@@ "):
            match = _HUNK_HEADER_RE.match(line)
            if match:
                remaining_old = int(match.group(2)) if match.group(2) is not None else 1
                line_number = int(match.group(3))
                remaining_new = int(match.group(4)) if match.group(4) is not None else 1
    return findings


def _load_pr_body(pr_body: str | None, pr_body_file: str | None, pr_body_env: str | None) -> str:
    parts: list[str] = []
    if pr_body:
        parts.append(pr_body)
    if pr_body_file is not None:
        try:
            parts.append(Path(pr_body_file).read_text(encoding="utf-8"))
        except OSError as exc:
            raise CheckExecutionError(f"failed to read PR body file '{pr_body_file}': {exc}") from exc
    if pr_body_env is not None:
        env_value = os.environ.get(pr_body_env, "")
        if env_value:
            parts.append(env_value)
    return "\n".join(parts)


def run_diff_check(
    repo: Path,
    base: str,
    head: str,
    pr_body: str = "",
) -> list[Finding]:
    if not repo.is_dir():
        raise CheckExecutionError(f"repository path is not a directory: {repo}")
    result = _run_git(repo, ["diff", "--unified=0", "--no-color", base, head])
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit code {result.returncode}"
        raise CheckExecutionError(f"failed to read git diff {base}..{head}: {detail}")
    findings = scan_unified_diff(result.stdout)
    if pr_body:
        findings.extend(scan_text(pr_body, "PR_BODY"))
    return findings


def _discover_tree_files(root: Path) -> list[tuple[Path, str]]:
    probe = _run_git(root, ["rev-parse", "--is-inside-work-tree"])
    if probe.returncode == 0 and probe.stdout.strip() == "true":
        listed = _run_git(root, ["ls-files", "-z"])
        if listed.returncode != 0:
            detail = listed.stderr.strip() or f"exit code {listed.returncode}"
            raise CheckExecutionError(f"failed to list tracked files: {detail}")
        rel_paths = [entry for entry in listed.stdout.split("\0") if entry]
        return [(root / rel, rel) for rel in sorted(rel_paths)]
    discovered: list[tuple[Path, str]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _WALK_SKIP_DIRS)
        base = Path(dirpath)
        for filename in sorted(filenames):
            full_path = base / filename
            if full_path.is_file():
                discovered.append((full_path, full_path.relative_to(root).as_posix()))
    return discovered


def run_tree_check(root: Path) -> list[Finding]:
    if not root.is_dir():
        raise CheckExecutionError(f"root path is not a directory: {root}")
    findings: list[Finding] = []
    for file_path, rel_path in _discover_tree_files(root):
        if not file_path.is_file():
            continue
        try:
            raw = file_path.read_bytes()
        except OSError as exc:
            raise CheckExecutionError(f"failed to read '{rel_path}': {exc}") from exc
        if b"\0" in raw:
            continue
        findings.extend(scan_text(raw.decode("utf-8", errors="ignore"), rel_path))
    return findings


def _emit_findings(findings: list[Finding]) -> int:
    for finding in findings:
        print(f"{finding.source}:{finding.line_number}: [{finding.pattern_name}] {finding.match_text}")
    return 1 if findings else 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="check_no_harness_references.py")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    diff_parser = subparsers.add_parser("diff")
    diff_parser.add_argument("--base", required=True)
    diff_parser.add_argument("--head", required=True)
    diff_parser.add_argument("--repo", default=".")
    diff_parser.add_argument("--pr-body", default=None)
    diff_parser.add_argument("--pr-body-file", default=None)
    diff_parser.add_argument("--pr-body-env", default=None)

    tree_parser = subparsers.add_parser("tree")
    tree_parser.add_argument("--root", default=".")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.mode == "diff":
            pr_body = _load_pr_body(args.pr_body, args.pr_body_file, args.pr_body_env)
            findings = run_diff_check(Path(args.repo), args.base, args.head, pr_body=pr_body)
            return _emit_findings(findings)
        findings = run_tree_check(Path(args.root))
        return _emit_findings(findings)
    except CheckExecutionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
