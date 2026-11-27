from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from tests.test_repo_self_doc import _find_yaml_comment_violations

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_REL_PATH = ".github/workflows/promote-ledger.yml"
WORKFLOW_PATH = REPO_ROOT / WORKFLOW_REL_PATH

GIT_IDENTITY_ENV = {
    "GIT_AUTHOR_NAME": "Test Runner",
    "GIT_AUTHOR_EMAIL": "test-runner@example.com",
    "GIT_COMMITTER_NAME": "Test Runner",
    "GIT_COMMITTER_EMAIL": "test-runner@example.com",
}


def _load_workflow() -> dict[str, Any]:
    parser = YAML(typ="safe")
    loaded = parser.load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _step_by_id(workflow: dict[str, Any], step_id: str) -> dict[str, Any]:
    steps = workflow["jobs"]["promote-ledger"]["steps"]
    for step in steps:
        if step.get("id") == step_id:
            return step
    raise AssertionError(f"Step id {step_id!r} not found in workflow")


def _run_step_script(
    script: str,
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(GIT_IDENTITY_ENV)
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )


def _init_temp_git_repo(tmp_path: Path) -> tuple[Path, Path]:
    bare = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    bare.mkdir()
    repo.mkdir()

    _git(bare, "init", "--bare", "-b", "main")
    _git(repo, "init", "-b", "main")
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "config", "user.name", "Test Runner")
    _git(repo, "config", "user.email", "test-runner@example.com")

    ledger_dir = repo / "holon-knowledge" / "ledger"
    ledger_dir.mkdir(parents=True)
    (ledger_dir / "intents.jsonl").write_bytes(b'{"id":  "I-1", "label": "caf\xc3\xa9"}\n')
    (ledger_dir / "plans.jsonl").write_bytes(b'{"id": "P-1", "note": "no-trailing-nl"}')
    (ledger_dir / "executions.jsonl").write_bytes(b'{"id": "E-1", "status": "ok"}\n')
    (repo / "README.md").write_text("initial\n", encoding="utf-8")

    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial commit")
    _git(repo, "push", "origin", "main")
    return repo, bare


def test_workflow_triggers_and_guards() -> None:
    raw_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    workflow = _load_workflow()
    triggers = workflow["on"]

    assert triggers["push"]["branches"] == ["main"]
    assert triggers["push"]["paths"] == ["holon-knowledge/ledger/pending/**"]
    assert isinstance(triggers["schedule"], list)
    assert isinstance(triggers["schedule"][0]["cron"], str)
    assert triggers["workflow_dispatch"]["inputs"]["force"]["type"] == "boolean"

    assert workflow["concurrency"]["cancel-in-progress"] is False
    assert workflow["permissions"]["contents"] == "write"

    job = workflow["jobs"]["promote-ledger"]
    assert "[ledger-promote]" in job["if"]
    assert "secrets.HOLON_LEDGER_BOT_TOKEN" in raw_text

    timing_steps = [step for step in job["steps"] if step.get("uses") == "./.github/actions/ci-timing-gate"]
    assert [step["with"]["phase"] for step in timing_steps] == ["start", "check"]
    assert timing_steps[1]["if"] == "always()"
    assert timing_steps[1]["with"]["max-seconds"] == "300"


def test_workflow_has_no_yaml_comments() -> None:
    source = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert _find_yaml_comment_violations(source, WORKFLOW_REL_PATH) == []


def test_missing_token_emits_warning_when_pending_fragments_exist(tmp_path: Path) -> None:
    workflow = _load_workflow()
    script = _step_by_id(workflow, "missing-token")["run"]
    summary_file = tmp_path / "summary.md"

    for category in ("intents", "plans", "executions"):
        pending_dir = tmp_path / "holon-knowledge" / "ledger" / "pending" / category
        pending_dir.mkdir(parents=True)
        (pending_dir / f"{category}-1.jsonl").write_text('{"id": "1"}\n', encoding="utf-8")

    result = _run_step_script(
        script,
        cwd=tmp_path,
        extra_env={
            "HOLON_LEDGER_BOT_TOKEN": "",
            "GITHUB_STEP_SUMMARY": str(summary_file),
        },
    )

    assert result.returncode == 0, result.stderr
    assert "::warning::" in result.stdout
    assert "3 pending ledger" in result.stdout
    assert "::notice::" not in result.stdout
    summary_text = summary_file.read_text(encoding="utf-8")
    assert "3" in summary_text
    assert "HOLON_LEDGER_BOT_TOKEN" in summary_text


def test_missing_token_emits_notice_when_no_pending_fragments(tmp_path: Path) -> None:
    workflow = _load_workflow()
    script = _step_by_id(workflow, "missing-token")["run"]
    summary_file = tmp_path / "summary.md"
    (tmp_path / "holon-knowledge" / "ledger" / "pending").mkdir(parents=True)

    result = _run_step_script(
        script,
        cwd=tmp_path,
        extra_env={
            "HOLON_LEDGER_BOT_TOKEN": "",
            "GITHUB_STEP_SUMMARY": str(summary_file),
        },
    )

    assert result.returncode == 0, result.stderr
    assert "::notice::" in result.stdout
    assert "0 pending ledger" in result.stdout
    assert "::warning::" not in result.stdout
    summary_text = summary_file.read_text(encoding="utf-8")
    assert "0" in summary_text
    assert "HOLON_LEDGER_BOT_TOKEN" in summary_text


def test_promotion_preserves_canonical_bytes_deduplicates_and_commits(tmp_path: Path) -> None:
    workflow = _load_workflow()
    promote_script = _step_by_id(workflow, "promote")["run"]
    commit_script = _step_by_id(workflow, "commit-push")["run"]

    repo, bare = _init_temp_git_repo(tmp_path)
    ledger_dir = repo / "holon-knowledge" / "ledger"
    original_bytes = {
        category: (ledger_dir / f"{category}.jsonl").read_bytes() for category in ("intents", "plans", "executions")
    }

    pending_payloads = {
        "intents": (
            b'{"id":  "I-1", "label": "caf\xc3\xa9"}\n{"id": "I-2", "label": "new"}\n{"id": "I-2", "label": "new"}\n'
        ),
        "plans": b'{"id": "P-1", "note": "no-trailing-nl"}\n{"id": "P-2"}\n',
        "executions": b'{"id": "E-2", "status": "ok"}\n',
    }
    for category, payload in pending_payloads.items():
        pending_dir = ledger_dir / "pending" / category
        pending_dir.mkdir(parents=True)
        (pending_dir / "frag-1.jsonl").write_bytes(payload)

    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "add pending fragments")
    _git(repo, "push", "origin", "main")

    summary_file = tmp_path / "summary.md"
    promote_result = _run_step_script(
        promote_script,
        cwd=repo,
        extra_env={
            "HOLON_LEDGER_BOT_TOKEN": "test-token",
            "FORCE_PROMOTE": "false",
            "GITHUB_STEP_SUMMARY": str(summary_file),
        },
    )
    assert promote_result.returncode == 0, promote_result.stderr

    commit_result = _run_step_script(
        commit_script,
        cwd=repo,
        extra_env={"HOLON_LEDGER_BOT_TOKEN": "test-token"},
    )
    assert commit_result.returncode == 0, commit_result.stderr

    for category, original in original_bytes.items():
        updated = (ledger_dir / f"{category}.jsonl").read_bytes()
        assert updated.startswith(original)
        assert list((ledger_dir / "pending" / category).glob("*.jsonl")) == []

    assert (ledger_dir / "intents.jsonl").read_bytes().splitlines() == [
        b'{"id":  "I-1", "label": "caf\xc3\xa9"}',
        b'{"id": "I-2", "label": "new"}',
    ]
    assert (ledger_dir / "plans.jsonl").read_bytes().splitlines() == [
        b'{"id": "P-1", "note": "no-trailing-nl"}',
        b'{"id": "P-2"}',
    ]
    assert (ledger_dir / "executions.jsonl").read_bytes().splitlines() == [
        b'{"id": "E-1", "status": "ok"}',
        b'{"id": "E-2", "status": "ok"}',
    ]

    commit_subject = _git(repo, "log", "-1", "--pretty=%s").stdout.strip()
    assert "[ledger-promote]" in commit_subject

    changed_paths = [
        line for line in _git(repo, "show", "--name-only", "--pretty=format:", "HEAD").stdout.splitlines() if line
    ]
    assert changed_paths
    assert all(path.startswith("holon-knowledge/ledger/") for path in changed_paths)

    local_head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    remote_head = _git(bare, "rev-parse", "refs/heads/main").stdout.strip()
    assert local_head == remote_head


def test_commit_guard_rejects_changes_outside_ledger(tmp_path: Path) -> None:
    workflow = _load_workflow()
    commit_script = _step_by_id(workflow, "commit-push")["run"]
    repo, _bare = _init_temp_git_repo(tmp_path)

    head_before = _git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / "README.md").write_text("unauthorized change\n", encoding="utf-8")

    result = _run_step_script(
        commit_script,
        cwd=repo,
        extra_env={"HOLON_LEDGER_BOT_TOKEN": "test-token"},
    )

    assert result.returncode != 0
    assert "::error::" in result.stdout
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == head_before


def test_promotion_keeps_pending_fragments_on_parse_error(tmp_path: Path) -> None:
    workflow = _load_workflow()
    promote_script = _step_by_id(workflow, "promote")["run"]
    repo, _bare = _init_temp_git_repo(tmp_path)
    ledger_dir = repo / "holon-knowledge" / "ledger"
    original_intents = (ledger_dir / "intents.jsonl").read_bytes()

    pending_dir = ledger_dir / "pending" / "intents"
    pending_dir.mkdir(parents=True)
    first_fragment = pending_dir / "01-valid.jsonl"
    second_fragment = pending_dir / "02-invalid.jsonl"
    first_fragment.write_bytes(b'{"id": "I-2"}\n')
    second_fragment.write_bytes(b"not-valid-json\n")

    result = _run_step_script(
        promote_script,
        cwd=repo,
        extra_env={"HOLON_LEDGER_BOT_TOKEN": "test-token", "FORCE_PROMOTE": "false"},
    )

    assert result.returncode != 0
    assert first_fragment.exists()
    assert second_fragment.exists()
    assert (ledger_dir / "intents.jsonl").read_bytes() == original_intents


def test_commit_guard_allows_non_ascii_ledger_paths(tmp_path: Path) -> None:
    workflow = _load_workflow()
    promote_script = _step_by_id(workflow, "promote")["run"]
    commit_script = _step_by_id(workflow, "commit-push")["run"]
    repo, _bare = _init_temp_git_repo(tmp_path)
    ledger_dir = repo / "holon-knowledge" / "ledger"

    pending_dir = ledger_dir / "pending" / "intents"
    pending_dir.mkdir(parents=True)
    (pending_dir / "café fragment.jsonl").write_bytes(b'{"id": "I-3"}\n')

    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "add non-ascii pending fragment")
    _git(repo, "push", "origin", "main")

    promote_result = _run_step_script(
        promote_script,
        cwd=repo,
        extra_env={"HOLON_LEDGER_BOT_TOKEN": "test-token", "FORCE_PROMOTE": "false"},
    )
    assert promote_result.returncode == 0, promote_result.stderr

    commit_result = _run_step_script(
        commit_script,
        cwd=repo,
        extra_env={"HOLON_LEDGER_BOT_TOKEN": "test-token"},
    )
    assert commit_result.returncode == 0, commit_result.stderr
    assert list(pending_dir.glob("*.jsonl")) == []
