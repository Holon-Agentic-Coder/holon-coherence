from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import check_no_harness_references as checker
from scripts.harness_reference_patterns import scan_text

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_no_harness_references.py"
PATTERNS_PATH = REPO_ROOT / "scripts" / "harness_reference_patterns.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "test-no-harness-references.yml"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit_file(repo: Path, rel_path: str, content: str, message: str) -> str:
    target = repo / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git(repo, "add", rel_path)
    _git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    return repo


def _run_cli(args: list[str], env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _sample_task_dir() -> str:
    return "." + "be" + "ans/0001.md"


def _sample_agent_dir() -> str:
    return "." + "sub" + "agent/state.json"


def _sample_scratch_dir() -> str:
    return "to" + "do/wire_logs"


def _sample_task_id() -> str:
    return "Be" + "an-0129"


@pytest.mark.parametrize(
    ("pattern_name", "token"),
    [
        ("task_tracking_dir", _sample_task_dir()),
        ("agent_instruction_dir", _sample_agent_dir()),
        ("scratch_dir", _sample_scratch_dir()),
        ("four_digit_task_id", _sample_task_id()),
    ],
)
def test_diff_mode_fails_on_added_reference_line(tmp_path: Path, pattern_name: str, token: str) -> None:
    repo = _init_repo(tmp_path)
    base = _commit_file(repo, "notes.txt", "line one\nline two\n", "base")
    head = _commit_file(repo, "notes.txt", f"line one\nline two\nsee {token}\n", "add ref")

    result = _run_cli(["diff", "--repo", str(repo), "--base", base, "--head", head])
    assert result.returncode == 1
    assert f"notes.txt:3: [{pattern_name}]" in result.stdout


def test_diff_mode_tracks_line_numbers_with_plus_prefix_content(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    base = _commit_file(repo, "doc.txt", "a\nb\nc\nd\ne\n", "base")
    updated = f"a\n++ marker\nb\nc\nd\ne\nref {_sample_task_id()}\n"
    head = _commit_file(repo, "doc.txt", updated, "multi hunk")

    result = _run_cli(["diff", "--repo", str(repo), "--base", base, "--head", head])
    assert result.returncode == 1
    assert "doc.txt:7: [four_digit_task_id]" in result.stdout


def test_diff_mode_fails_on_pr_body_flag_and_env_and_file(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    base = _commit_file(repo, "app.py", "x = 1\n", "base")
    head = _commit_file(repo, "app.py", "x = 2\n", "clean change")
    body = f"Summary\nTracks {_sample_task_dir()}\n"

    flag_res = _run_cli(["diff", "--repo", str(repo), "--base", base, "--head", head, "--pr-body", body])
    assert flag_res.returncode == 1
    assert "PR_BODY:2: [task_tracking_dir]" in flag_res.stdout

    env_res = _run_cli(
        ["diff", "--repo", str(repo), "--base", base, "--head", head, "--pr-body-env", "TEST_PR_BODY"],
        env_extra={"TEST_PR_BODY": body},
    )
    assert env_res.returncode == 1
    assert "PR_BODY:2: [task_tracking_dir]" in env_res.stdout

    body_file = tmp_path / "pr_body.md"
    body_file.write_text(body, encoding="utf-8")
    file_res = _run_cli(["diff", "--repo", str(repo), "--base", base, "--head", head, "--pr-body-file", str(body_file)])
    assert file_res.returncode == 1
    assert "PR_BODY:2: [task_tracking_dir]" in file_res.stdout


def test_diff_mode_passes_on_clean_diff_and_benign_body(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    base = _commit_file(repo, "readme.txt", "initial\n", "base")
    head = _commit_file(
        repo,
        "readme.txt",
        "initial\nsee .beads/ and .agents/AGENTS.md for the " + "to" + "do list\n",
        "clean",
    )

    result = _run_cli(
        [
            "diff",
            "--repo",
            str(repo),
            "--base",
            base,
            "--head",
            head,
            "--pr-body",
            "Clean PR referencing .beads/issues.jsonl and 2048 beans in jars.",
        ]
    )
    assert result.returncode == 0
    assert result.stdout == ""


def test_diff_mode_ignores_removed_lines(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    base = _commit_file(repo, "legacy.txt", f"keep\nold {_sample_agent_dir()}\n", "base with legacy ref")
    head = _commit_file(repo, "legacy.txt", "keep\nclean replacement\n", "remove legacy ref")

    result = _run_cli(["diff", "--repo", str(repo), "--base", base, "--head", head])
    assert result.returncode == 0
    assert result.stdout == ""


def test_diff_mode_fails_closed_on_unreadable_diff_and_inputs(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    base = _commit_file(repo, "a.txt", "ok\n", "base")

    bad_ref = _run_cli(["diff", "--repo", str(repo), "--base", base, "--head", "deadbeefdeadbeef"])
    assert bad_ref.returncode == 2
    assert "error:" in bad_ref.stderr

    non_git = tmp_path / "not_a_repo"
    non_git.mkdir()
    not_repo = _run_cli(["diff", "--repo", str(non_git), "--base", "HEAD~1", "--head", "HEAD"])
    assert not_repo.returncode == 2
    assert "error:" in not_repo.stderr

    missing_body = _run_cli(
        ["diff", "--repo", str(repo), "--base", base, "--head", base, "--pr-body-file", str(tmp_path / "missing.md")]
    )
    assert missing_body.returncode == 2
    assert "error:" in missing_body.stderr


def test_tree_mode_reports_matching_files_and_lines(tmp_path: Path) -> None:
    tree_root = tmp_path / "sample_tree"
    tree_root.mkdir()
    (tree_root / "clean.txt").write_text("benign .beads/ text\n", encoding="utf-8")
    (tree_root / "binary.bin").write_bytes(b"\x00\x01" + _sample_task_dir().encode("utf-8"))
    (tree_root / "sub").mkdir()
    (tree_root / "sub" / "hit.txt").write_text(f"line 1\nfound {_sample_scratch_dir()}\n", encoding="utf-8")

    result = _run_cli(["tree", "--root", str(tree_root)])
    assert result.returncode == 1
    assert "sub/hit.txt:2: [scratch_dir]" in result.stdout
    assert "binary.bin" not in result.stdout
    assert "clean.txt" not in result.stdout

    clean_root = tmp_path / "clean_tree"
    clean_root.mkdir()
    (clean_root / "ok.txt").write_text("all clear\n", encoding="utf-8")
    clean_result = _run_cli(["tree", "--root", str(clean_root)])
    assert clean_result.returncode == 0
    assert clean_result.stdout == ""

    missing_result = _run_cli(["tree", "--root", str(tmp_path / "does_not_exist")])
    assert missing_result.returncode == 2
    assert "error:" in missing_result.stderr


def test_new_files_have_zero_self_matches_and_single_pattern_source() -> None:
    for path in (PATTERNS_PATH, SCRIPT_PATH, Path(__file__), WORKFLOW_PATH):
        content = path.read_text(encoding="utf-8")
        assert scan_text(content, path.as_posix()) == [], f"Unexpected self-match in {path}"
    assert "harness_reference_patterns" in SCRIPT_PATH.read_text(encoding="utf-8")
    assert checker.scan_text is scan_text


def test_workflow_contract_wiring() -> None:
    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "pull_request:" in content
    assert "edited" in content
    assert "fetch-depth: 0" in content
    assert "scripts/check_no_harness_references.py diff" in content
    assert "PR_BODY: ${{ github.event.pull_request.body }}" in content
    assert "--pr-body-env PR_BODY" in content
