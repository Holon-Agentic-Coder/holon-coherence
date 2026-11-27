from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_commit_trailers.py"
HOOK_PATH = REPO_ROOT / ".githooks" / "commit-msg"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "test-commit-trailers.yml"


def _load_checker_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_commit_trailers", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHECKER = _load_checker_module()


def _run_cli(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        check=False,
    )


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    return env


def _run_git(repo_dir: Path, args: list[str]) -> str:
    result = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", f"core.hooksPath={os.devnull}", *args],
        capture_output=True,
        text=True,
        cwd=repo_dir,
        env=_git_env(),
        check=True,
    )
    return result.stdout.strip()


@pytest.mark.parametrize(
    "trailer",
    [
        "Co-Authored-By: Claude <noreply@anthropic.com>",
        "co-authored-by: claude <noreply@anthropic.com>",
        "  Co-Developed-By: Assistant <bot@example.com>",
        "Generated-By: Agent",
        "assisted-by: tool",
        "Generated with [Claude Code](https://claude.com/claude-code)",
        "   generated with [claude code](https://claude.com/claude-code)",
    ],
)
def test_find_attribution_lines_rejects_forbidden_trailers(trailer: str) -> None:
    message = f"feat: update\n\n{trailer}\n"
    assert CHECKER.find_attribution_lines(message) == [trailer]


def test_find_attribution_lines_ignores_git_comments_and_allows_flow_trailers() -> None:
    message = (
        "feat: enforce commit trailer policy\n"
        "\n"
        "# Co-Authored-By: Claude <noreply@anthropic.com>\n"
        "  # Generated-By: Agent\n"
        "Action-Origin: pr_review\n"
        "Review-Iteration: 2\n"
    )
    assert CHECKER.find_attribution_lines(message) == []


def test_repo_scripts_do_not_embed_attribution_trailers() -> None:
    for script in sorted((REPO_ROOT / "scripts").glob("*.py")):
        if script == SCRIPT_PATH:
            continue
        source = script.read_text(encoding="utf-8")
        assert CHECKER.find_attribution_lines(source) == []


@pytest.mark.parametrize(
    ("message", "expected_fragment"),
    [
        (
            "feat: x\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n",
            "Co-Authored-By: Claude <noreply@anthropic.com>",
        ),
        (
            "feat: x\n\nco-authored-by: claude <noreply@anthropic.com>\n",
            "co-authored-by: claude <noreply@anthropic.com>",
        ),
        (
            "feat: x\n\nGenerated with [Claude Code](https://claude.com/claude-code)\n",
            "Generated with [Claude Code](https://claude.com/claude-code)",
        ),
    ],
)
def test_cli_message_file_rejects_violations(tmp_path: Path, message: str, expected_fragment: str) -> None:
    msg_file = tmp_path / "COMMIT_EDITMSG"
    msg_file.write_text(message, encoding="utf-8")
    result = _run_cli(["--message-file", str(msg_file)])
    assert result.returncode != 0
    assert expected_fragment in result.stderr


def test_cli_message_file_accepts_clean_flow_trailers(tmp_path: Path) -> None:
    msg_file = tmp_path / "COMMIT_EDITMSG"
    msg_file.write_text(
        "fix: handle review feedback\n\nAction-Origin: pr_review\nReview-Iteration: 2\n",
        encoding="utf-8",
    )
    result = _run_cli(["--message-file", str(msg_file)])
    assert result.returncode == 0
    assert result.stderr == ""


def test_cli_range_reports_only_violating_commits(tmp_path: Path) -> None:
    _run_git(tmp_path, ["init"])
    _run_git(tmp_path, ["config", "user.name", "Test Author"])
    _run_git(tmp_path, ["config", "user.email", "test@example.com"])

    target = tmp_path / "notes.txt"
    target.write_text("base\n", encoding="utf-8")
    _run_git(tmp_path, ["add", "notes.txt"])
    _run_git(tmp_path, ["commit", "-m", "chore: base"])
    base_sha = _run_git(tmp_path, ["rev-parse", "HEAD"])

    target.write_text("clean\n", encoding="utf-8")
    _run_git(tmp_path, ["commit", "-am", "feat: clean\n\nAction-Origin: pr_review\nReview-Iteration: 2"])
    clean_sha = _run_git(tmp_path, ["rev-parse", "HEAD"])
    clean_short = _run_git(tmp_path, ["rev-parse", "--short", clean_sha])

    target.write_text("bad\n", encoding="utf-8")
    _run_git(
        tmp_path,
        ["commit", "-am", "feat: bad\n\nCo-Authored-By: Claude <noreply@anthropic.com>"],
    )
    bad_sha = _run_git(tmp_path, ["rev-parse", "HEAD"])
    bad_short = _run_git(tmp_path, ["rev-parse", "--short", bad_sha])

    bad_result = _run_cli(["--range", f"{base_sha}..{bad_sha}"], cwd=tmp_path)
    assert bad_result.returncode != 0
    assert bad_short in bad_result.stderr
    assert clean_short not in bad_result.stderr
    assert "Co-Authored-By: Claude <noreply@anthropic.com>" in bad_result.stderr

    clean_result = _run_cli(["--range", f"{base_sha}..{clean_sha}"], cwd=tmp_path)
    assert clean_result.returncode == 0
    assert clean_result.stderr == ""


def test_githook_is_executable_and_enforces_checker(tmp_path: Path) -> None:
    assert HOOK_PATH.is_file()
    mode = HOOK_PATH.stat().st_mode
    assert bool(mode & stat.S_IXUSR)
    assert os.access(HOOK_PATH, os.X_OK)

    hook_text = HOOK_PATH.read_text(encoding="utf-8")
    assert "scripts/check_commit_trailers.py" in hook_text
    assert "--message-file" in hook_text

    bad_msg = tmp_path / "BAD_MSG"
    bad_msg.write_text("feat: x\n\nCo-Authored-By: Claude <noreply@anthropic.com>\n", encoding="utf-8")
    bad_run = subprocess.run([str(HOOK_PATH), str(bad_msg)], capture_output=True, text=True, cwd=REPO_ROOT, check=False)
    assert bad_run.returncode != 0
    assert "Co-Authored-By: Claude <noreply@anthropic.com>" in bad_run.stderr

    clean_msg = tmp_path / "CLEAN_MSG"
    clean_msg.write_text("feat: x\n\nAction-Origin: pr_review\n", encoding="utf-8")
    clean_run = subprocess.run(
        [str(HOOK_PATH), str(clean_msg)], capture_output=True, text=True, cwd=REPO_ROOT, check=False
    )
    assert clean_run.returncode == 0


def test_ci_workflow_runs_commit_trailer_range_check() -> None:
    assert WORKFLOW_PATH.is_file()
    raw = WORKFLOW_PATH.read_text(encoding="utf-8")
    lines = [line.strip() for line in raw.splitlines()]
    assert "pull_request:" in lines
    assert "fetch-depth: 0" in lines
    assert any(line.startswith("uses:") and "actions/checkout@" in line for line in lines)
    assert any("scripts/check_commit_trailers.py" in line and "--range" in line for line in lines)
