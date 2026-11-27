from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.check_ledger_stores import (
    StoreCheckError,
    check_ledger_store_paths,
    check_ledger_stores,
    main,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _seed_canonical_repo(root: Path) -> None:
    ledger_dir = root / "holon-knowledge" / "ledger"
    for name in ("intents", "plans", "executions"):
        path = ledger_dir / f"{name}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"id": "row-1"}\n', encoding="utf-8")
        pending = ledger_dir / "pending" / name / "item.jsonl"
        pending.parent.mkdir(parents=True, exist_ok=True)
        pending.write_text('{"id": "pending-1"}\n', encoding="utf-8")
    kb_file = root / "holon-knowledge" / "kb" / "notes.jsonl"
    kb_file.parent.mkdir(parents=True, exist_ok=True)
    kb_file.write_text('{"kb": true}\n', encoding="utf-8")
    kb_json = root / "holon-knowledge" / "kb" / "index.json"
    kb_json.write_text("{}\n", encoding="utf-8")


def _init_git_repo(root: Path) -> str:
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Test User",
            "-c",
            "user.email=test@example.com",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-m",
            "initial",
        ],
        check=True,
        capture_output=True,
    )
    sha = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return sha


def test_real_repository_layout_passes(capsys: pytest.CaptureFixture[str]) -> None:
    assert check_ledger_stores(REPO_ROOT) == []
    exit_code = main(["--repo", str(REPO_ROOT), "--base", "HEAD", "--head", "HEAD"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_canonical_temp_repo_with_kb_and_pending_passes(tmp_path: Path) -> None:
    _seed_canonical_repo(tmp_path)
    assert check_ledger_stores(tmp_path) == []
    assert main(["--repo", str(tmp_path)]) == 0


def test_fourth_ledger_store_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _seed_canonical_repo(tmp_path)
    extra = tmp_path / "holon-knowledge" / "ledger" / "extra.jsonl"
    extra.write_text('{"id": "extra"}\n', encoding="utf-8")
    violations = check_ledger_stores(tmp_path)
    assert any("holon-knowledge/ledger/extra.jsonl" in item for item in violations)
    assert main(["--repo", str(tmp_path)]) == 1
    assert "holon-knowledge/ledger/extra.jsonl" in capsys.readouterr().out


def test_stray_jsonl_outside_kb_and_fourth_pending_subdir_fail(tmp_path: Path) -> None:
    _seed_canonical_repo(tmp_path)
    stray = tmp_path / "holon-knowledge" / "other" / "extra.jsonl"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_text('{"stray": true}\n', encoding="utf-8")
    fourth_pending = tmp_path / "holon-knowledge" / "ledger" / "pending" / "other" / "x.jsonl"
    fourth_pending.parent.mkdir(parents=True, exist_ok=True)
    fourth_pending.write_text('{"fourth": true}\n', encoding="utf-8")
    violations = check_ledger_stores(tmp_path)
    assert any("holon-knowledge/other/extra.jsonl" in item for item in violations)
    assert any("holon-knowledge/ledger/pending/other/x.jsonl" in item for item in violations)


def test_missing_canonical_ledger_fails(tmp_path: Path) -> None:
    _seed_canonical_repo(tmp_path)
    (tmp_path / "holon-knowledge" / "ledger" / "plans.jsonl").unlink()
    violations = check_ledger_stores(tmp_path)
    assert any("holon-knowledge/ledger/plans.jsonl" in item for item in violations)


def test_unreadable_base_ref_fails_closed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _seed_canonical_repo(tmp_path)
    head_sha = _init_git_repo(tmp_path)
    with pytest.raises(StoreCheckError):
        check_ledger_stores(tmp_path, base="0000000000000000000000000000000000000000", head=head_sha)
    exit_code = main(
        [
            "--repo",
            str(tmp_path),
            "--base",
            "0000000000000000000000000000000000000000",
            "--head",
            head_sha,
        ]
    )
    assert exit_code == 2
    assert "error:" in capsys.readouterr().err


def test_check_ledger_store_paths_ignores_kb_and_rejects_pending_top_level() -> None:
    paths = [
        "holon-knowledge/ledger/intents.jsonl",
        "holon-knowledge/ledger/plans.jsonl",
        "holon-knowledge/ledger/executions.jsonl",
        "holon-knowledge/kb/nested/anything.jsonl",
        "holon-knowledge/ledger/pending/stray.jsonl",
    ]
    violations = check_ledger_store_paths(paths)
    assert len(violations) == 1
    assert "holon-knowledge/ledger/pending/stray.jsonl" in violations[0]
