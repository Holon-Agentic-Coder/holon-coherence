#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

EXPECTED_LEDGER_NAMES = frozenset({"intents", "plans", "executions"})
EXPECTED_LEDGER_STORES = frozenset(f"holon-knowledge/ledger/{name}.jsonl" for name in EXPECTED_LEDGER_NAMES)
KNOWLEDGE_PREFIX = "holon-knowledge/"
KB_PREFIX = "holon-knowledge/kb/"
LEDGER_PREFIX = "holon-knowledge/ledger/"
PENDING_PREFIX = "holon-knowledge/ledger/pending/"


class StoreCheckError(RuntimeError):
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
        raise StoreCheckError(f"failed to execute git: {exc}") from exc


def _verify_commit(repo: Path, ref: str) -> None:
    result = _run_git(repo, ["rev-parse", "--verify", f"{ref}^{{commit}}"])
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit code {result.returncode}"
        raise StoreCheckError(f"failed to resolve git ref '{ref}': {detail}")


def _check_pending_path(path: str) -> str | None:
    rel = path[len(PENDING_PREFIX) :]
    parts = rel.split("/")
    if len(parts) != 2:
        return f"unexpected path under {PENDING_PREFIX}: {path}"
    subdir, filename = parts
    if subdir not in EXPECTED_LEDGER_NAMES:
        return f"unexpected pending ledger subdirectory '{subdir}': {path}"
    if not (filename.endswith(".jsonl") or filename == ".gitkeep"):
        return f"unexpected pending ledger file: {path}"
    return None


def check_ledger_store_paths(paths: Iterable[str]) -> list[str]:
    present_stores: set[str] = set()
    violations: list[str] = []
    for raw_path in sorted(set(paths)):
        path = raw_path.replace("\\", "/")
        if not path.startswith(KNOWLEDGE_PREFIX) or path.startswith(KB_PREFIX):
            continue
        if path in EXPECTED_LEDGER_STORES:
            present_stores.add(path)
            continue
        if path.startswith(PENDING_PREFIX):
            violation = _check_pending_path(path)
            if violation is not None:
                violations.append(violation)
            continue
        if path.startswith(LEDGER_PREFIX):
            violations.append(f"unexpected path under {LEDGER_PREFIX}: {path}")
            continue
        if path.endswith(".jsonl"):
            violations.append(f"unexpected jsonl store outside {KB_PREFIX}: {path}")
    for missing in sorted(EXPECTED_LEDGER_STORES - present_stores):
        violations.append(f"missing canonical ledger store: {missing}")
    return violations


def list_tree_paths(repo: Path, ref: str | None = None) -> list[str]:
    if not repo.is_dir():
        raise StoreCheckError(f"repository path is not a directory: {repo}")
    if ref is not None:
        _verify_commit(repo, ref)
        result = _run_git(repo, ["ls-tree", "-r", "--name-only", "-z", ref, "--", "holon-knowledge"])
        if result.returncode != 0:
            detail = result.stderr.strip() or f"exit code {result.returncode}"
            raise StoreCheckError(f"failed to list git tree for '{ref}': {detail}")
        return sorted(entry for entry in result.stdout.split("\0") if entry)
    knowledge_dir = repo / "holon-knowledge"
    if not knowledge_dir.is_dir():
        raise StoreCheckError(f"holon-knowledge directory not found: {knowledge_dir}")

    def _raise_walk_error(exc: OSError) -> None:
        raise StoreCheckError(f"failed to read directory '{exc.filename}': {exc}") from exc

    discovered: list[str] = []
    for dirpath, dirnames, filenames in os.walk(knowledge_dir, onerror=_raise_walk_error):
        dirnames.sort()
        base_dir = Path(dirpath)
        for filename in sorted(filenames):
            full_path = base_dir / filename
            discovered.append(full_path.relative_to(repo).as_posix())
    return sorted(discovered)


def check_ledger_stores(repo: Path, base: str | None = None, head: str | None = None) -> list[str]:
    if not repo.is_dir():
        raise StoreCheckError(f"repository path is not a directory: {repo}")
    if base is not None:
        _verify_commit(repo, base)
    paths = list_tree_paths(repo, ref=head)
    return check_ledger_store_paths(paths)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="check_ledger_stores.py")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--base", default=None)
    parser.add_argument("--head", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        violations = check_ledger_stores(Path(args.repo), base=args.base, head=args.head)
    except StoreCheckError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for violation in violations:
        print(violation)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
