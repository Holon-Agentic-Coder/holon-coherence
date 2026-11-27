from __future__ import annotations

import http.client
import io
import json
import urllib.error
from pathlib import Path
from typing import Any

import pytest
from ruamel.yaml import YAML

from scripts import ci_bookkeeping_api as api_mod
from scripts import ci_bookkeeping_gate as gate
from scripts.ci_bookkeeping_api import CompareResult, GateApi, JobRecord, JobStep

REPO_ROOT = Path(__file__).resolve().parent.parent
YAML_LOADER = YAML(typ="safe")


def _passed_job(name: str = "unit (ubuntu-latest)") -> JobRecord:
    return JobRecord(
        name=name,
        status="completed",
        conclusion="success",
        steps=(
            JobStep("Set up job", "completed", "success"),
            JobStep("Checkout code", "completed", "success"),
            JobStep("Bookkeeping gate", "completed", "success"),
            JobStep("Run unit tests", "completed", "success"),
            JobStep("Complete job", "completed", "success"),
        ),
    )


def _skipped_job(name: str = "unit (ubuntu-latest)") -> JobRecord:
    return JobRecord(
        name=name,
        status="completed",
        conclusion="success",
        steps=(
            JobStep("Set up job", "completed", "success"),
            JobStep("Checkout code", "completed", "success"),
            JobStep("Bookkeeping gate", "completed", "success"),
            JobStep("Run unit tests", "completed", "skipped"),
            JobStep("CI Timing Gate (Check <= 5 min)", "completed", "skipped"),
            JobStep("Complete job", "completed", "success"),
        ),
    )


def _failed_job(name: str = "unit (ubuntu-latest)") -> JobRecord:
    return JobRecord(
        name=name,
        status="completed",
        conclusion="failure",
        steps=(
            JobStep("Checkout code", "completed", "success"),
            JobStep("Bookkeeping gate", "completed", "success"),
            JobStep("Run unit tests", "completed", "failure"),
        ),
    )


def _pr_env(
    job_name: str = "unit (ubuntu-latest)",
    attempt: str = "1",
    event_name: str = "pull_request",
) -> dict[str, str]:
    return {
        "GITHUB_EVENT_NAME": event_name,
        "GITHUB_RUN_ATTEMPT": attempt,
        "GITHUB_RUN_ID": "100",
        "GITHUB_JOB": "unit",
        "BOOKKEEPING_JOB_NAME": job_name,
    }


def _fake_api(
    compares: dict[tuple[str, str], CompareResult] | None = None,
    parents: dict[str, tuple[str, ...]] | None = None,
    runs: dict[str, tuple[int, ...]] | None = None,
    jobs: dict[int, tuple[JobRecord, ...]] | None = None,
) -> GateApi:
    compare_map = compares or {}
    parent_map = parents or {}
    run_map = runs or {}
    job_map = jobs or {}
    return GateApi(
        workflow_id=lambda _run_id: 42,
        compare=lambda before, after: compare_map[(before, after)],
        commit_parents=lambda sha: parent_map[sha],
        runs_for_sha=lambda _wf_id, sha: run_map.get(sha, ()),
        jobs_for_run=lambda run_id: job_map.get(run_id, ()),
    )


@pytest.mark.parametrize(
    "path",
    [
        "plans/P-1.md",
        "plans/nested/sub/plan.json",
        "executions/E-1.md",
        "executions/archive/run.jsonl",
        "holon-knowledge/ledger/events.jsonl",
        "holon-knowledge/notes/summary.md",
        "holon-knowledge/meta.json",
    ],
)
def test_is_bookkeeping_path_accepts_valid_paths(path: str) -> None:
    assert gate.is_bookkeeping_path(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/plans/P-1.md",
        "plans\\P-1.md",
        "plans/../src/app.py",
        "plans/script.py",
        "executions/run.sh",
        "holon-knowledge/config.yml",
        "holon-knowledge/notes.txt",
        "src/holon_coherence/cli.py",
        "scripts/ci_bookkeeping_gate.py",
        "tests/test_ci_bookkeeping_gate.py",
        "docs/readme.md",
        "holon-config/hygiene/module_budgets.json",
        ".github/workflows/test-unit.yml",
    ],
)
def test_is_bookkeeping_path_rejects_invalid_paths(path: str) -> None:
    assert gate.is_bookkeeping_path(path) is False


def test_compare_validates_renames_both_directions() -> None:
    ok_rename = CompareResult("ahead", 1, 0, (("plans/new.md", "plans/old.md"),))
    assert gate.is_bookkeeping_compare(ok_rename)[0] is True

    bad_from_code = CompareResult("ahead", 1, 0, (("plans/new.md", "src/app.py"),))
    assert gate.is_bookkeeping_compare(bad_from_code)[0] is False

    bad_to_docs = CompareResult("ahead", 1, 0, (("docs/new.md", "plans/old.md"),))
    assert gate.is_bookkeeping_compare(bad_to_docs)[0] is False


@pytest.mark.parametrize(
    ("env_overrides", "action"),
    [
        ({"GITHUB_EVENT_NAME": "push"}, "synchronize"),
        ({"GITHUB_EVENT_NAME": "workflow_dispatch"}, "synchronize"),
        ({"GITHUB_RUN_ATTEMPT": "2"}, "synchronize"),
        ({"GITHUB_RUN_ATTEMPT": ""}, "synchronize"),
        ({}, "opened"),
        ({}, "reopened"),
        ({}, "edited"),
        ({"BOOKKEEPING_JOB_NAME": "", "GITHUB_JOB": ""}, "synchronize"),
        ({"GITHUB_RUN_ID": ""}, "synchronize"),
    ],
)
def test_non_eligible_events_and_attempts_fail_closed(env_overrides: dict[str, str], action: str) -> None:
    env = {**_pr_env(), **env_overrides}
    decision = gate.evaluate(env, {"action": action}, _fake_api())
    assert decision.skip is False


@pytest.mark.parametrize("action", ["labeled", "unlabeled"])
@pytest.mark.parametrize("label", ["documentation", "chore"])
def test_benign_label_change_with_prior_green_job_skips(action: str, label: str) -> None:
    api = _fake_api(runs={"sha1": (10,)}, jobs={10: (_passed_job(),)})
    event = {"action": action, "label": {"name": label}, "pull_request": {"head": {"sha": "sha1"}}}
    decision = gate.evaluate(_pr_env(), event, api)
    assert decision.skip is True


@pytest.mark.parametrize("action", ["labeled", "unlabeled"])
@pytest.mark.parametrize("label", sorted(gate.RESULT_AFFECTING_LABELS))
def test_result_affecting_label_change_never_skips(action: str, label: str) -> None:
    api = _fake_api(runs={"sha1": (10,)}, jobs={10: (_passed_job(),)})
    event = {"action": action, "label": {"name": label}, "pull_request": {"head": {"sha": "sha1"}}}
    decision = gate.evaluate(_pr_env(), event, api)
    assert decision.skip is False


def test_benign_label_change_fails_closed_without_prior_green() -> None:
    failed_api = _fake_api(runs={"sha1": (10,)}, jobs={10: (_failed_job(),)})
    event = {"action": "labeled", "label": {"name": "chore"}, "pull_request": {"head": {"sha": "sha1"}}}
    assert gate.evaluate(_pr_env(), event, failed_api).skip is False
    assert gate.evaluate(_pr_env(), event, _fake_api()).skip is False


def test_synchronize_bookkeeping_push_with_prior_green_skips() -> None:
    api = _fake_api(
        compares={("c0", "c1"): CompareResult("ahead", 1, 0, (("executions/E-1.md", None),))},
        runs={"c0": (10,)},
        jobs={10: (_passed_job(),)},
    )
    event = {"action": "synchronize", "before": "c0", "after": "c1"}
    decision = gate.evaluate(_pr_env(), event, api)
    assert decision.skip is True


def test_synchronize_non_bookkeeping_file_fails_closed() -> None:
    api = _fake_api(
        compares={
            ("c0", "c1"): CompareResult("ahead", 1, 0, (("executions/E-1.md", None), ("src/app.py", None))),
        },
        runs={"c0": (10,)},
        jobs={10: (_passed_job(),)},
    )
    event = {"action": "synchronize", "before": "c0", "after": "c1"}
    assert gate.evaluate(_pr_env(), event, api).skip is False


@pytest.mark.parametrize(
    "compare_result",
    [
        CompareResult("diverged", 1, 1, (("plans/p.md", None),)),
        CompareResult("behind", 0, 1, (("plans/p.md", None),)),
        CompareResult("identical", 0, 0, (("plans/p.md", None),)),
        CompareResult("ahead", 1, 1, (("plans/p.md", None),)),
        CompareResult("ahead", 1, 0, ()),
        CompareResult("ahead", 1, 0, tuple((f"plans/p-{i}.md", None) for i in range(300))),
    ],
)
def test_synchronize_force_push_and_invalid_compare_fail_closed(compare_result: CompareResult) -> None:
    api = _fake_api(compares={("c0", "c1"): compare_result}, runs={"c0": (10,)}, jobs={10: (_passed_job(),)})
    event = {"action": "synchronize", "before": "c0", "after": "c1"}
    assert gate.evaluate(_pr_env(), event, api).skip is False


def test_chain_traversal_across_skipped_runs_succeeds() -> None:
    api = _fake_api(
        compares={
            ("c1", "c2"): CompareResult("ahead", 1, 0, (("executions/E-2.md", None),)),
            ("c0", "c1"): CompareResult("ahead", 1, 0, (("plans/P-1.md", None),)),
        },
        parents={"c1": ("c0",)},
        runs={"c0": (10,), "c1": (11,)},
        jobs={10: (_passed_job(),), 11: (_skipped_job(),)},
    )
    event = {"action": "synchronize", "before": "c1", "after": "c2"}
    assert gate.evaluate(_pr_env(), event, api).skip is True


def test_chain_traversal_fails_on_non_bookkeeping_ancestor() -> None:
    api = _fake_api(
        compares={
            ("c1", "c2"): CompareResult("ahead", 1, 0, (("executions/E-2.md", None),)),
            ("c0", "c1"): CompareResult("ahead", 1, 0, (("src/app.py", None),)),
        },
        parents={"c1": ("c0",)},
        runs={"c0": (10,), "c1": (11,)},
        jobs={10: (_passed_job(),), 11: (_skipped_job(),)},
    )
    event = {"action": "synchronize", "before": "c1", "after": "c2"}
    assert gate.evaluate(_pr_env(), event, api).skip is False


@pytest.mark.parametrize("parent_tuple", [(), ("p1", "p2")])
def test_chain_traversal_fails_on_root_or_merge_commit(parent_tuple: tuple[str, ...]) -> None:
    api = _fake_api(
        compares={("c1", "c2"): CompareResult("ahead", 1, 0, (("executions/E-2.md", None),))},
        parents={"c1": parent_tuple},
        runs={"c1": (11,)},
        jobs={11: (_skipped_job(),)},
    )
    event = {"action": "synchronize", "before": "c1", "after": "c2"}
    assert gate.evaluate(_pr_env(), event, api).skip is False


def test_chain_traversal_fails_when_exceeding_max_depth() -> None:
    compares: dict[tuple[str, str], CompareResult] = {}
    parents: dict[str, tuple[str, ...]] = {}
    runs: dict[str, tuple[int, ...]] = {}
    jobs: dict[int, tuple[JobRecord, ...]] = {}
    total = gate.MAX_CHAIN_DEPTH + 2
    for idx in range(1, total):
        prev_sha, cur_sha = f"c{idx - 1}", f"c{idx}"
        compares[(prev_sha, cur_sha)] = CompareResult("ahead", 1, 0, ((f"plans/p-{idx}.md", None),))
        parents[cur_sha] = (prev_sha,)
        runs[cur_sha] = (idx,)
        jobs[idx] = (_skipped_job(),)
    runs["c0"] = (999,)
    jobs[999] = (_passed_job(),)
    api = _fake_api(compares=compares, parents=parents, runs=runs, jobs=jobs)
    event = {"action": "synchronize", "before": f"c{total - 2}", "after": f"c{total - 1}"}
    assert gate.evaluate(_pr_env(), event, api).skip is False


def test_chain_traversal_requires_exact_matrix_job_name() -> None:
    api = _fake_api(
        compares={("c0", "c1"): CompareResult("ahead", 1, 0, (("plans/P-1.md", None),))},
        runs={"c0": (10,)},
        jobs={10: (_passed_job("unit (ubuntu-latest)"),)},
    )
    event = {"action": "synchronize", "before": "c0", "after": "c1"}
    assert gate.evaluate(_pr_env(job_name="unit (macos-latest)"), event, api).skip is False


def _read_outputs(path: Path) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        pairs[key] = value
    return pairs


@pytest.mark.parametrize(
    "exc",
    [
        urllib.error.HTTPError("https://api.github.com", 500, "err", {}, io.BytesIO(b"")),
        OSError("connection reset"),
        http.client.IncompleteRead(b"partial"),
        json.JSONDecodeError("bad json", "{", 1),
    ],
)
def test_main_fails_closed_on_api_errors_and_exits_zero(tmp_path: Path, exc: Exception) -> None:
    event_file = tmp_path / "event.json"
    output_file = tmp_path / "output.txt"
    event_file.write_text(json.dumps({"action": "synchronize", "before": "c0", "after": "c1"}), encoding="utf-8")

    def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise exc

    broken_api = GateApi(workflow_id=boom, compare=boom, commit_parents=boom, runs_for_sha=boom, jobs_for_run=boom)
    env = {**_pr_env(), "GITHUB_EVENT_PATH": str(event_file), "GITHUB_OUTPUT": str(output_file)}
    assert gate.main(env=env, api=broken_api) == 0
    outputs = _read_outputs(output_file)
    assert outputs["skip"] == "false"
    assert "fail-closed" in outputs["reason"]


def test_main_fails_closed_on_missing_token_or_malformed_event(tmp_path: Path) -> None:
    output_file = tmp_path / "output.txt"
    event_file = tmp_path / "event.json"
    event_file.write_text("{not valid json", encoding="utf-8")
    env = {
        **_pr_env(),
        "GITHUB_EVENT_PATH": str(event_file),
        "GITHUB_OUTPUT": str(output_file),
        "GITHUB_REPOSITORY": "holon/coherence",
        "GITHUB_TOKEN": "",
    }
    assert gate.main(env=env) == 0
    assert _read_outputs(output_file)["skip"] == "false"

    event_file.write_text(json.dumps({"action": "synchronize", "before": "c0", "after": "c1"}), encoding="utf-8")
    output_file.unlink()
    assert gate.main(env=env) == 0
    assert _read_outputs(output_file)["skip"] == "false"


def test_main_writes_skip_true_and_single_line_reason(tmp_path: Path) -> None:
    event_file = tmp_path / "event.json"
    output_file = tmp_path / "output.txt"
    event_file.write_text(json.dumps({"action": "synchronize", "before": "c0", "after": "c1"}), encoding="utf-8")
    api = _fake_api(
        compares={("c0", "c1"): CompareResult("ahead", 1, 0, (("plans/P-1.md", None),))},
        runs={"c0": (10,)},
        jobs={10: (_passed_job(),)},
    )
    env = {**_pr_env(), "GITHUB_EVENT_PATH": str(event_file), "GITHUB_OUTPUT": str(output_file)}
    assert gate.main(env=env, api=api) == 0
    outputs = _read_outputs(output_file)
    assert outputs["skip"] == "true"
    assert "\n" not in outputs["reason"]
    assert outputs["reason"]


def test_github_api_request_headers_and_parsers(monkeypatch: pytest.MonkeyPatch) -> None:
    req = api_mod._request("https://api.github.com/test", "secret-token")
    assert req.get_header("Accept") == "application/vnd.github+json"
    assert req.get_header("X-github-api-version") == api_mod.API_VERSION
    assert req.get_header("Authorization") == "Bearer secret-token"

    responses: dict[str, Any] = {
        "https://api.github.com/repos/org/repo/actions/runs/55": {"workflow_id": 77},
        "https://api.github.com/repos/org/repo/compare/a1...b2": {
            "status": "ahead",
            "ahead_by": 1,
            "behind_by": 0,
            "files": [{"filename": "plans/p.md", "previous_filename": "plans/old.md"}],
        },
        "https://api.github.com/repos/org/repo/commits/b2": {"parents": [{"sha": "a1"}]},
        "https://api.github.com/repos/org/repo/actions/workflows/77/runs?head_sha=a1&per_page=100": {
            "workflow_runs": [
                {"id": 1, "status": "completed", "conclusion": "failure", "created_at": "2026-01-02T00:00:00Z"},
                {"id": 2, "status": "completed", "conclusion": "success", "created_at": "2026-01-01T00:00:00Z"},
                {"id": 3, "status": "completed", "conclusion": "success", "created_at": "2026-01-03T00:00:00Z"},
            ]
        },
        "https://api.github.com/repos/org/repo/actions/runs/3/jobs?per_page=100": {
            "jobs": [
                {
                    "name": "unit (ubuntu-latest)",
                    "status": "completed",
                    "conclusion": "success",
                    "steps": [{"name": "Run unit tests", "status": "completed", "conclusion": "success"}],
                }
            ]
        },
    }
    monkeypatch.setattr(api_mod, "_get_json", lambda url, _token: responses[url])
    client = api_mod.github_api("https://api.github.com", "org/repo", "tok")
    assert client.workflow_id("55") == 77
    assert client.compare("a1", "b2") == CompareResult("ahead", 1, 0, (("plans/p.md", "plans/old.md"),))
    assert client.commit_parents("b2") == ("a1",)
    assert client.runs_for_sha(77, "a1") == (3, 2)
    jobs = client.jobs_for_run(3)
    assert len(jobs) == 1
    assert jobs[0].name == "unit (ubuntu-latest)"
    assert jobs[0].steps == (JobStep("Run unit tests", "completed", "success"),)


def test_composite_action_wiring() -> None:
    action_path = REPO_ROOT / ".github" / "actions" / "bookkeeping-gate" / "action.yml"
    assert action_path.is_file()
    data = YAML_LOADER.load(action_path.read_text(encoding="utf-8"))
    assert data["runs"]["using"] == "composite"
    assert "skip" in data["outputs"]
    assert "reason" in data["outputs"]
    steps = data["runs"]["steps"]
    assert len(steps) == 1
    assert "ci_bookkeeping_gate.py" in steps[0]["run"]


@pytest.mark.parametrize(
    ("workflow_file", "job_key", "expected_job_name"),
    [
        ("test-unit.yml", "unit", "unit (${{ matrix.os }})"),
        ("test-integration.yml", "integration", "integration (${{ matrix.os }})"),
        ("test-hygiene.yml", "hygiene", "hygiene (${{ matrix.os }})"),
        ("make.yml", "make", "make (${{ matrix.os }})"),
        ("docker-build.yml", "docker-build", "docker-build"),
    ],
)
def test_workflow_bookkeeping_gate_wiring(workflow_file: str, job_key: str, expected_job_name: str) -> None:
    workflow_path = REPO_ROOT / ".github" / "workflows" / workflow_file
    data = YAML_LOADER.load(workflow_path.read_text(encoding="utf-8"))
    steps = data["jobs"][job_key]["steps"]
    assert steps[0]["uses"].startswith("actions/checkout@")
    gate_step = steps[1]
    assert gate_step["id"] == "bookkeeping_gate"
    assert gate_step["name"] == gate.GATE_STEP_NAME
    assert gate_step["uses"] == "./.github/actions/bookkeeping-gate"
    assert gate_step["with"]["job-name"] == expected_job_name
    for step in steps[2:]:
        condition = step.get("if", "")
        assert "steps.bookkeeping_gate.outputs.skip != 'true'" in condition, (
            f"{workflow_file} step {step.get('name')!r} missing bookkeeping_gate guard"
        )
