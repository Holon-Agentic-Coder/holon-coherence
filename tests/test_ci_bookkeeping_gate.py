from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from scripts.ci_bookkeeping_api import (
    CheckRunInfo,
    CommitInfo,
    CompareResult,
    GitHubApiError,
    GitHubBookkeepingClient,
)
from scripts.ci_bookkeeping_gate import (
    MAX_CHAIN_DEPTH,
    MAX_COMPARE_FILES,
    all_bookkeeping_files,
    evaluate_gate,
    is_bookkeeping_path,
    main,
    verify_green_ancestor_chain,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECK_NAME = "unit (ubuntu-latest)"


class FakeBookkeepingClient:
    def __init__(
        self,
        compares: dict[tuple[str, str], CompareResult | Exception] | None = None,
        commits: dict[str, CommitInfo | Exception] | None = None,
        check_runs: dict[str, tuple[CheckRunInfo, ...] | Exception] | None = None,
    ) -> None:
        self._compares = compares or {}
        self._commits = commits or {}
        self._check_runs = check_runs or {}

    def compare_commits(self, before: str, after: str) -> CompareResult:
        result = self._compares[(before, after)]
        if isinstance(result, Exception):
            raise result
        return result

    def get_commit(self, sha: str) -> CommitInfo:
        result = self._commits[sha]
        if isinstance(result, Exception):
            raise result
        return result

    def list_check_runs(self, sha: str, check_name: str) -> tuple[CheckRunInfo, ...]:
        result = self._check_runs.get(sha, ())
        if isinstance(result, Exception):
            raise result
        return result


def _green_runs(name: str = CHECK_NAME) -> tuple[CheckRunInfo, ...]:
    return (CheckRunInfo(name=name, status="completed", conclusion="success"),)


def _pr_env(**overrides: str) -> dict[str, str]:
    base = {
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_RUN_ATTEMPT": "1",
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "path",
    [
        "plans/foo.md",
        "plans/I-1/P-1.md",
        "executions/E-1.md",
        "holon-knowledge/ledger/plans.jsonl",
        "holon-knowledge/kb/patterns/p.json",
    ],
)
def test_is_bookkeeping_path_allows_valid_paths(path: str) -> None:
    assert is_bookkeeping_path(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "",
        "src/holon_coherence/cli.py",
        "scripts/ci_bookkeeping_gate.py",
        "plans/script.py",
        "plans/notes.txt",
        "docs/readme.md",
        "../plans/a.md",
        "plans/../src/a.md",
        "/plans/a.md",
        "plans\\a.md",
        "holon-config/hygiene/module_budgets.json",
    ],
)
def test_is_bookkeeping_path_rejects_disallowed_paths(path: str) -> None:
    assert is_bookkeeping_path(path) is False


def test_all_bookkeeping_files_handles_renames_empty_and_truncation() -> None:
    assert all_bookkeeping_files((("plans/b.md", "plans/a.md"),)) is True
    assert all_bookkeeping_files((("plans/b.md", "src/a.py"),)) is False
    assert all_bookkeeping_files((("src/b.py", "plans/a.md"),)) is False
    assert all_bookkeeping_files(()) is False
    truncated = tuple((f"plans/f{idx}.md", None) for idx in range(MAX_COMPARE_FILES))
    assert all_bookkeeping_files(truncated) is False


def test_evaluate_gate_skips_bookkeeping_synchronize_with_green_ancestor() -> None:
    client = FakeBookkeepingClient(
        compares={("c0", "c1"): CompareResult(status="ahead", files=(("plans/p1.md", None),))},
        commits={"c0": CommitInfo(sha="c0", parents=("root",), files=(("src/app.py", None),))},
        check_runs={"c0": _green_runs()},
    )
    event = {"action": "synchronize", "before": "c0", "after": "c1"}
    decision = evaluate_gate(event, _pr_env(), client, CHECK_NAME)
    assert decision.skip is True
    assert "c0" in decision.reason


def test_evaluate_gate_runs_on_non_bookkeeping_synchronize() -> None:
    client = FakeBookkeepingClient(
        compares={("c0", "c1"): CompareResult(status="ahead", files=(("plans/p1.md", None), ("src/app.py", None)))},
        commits={"c0": CommitInfo(sha="c0", parents=("root",), files=(("src/app.py", None),))},
        check_runs={"c0": _green_runs()},
    )
    event = {"action": "synchronize", "before": "c0", "after": "c1"}
    decision = evaluate_gate(event, _pr_env(), client, CHECK_NAME)
    assert decision.skip is False


@pytest.mark.parametrize("status", ["diverged", "behind", "identical", "unknown"])
def test_evaluate_gate_fails_closed_on_non_ahead_compare_status(status: str) -> None:
    client = FakeBookkeepingClient(
        compares={("c0", "c1"): CompareResult(status=status, files=(("plans/p1.md", None),))},
        commits={"c0": CommitInfo(sha="c0", parents=("root",), files=(("src/app.py", None),))},
        check_runs={"c0": _green_runs()},
    )
    event = {"action": "synchronize", "before": "c0", "after": "c1"}
    decision = evaluate_gate(event, _pr_env(), client, CHECK_NAME)
    assert decision.skip is False


def test_evaluate_gate_rejects_non_pr_unsupported_action_and_reruns() -> None:
    client = FakeBookkeepingClient()
    sync_event = {"action": "synchronize", "before": "c0", "after": "c1"}
    assert evaluate_gate(sync_event, _pr_env(GITHUB_EVENT_NAME="push"), client, CHECK_NAME).skip is False
    assert evaluate_gate(sync_event, _pr_env(GITHUB_EVENT_NAME="workflow_dispatch"), client, CHECK_NAME).skip is False
    assert evaluate_gate(sync_event, _pr_env(GITHUB_RUN_ATTEMPT="2"), client, CHECK_NAME).skip is False
    assert evaluate_gate({"action": "opened"}, _pr_env(), client, CHECK_NAME).skip is False
    assert evaluate_gate({"action": "reopened"}, _pr_env(), client, CHECK_NAME).skip is False


@pytest.mark.parametrize("action", ["labeled", "unlabeled"])
def test_evaluate_gate_label_events_respect_result_affecting_labels(action: str) -> None:
    client = FakeBookkeepingClient(
        commits={"c0": CommitInfo(sha="c0", parents=("root",), files=(("src/app.py", None),))},
        check_runs={"c0": _green_runs()},
    )
    benign = {"action": action, "label": {"name": "documentation"}, "pull_request": {"head": {"sha": "c0"}}}
    assert evaluate_gate(benign, _pr_env(), client, CHECK_NAME).skip is True

    for label in ("module-budget-change", "ci-timing-override", "timing-regression-accepted"):
        sensitive = {"action": action, "label": {"name": label}, "pull_request": {"head": {"sha": "c0"}}}
        assert evaluate_gate(sensitive, _pr_env(), client, CHECK_NAME).skip is False


def test_chain_traversal_walks_consecutive_bookkeeping_commits() -> None:
    client = FakeBookkeepingClient(
        compares={("c2", "c3"): CompareResult(status="ahead", files=(("executions/e3.md", None),))},
        commits={
            "c2": CommitInfo(sha="c2", parents=("c1",), files=(("executions/e2.md", None),)),
            "c1": CommitInfo(sha="c1", parents=("c0",), files=(("plans/p1.md", None),)),
            "c0": CommitInfo(sha="c0", parents=("root",), files=(("src/app.py", None),)),
        },
        check_runs={"c2": _green_runs(), "c1": _green_runs(), "c0": _green_runs()},
    )
    decision = evaluate_gate({"action": "synchronize", "before": "c2", "after": "c3"}, _pr_env(), client, CHECK_NAME)
    assert decision.skip is True
    assert "c0" in decision.reason


def test_chain_traversal_fails_closed_on_failed_base_merge_or_depth() -> None:
    failed_base = FakeBookkeepingClient(
        commits={
            "c1": CommitInfo(sha="c1", parents=("c0",), files=(("plans/p1.md", None),)),
            "c0": CommitInfo(sha="c0", parents=("root",), files=(("src/app.py", None),)),
        },
        check_runs={
            "c1": _green_runs(),
            "c0": (CheckRunInfo(name=CHECK_NAME, status="completed", conclusion="failure"),),
        },
    )
    assert verify_green_ancestor_chain(failed_base, "c1", CHECK_NAME).skip is False

    merge_client = FakeBookkeepingClient(
        commits={"c1": CommitInfo(sha="c1", parents=("c0", "other"), files=(("plans/p1.md", None),))},
        check_runs={"c1": _green_runs()},
    )
    assert verify_green_ancestor_chain(merge_client, "c1", CHECK_NAME).skip is False

    deep_commits = {
        f"c{i}": CommitInfo(sha=f"c{i}", parents=(f"c{i - 1}",), files=(("plans/p.md", None),))
        for i in range(1, MAX_CHAIN_DEPTH + 3)
    }
    deep_runs = {sha: _green_runs() for sha in deep_commits}
    deep_client = FakeBookkeepingClient(commits=deep_commits, check_runs=deep_runs)
    assert verify_green_ancestor_chain(deep_client, f"c{MAX_CHAIN_DEPTH + 2}", CHECK_NAME).skip is False


def test_evaluate_gate_fails_closed_on_api_errors() -> None:
    compare_err = FakeBookkeepingClient(compares={("c0", "c1"): GitHubApiError("boom")})
    assert (
        evaluate_gate({"action": "synchronize", "before": "c0", "after": "c1"}, _pr_env(), compare_err, CHECK_NAME).skip
        is False
    )

    runs_err = FakeBookkeepingClient(
        compares={("c0", "c1"): CompareResult(status="ahead", files=(("plans/p1.md", None),))},
        check_runs={"c0": GitHubApiError("rate limited")},
    )
    assert (
        evaluate_gate({"action": "synchronize", "before": "c0", "after": "c1"}, _pr_env(), runs_err, CHECK_NAME).skip
        is False
    )

    commit_err = FakeBookkeepingClient(
        compares={("c0", "c1"): CompareResult(status="ahead", files=(("plans/p1.md", None),))},
        check_runs={"c0": _green_runs()},
        commits={"c0": GitHubApiError("not found")},
    )
    assert (
        evaluate_gate({"action": "synchronize", "before": "c0", "after": "c1"}, _pr_env(), commit_err, CHECK_NAME).skip
        is False
    )


class _FakeHttpResponse(io.BytesIO):
    def __enter__(self) -> _FakeHttpResponse:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def test_github_client_parses_responses_and_wraps_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    responses: list[dict[str, Any]] = [
        {"status": "ahead", "files": [{"filename": "plans/a.md", "previous_filename": "plans/old.md"}]},
        {"sha": "c0", "parents": [{"sha": "root"}], "files": [{"filename": "src/a.py"}]},
        {"check_runs": [{"name": CHECK_NAME, "status": "completed", "conclusion": "success"}]},
    ]
    seen_urls: list[str] = []

    def fake_urlopen(req: urllib.request.Request, timeout: int = 15) -> _FakeHttpResponse:
        seen_urls.append(req.full_url)
        assert req.get_header("Authorization") == "Bearer tok"
        payload = json.dumps(responses.pop(0)).encode("utf-8")
        return _FakeHttpResponse(payload)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    client = GitHubBookkeepingClient(api_url="https://api.github.com", repo="org/repo", token="tok")
    cmp_res = client.compare_commits("c0", "c1")
    commit = client.get_commit("c0")
    runs = client.list_check_runs("c0", CHECK_NAME)

    assert cmp_res == CompareResult(status="ahead", files=(("plans/a.md", "plans/old.md"),))
    assert commit == CommitInfo(sha="c0", parents=("root",), files=(("src/a.py", None),))
    assert runs == (CheckRunInfo(name=CHECK_NAME, status="completed", conclusion="success"),)
    assert len(seen_urls) == 3

    def failing_urlopen(req: urllib.request.Request, timeout: int = 15) -> _FakeHttpResponse:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(urllib.request, "urlopen", failing_urlopen)
    with pytest.raises(GitHubApiError):
        client.compare_commits("c0", "c1")


def test_cli_main_writes_github_output_and_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out_file = tmp_path / "github_output.txt"
    event_file = tmp_path / "event.json"
    event_file.write_text(json.dumps({"action": "synchronize", "before": "c0", "after": "c1"}), encoding="utf-8")

    monkeypatch.setattr(
        "scripts.ci_bookkeeping_gate.GitHubBookkeepingClient",
        lambda api_url, repo, token: FakeBookkeepingClient(
            compares={("c0", "c1"): CompareResult(status="ahead", files=(("plans/p1.md", None),))},
            commits={"c0": CommitInfo(sha="c0", parents=("root",), files=(("src/app.py", None),))},
            check_runs={"c0": _green_runs()},
        ),
    )
    env = {
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_TOKEN": "tok",
        "GITHUB_REPOSITORY": "org/repo",
        "GITHUB_EVENT_PATH": str(event_file),
        "GITHUB_OUTPUT": str(out_file),
    }
    assert main(["--check-name", CHECK_NAME], env=env) == 0
    lines = out_file.read_text(encoding="utf-8").splitlines()
    assert "skip=true" in lines
    assert any(line.startswith("reason=") for line in lines)

    bad_out = tmp_path / "bad_output.txt"
    assert main(["--check-name", CHECK_NAME], env={"GITHUB_OUTPUT": str(bad_out)}) == 0
    assert "skip=false" in bad_out.read_text(encoding="utf-8").splitlines()

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{not json", encoding="utf-8")
    bad_json_out = tmp_path / "bad_json_output.txt"
    bad_env = dict(env, GITHUB_EVENT_PATH=str(malformed), GITHUB_OUTPUT=str(bad_json_out))
    assert main(["--check-name", CHECK_NAME], env=bad_env) == 0
    assert "skip=false" in bad_json_out.read_text(encoding="utf-8").splitlines()


def _extract_step_blocks(yaml_text: str) -> dict[str, str]:
    steps: dict[str, list[str]] = {}
    current_name: str | None = None
    for line in yaml_text.splitlines():
        stripped = line.lstrip()
        if line.startswith("      - name: "):
            current_name = stripped[len("- name: ") :].strip()
            steps[current_name] = [line]
        elif current_name is not None:
            steps[current_name].append(line)
    return {name: "\n".join(lines) for name, lines in steps.items()}


def test_composite_action_invokes_gate_script_and_exports_outputs() -> None:
    action_text = (REPO_ROOT / ".github/actions/bookkeeping-gate/action.yml").read_text(encoding="utf-8")
    assert "scripts/ci_bookkeeping_gate.py" in action_text
    assert "steps.gate.outputs.skip" in action_text
    assert "steps.gate.outputs.reason" in action_text


@pytest.mark.parametrize(
    ("workflow_rel", "expected_check_name", "required_gated_steps"),
    [
        (
            ".github/workflows/test-unit.yml",
            "unit (${{ matrix.os }})",
            (
                "Set up Miniconda",
                "Run unit tests",
                "CI timing gate (compare with main)",
                "CI Timing Gate (Check <= 5 min)",
            ),
        ),
        (
            ".github/workflows/test-integration.yml",
            "integration (${{ matrix.os }})",
            (
                "Set up Miniconda",
                "Build Docker image via make build-image",
                "Run integration tests",
                "CI timing gate (compare with main)",
            ),
        ),
        (
            ".github/workflows/test-hygiene.yml",
            "hygiene (${{ matrix.os }})",
            ("Set up Miniconda", "Lint with Ruff", "Check module line budgets", "CI timing gate (compare with main)"),
        ),
        (
            ".github/workflows/make.yml",
            "make (${{ matrix.os }})",
            (
                "Install Conda",
                "Install the conda environment",
                "Verify make check-prerequisites",
                "CI timing gate (compare with main)",
            ),
        ),
        (
            ".github/workflows/docker-build.yml",
            "docker-build",
            (
                "Set up QEMU",
                "Build Docker image via make build-image",
                "Verify Docker image",
                "CI timing gate (compare with main)",
            ),
        ),
    ],
)
def test_workflows_wire_bookkeeping_gate_and_permissions(
    workflow_rel: str,
    expected_check_name: str,
    required_gated_steps: tuple[str, ...],
) -> None:
    text = (REPO_ROOT / workflow_rel).read_text(encoding="utf-8")
    assert "checks: read" in text
    steps = _extract_step_blocks(text)
    assert "Bookkeeping-only PR gate" in steps
    gate_block = steps["Bookkeeping-only PR gate"]
    assert "id: bookkeeping_gate" in gate_block
    assert "uses: ./.github/actions/bookkeeping-gate" in gate_block
    assert f"check-name: {expected_check_name}" in gate_block
    for step_name in required_gated_steps:
        assert step_name in steps
        assert "steps.bookkeeping_gate.outputs.skip != 'true'" in steps[step_name]
