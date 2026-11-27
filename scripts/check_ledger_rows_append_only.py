#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

LEDGER_TREE_PATH = "holon-knowledge/ledger"


class AppendOnlyCheckError(RuntimeError):
    pass


@dataclass(frozen=True)
class Violation:
    path: str
    reason: str
    row_index: int | None = None

    def format_line(self) -> str:
        if self.row_index is not None:
            return f"{self.path}:{self.row_index}: {self.reason}"
        return f"{self.path}: {self.reason}"


def _run_git_bytes(repo: Path, args: list[str]) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise AppendOnlyCheckError(f"failed to execute git: {exc}") from exc


def _decode_stderr(stderr: bytes, returncode: int) -> str:
    text = stderr.decode("utf-8", errors="replace").strip()
    return text or f"exit code {returncode}"


def _verify_commit(repo: Path, ref: str) -> None:
    result = _run_git_bytes(repo, ["rev-parse", "--verify", f"{ref}^{{commit}}"])
    if result.returncode != 0:
        detail = _decode_stderr(result.stderr, result.returncode)
        raise AppendOnlyCheckError(f"failed to resolve git ref '{ref}': {detail}")


def _resolve_merge_base(repo: Path, base: str, head: str) -> str:
    result = _run_git_bytes(repo, ["merge-base", base, head])
    if result.returncode != 0:
        detail = _decode_stderr(result.stderr, result.returncode)
        raise AppendOnlyCheckError(f"failed to resolve merge-base for '{base}' and '{head}': {detail}")
    merge_base = result.stdout.decode("utf-8", errors="replace").strip()
    if not merge_base:
        raise AppendOnlyCheckError(f"empty merge-base for '{base}' and '{head}'")
    return merge_base


def _list_ledger_jsonl_paths(repo: Path, ref: str) -> list[str]:
    result = _run_git_bytes(repo, ["ls-tree", "-r", "--name-only", "-z", ref, "--", LEDGER_TREE_PATH])
    if result.returncode != 0:
        detail = _decode_stderr(result.stderr, result.returncode)
        raise AppendOnlyCheckError(f"failed to list ledger tree at '{ref}': {detail}")
    entries = [raw.decode("utf-8", errors="surrogateescape") for raw in result.stdout.split(b"\0") if raw]
    return sorted(entry for entry in entries if entry.endswith(".jsonl"))


def _read_git_blob(repo: Path, ref: str, rel_path: str) -> bytes:
    result = _run_git_bytes(repo, ["show", f"{ref}:{rel_path}"])
    if result.returncode != 0:
        detail = _decode_stderr(result.stderr, result.returncode)
        raise AppendOnlyCheckError(f"failed to read '{rel_path}' at '{ref}': {detail}")
    return result.stdout


def check_bytes_append_only(path: str, base_bytes: bytes, head_bytes: bytes | None) -> list[Violation]:
    if head_bytes is None:
        return [Violation(path=path, reason="base ledger file deleted on head")]
    base_rows = base_bytes.splitlines()
    head_rows = head_bytes.splitlines()
    violations: list[Violation] = []
    shared_count = min(len(base_rows), len(head_rows))
    for index in range(shared_count):
        if head_rows[index] != base_rows[index]:
            violations.append(
                Violation(
                    path=path,
                    reason="base row edited or reordered",
                    row_index=index + 1,
                )
            )
    if len(head_rows) < len(base_rows):
        violations.append(
            Violation(
                path=path,
                reason=f"base rows deleted (expected at least {len(base_rows)}, found {len(head_rows)})",
                row_index=len(head_rows) + 1,
            )
        )
    if not violations and base_bytes:
        if base_bytes.endswith(b"\n"):
            if not head_bytes.startswith(base_bytes):
                violations.append(Violation(path=path, reason="base byte prefix modified"))
        elif head_bytes != base_bytes and not head_bytes.startswith(base_bytes + b"\n"):
            violations.append(Violation(path=path, reason="base byte prefix modified"))
    return violations


def check_ledger_rows_append_only(repo: Path, base: str, head: str) -> list[Violation]:
    if not repo.is_dir():
        raise AppendOnlyCheckError(f"repository path is not a directory: {repo}")
    _verify_commit(repo, base)
    _verify_commit(repo, head)
    merge_base = _resolve_merge_base(repo, base, head)
    base_paths = _list_ledger_jsonl_paths(repo, merge_base)
    head_paths = set(_list_ledger_jsonl_paths(repo, head))
    violations: list[Violation] = []
    for rel_path in base_paths:
        base_bytes = _read_git_blob(repo, merge_base, rel_path)
        head_bytes = _read_git_blob(repo, head, rel_path) if rel_path in head_paths else None
        violations.extend(check_bytes_append_only(rel_path, base_bytes, head_bytes))
    return violations


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="check_ledger_rows_append_only.py")
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--repo", default=".")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        violations = check_ledger_rows_append_only(Path(args.repo), args.base, args.head)
    except AppendOnlyCheckError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for violation in violations:
        print(violation.format_line())
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
