from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.check_ledger_rows_append_only import (
    AppendOnlyCheckError,
    check_ledger_rows_append_only,
    main,
)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit_all(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(
        repo,
        "-c",
        "user.name=Test User",
        "-c",
        "user.email=test@example.com",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-m",
        message,
    )
    return _git(repo, "rev-parse", "HEAD")


def _create_base_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    ledger_dir = repo / "holon-knowledge" / "ledger"
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "intents.jsonl").write_bytes(b'{"id":"I-1","v":1}\n{"id":"I-2","v":2}\n')
    (ledger_dir / "plans.jsonl").write_bytes(b'{"id":"P-1"}\n')
    (ledger_dir / "executions.jsonl").write_bytes(b'{"id":"E-1"}\n')
    pending_intent = ledger_dir / "pending" / "intents" / "I-1.jsonl"
    pending_intent.parent.mkdir(parents=True)
    pending_intent.write_bytes(b'{"id":"I-1","pending":true}\n')
    base_sha = _commit_all(repo, "base ledger")
    return repo, base_sha


def test_appending_rows_and_new_pending_fragment_passes(tmp_path: Path) -> None:
    repo, base_sha = _create_base_repo(tmp_path)
    intents = repo / "holon-knowledge" / "ledger" / "intents.jsonl"
    intents.write_bytes(intents.read_bytes() + b'{"id":"I-3","v":3}\n')
    new_pending = repo / "holon-knowledge" / "ledger" / "pending" / "plans" / "P-2.jsonl"
    new_pending.parent.mkdir(parents=True)
    new_pending.write_bytes(b'{"id":"P-2","pending":true}\n')
    head_sha = _commit_all(repo, "append rows and pending fragment")
    assert check_ledger_rows_append_only(repo, base_sha, head_sha) == []
    assert main(["--repo", str(repo), "--base", base_sha, "--head", head_sha]) == 0


def test_editing_single_byte_in_base_row_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo, base_sha = _create_base_repo(tmp_path)
    intents = repo / "holon-knowledge" / "ledger" / "intents.jsonl"
    intents.write_bytes(b'{"id":"I-1","v":9}\n{"id":"I-2","v":2}\n')
    head_sha = _commit_all(repo, "edit byte")
    violations = check_ledger_rows_append_only(repo, base_sha, head_sha)
    assert len(violations) == 1
    assert violations[0].path == "holon-knowledge/ledger/intents.jsonl"
    assert violations[0].row_index == 1
    assert main(["--repo", str(repo), "--base", base_sha, "--head", head_sha]) == 1
    assert "holon-knowledge/ledger/intents.jsonl:1:" in capsys.readouterr().out


def test_deleting_base_row_fails(tmp_path: Path) -> None:
    repo, base_sha = _create_base_repo(tmp_path)
    intents = repo / "holon-knowledge" / "ledger" / "intents.jsonl"
    intents.write_bytes(b'{"id":"I-1","v":1}\n')
    head_sha = _commit_all(repo, "delete row")
    violations = check_ledger_rows_append_only(repo, base_sha, head_sha)
    assert any(v.path == "holon-knowledge/ledger/intents.jsonl" for v in violations)
    assert main(["--repo", str(repo), "--base", base_sha, "--head", head_sha]) == 1


def test_deleting_base_pending_fragment_fails(tmp_path: Path) -> None:
    repo, base_sha = _create_base_repo(tmp_path)
    (repo / "holon-knowledge" / "ledger" / "pending" / "intents" / "I-1.jsonl").unlink()
    head_sha = _commit_all(repo, "delete pending fragment")
    violations = check_ledger_rows_append_only(repo, base_sha, head_sha)
    assert len(violations) == 1
    assert violations[0].path == "holon-knowledge/ledger/pending/intents/I-1.jsonl"
    assert main(["--repo", str(repo), "--base", base_sha, "--head", head_sha]) == 1


def test_reordering_existing_base_rows_fails(tmp_path: Path) -> None:
    repo, base_sha = _create_base_repo(tmp_path)
    intents = repo / "holon-knowledge" / "ledger" / "intents.jsonl"
    intents.write_bytes(b'{"id":"I-2","v":2}\n{"id":"I-1","v":1}\n')
    head_sha = _commit_all(repo, "reorder rows")
    violations = check_ledger_rows_append_only(repo, base_sha, head_sha)
    assert len(violations) == 2
    assert {v.row_index for v in violations} == {1, 2}
    assert main(["--repo", str(repo), "--base", base_sha, "--head", head_sha]) == 1


def test_unreadable_base_ref_fails_closed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo, head_sha = _create_base_repo(tmp_path)
    missing_sha = "0000000000000000000000000000000000000000"
    with pytest.raises(AppendOnlyCheckError):
        check_ledger_rows_append_only(repo, missing_sha, head_sha)
    exit_code = main(["--repo", str(repo), "--base", missing_sha, "--head", head_sha])
    assert exit_code == 2
    assert "error:" in capsys.readouterr().err


def test_diverged_base_advancing_ledger_does_not_false_positive(tmp_path: Path) -> None:
    repo, merge_base_sha = _create_base_repo(tmp_path)
    _git(repo, "checkout", "-b", "pr-branch", merge_base_sha)
    pr_pending = repo / "holon-knowledge" / "ledger" / "pending" / "plans" / "P-2.jsonl"
    pr_pending.parent.mkdir(parents=True)
    pr_pending.write_bytes(b'{"id":"P-2","pending":true}\n')
    pr_head_sha = _commit_all(repo, "pr appends pending fragment")

    _git(repo, "checkout", "-b", "base-branch", merge_base_sha)
    intents = repo / "holon-knowledge" / "ledger" / "intents.jsonl"
    intents.write_bytes(intents.read_bytes() + b'{"id":"I-99","v":99}\n')
    main_pending = repo / "holon-knowledge" / "ledger" / "pending" / "executions" / "E-99.jsonl"
    main_pending.parent.mkdir(parents=True)
    main_pending.write_bytes(b'{"id":"E-99","pending":true}\n')
    advanced_base_sha = _commit_all(repo, "main appends ledger row and pending fragment")

    assert check_ledger_rows_append_only(repo, advanced_base_sha, pr_head_sha) == []
    assert main(["--repo", str(repo), "--base", advanced_base_sha, "--head", pr_head_sha]) == 0

    _git(repo, "checkout", "pr-branch")
    intents.write_bytes(b'{"id":"I-1","v":9}\n{"id":"I-2","v":2}\n')
    bad_pr_head_sha = _commit_all(repo, "pr edits merge-base row")
    violations = check_ledger_rows_append_only(repo, advanced_base_sha, bad_pr_head_sha)
    assert len(violations) == 1
    assert violations[0].path == "holon-knowledge/ledger/intents.jsonl"
    assert violations[0].row_index == 1


def test_unrelated_histories_fail_closed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo, base_sha = _create_base_repo(tmp_path)
    _git(repo, "checkout", "--orphan", "orphan-branch")
    (repo / "holon-knowledge" / "ledger" / "intents.jsonl").write_bytes(b'{"id":"I-1","v":1}\n')
    orphan_sha = _commit_all(repo, "orphan commit")
    with pytest.raises(AppendOnlyCheckError):
        check_ledger_rows_append_only(repo, base_sha, orphan_sha)
    exit_code = main(["--repo", str(repo), "--base", base_sha, "--head", orphan_sha])
    assert exit_code == 2
    assert "error:" in capsys.readouterr().err
