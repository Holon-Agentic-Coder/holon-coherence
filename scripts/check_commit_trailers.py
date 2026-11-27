#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

FORBIDDEN_PREFIXES: tuple[str, ...] = (
    "co-authored-by",
    "co-developed-by",
    "generated-by",
    "assisted-by",
    "generated with [claude code",
)


def find_attribution_lines(message: str) -> list[str]:
    offending: list[str] = []
    for line in message.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if stripped.lower().startswith(FORBIDDEN_PREFIXES):
            offending.append(line)
    return offending


def check_message_file(path: Path) -> int:
    content = path.read_text(encoding="utf-8", errors="replace")
    offending = find_attribution_lines(content)
    for line in offending:
        sys.stderr.write(f"{path}: {line}\n")
    return 1 if offending else 0


def _run_git(args: list[str], repo_dir: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=repo_dir,
        check=False,
    )


def check_revision_range(rev_range: str, repo_dir: Path | None = None) -> int:
    rev_list = _run_git(["rev-list", rev_range], repo_dir=repo_dir)
    if rev_list.returncode != 0:
        sys.stderr.write(rev_list.stderr)
        return 2

    found_violation = False
    for sha in rev_list.stdout.splitlines():
        commit_sha = sha.strip()
        if not commit_sha:
            continue
        show_result = _run_git(["show", "-s", "--format=%B", commit_sha], repo_dir=repo_dir)
        if show_result.returncode != 0:
            sys.stderr.write(show_result.stderr)
            return 2
        offending = find_attribution_lines(show_result.stdout)
        if not offending:
            continue
        short_result = _run_git(["rev-parse", "--short", commit_sha], repo_dir=repo_dir)
        short_sha = short_result.stdout.strip() if short_result.returncode == 0 else commit_sha[:7]
        for line in offending:
            sys.stderr.write(f"{short_sha}: {line}\n")
        found_violation = True

    return 1 if found_violation else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_commit_trailers.py",
        description="Reject forbidden AI attribution trailers in commit messages.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--message-file", type=Path, help="Path to a commit message file.")
    group.add_argument("--range", dest="rev_range", help="Git revision range to inspect.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.message_file is not None:
        return check_message_file(args.message_file)
    return check_revision_range(args.rev_range)


if __name__ == "__main__":
    sys.exit(main())
