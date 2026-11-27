#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from scripts.ci_bookkeeping_api import API_ERRORS, CompareResult, GateApi, JobRecord, github_api
except ModuleNotFoundError:
    from ci_bookkeeping_api import API_ERRORS, CompareResult, GateApi, JobRecord, github_api

BOOKKEEPING_PREFIXES = ("plans/", "executions/", "holon-knowledge/")
BOOKKEEPING_SUFFIXES = (".md", ".json", ".jsonl")
RESULT_AFFECTING_LABELS = frozenset({"module-budget-change", "ci-timing-override", "timing-regression-accepted"})
ALLOWED_PR_ACTIONS = frozenset({"synchronize", "labeled", "unlabeled"})
GATE_STEP_NAME = "Bookkeeping gate"
CHECKOUT_STEP_PREFIX = "Checkout"
BUILTIN_STEPS = frozenset({"Set up job", "Complete job"})
MAX_COMPARE_FILES = 300
MAX_CHAIN_DEPTH = 20
ZERO_SHA = "0" * 40


@dataclass(frozen=True)
class GateDecision:
    skip: bool
    reason: str


def is_bookkeeping_path(path: str) -> bool:
    if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path:
        return False
    if ".." in PurePosixPath(path).parts:
        return False
    return path.startswith(BOOKKEEPING_PREFIXES) and path.endswith(BOOKKEEPING_SUFFIXES)


def is_bookkeeping_compare(result: CompareResult) -> tuple[bool, str]:
    if result.status != "ahead" or result.ahead_by <= 0 or result.behind_by != 0:
        return False, f"non-linear compare status={result.status} ahead={result.ahead_by} behind={result.behind_by}"
    if not result.files or len(result.files) >= MAX_COMPARE_FILES:
        return False, f"invalid compare file count: {len(result.files)}"
    for filename, previous_filename in result.files:
        if not is_bookkeeping_path(filename):
            return False, f"non-bookkeeping file changed: {filename}"
        if previous_filename is not None and not is_bookkeeping_path(previous_filename):
            return False, f"non-bookkeeping file renamed: {previous_filename}"
    return True, "bookkeeping-only diff"


def _is_work_step(name: str) -> bool:
    return name not in BUILTIN_STEPS and not name.startswith(CHECKOUT_STEP_PREFIX) and name != GATE_STEP_NAME


def classify_job(job: JobRecord) -> str:
    if job.status != "completed" or job.conclusion != "success":
        return "none"
    gate_ok = any(step.name == GATE_STEP_NAME and step.conclusion == "success" for step in job.steps)
    work_steps = [step for step in job.steps if _is_work_step(step.name)]
    if any(step.conclusion == "success" for step in work_steps):
        return "passed"
    if gate_ok and work_steps and all(step.conclusion == "skipped" for step in work_steps):
        return "skipped"
    return "none"


def job_status_on_sha(api: GateApi, wf_id: int, sha: str, job_name: str) -> str:
    best = "none"
    for run_id in api.runs_for_sha(wf_id, sha):
        for job in api.jobs_for_run(run_id):
            if job.name != job_name:
                continue
            status = classify_job(job)
            if status == "passed":
                return "passed"
            if status == "skipped":
                best = "skipped"
    return best


def has_prior_green_chain(api: GateApi, wf_id: int, start_sha: str, job_name: str) -> tuple[bool, str]:
    sha = start_sha
    visited: set[str] = set()
    for _ in range(MAX_CHAIN_DEPTH):
        if not sha or sha in visited:
            return False, f"invalid or cyclic commit at {sha[:7]}"
        visited.add(sha)
        status = job_status_on_sha(api, wf_id, sha, job_name)
        if status == "passed":
            return True, f"prior green job verified at {sha[:7]}"
        if status != "skipped":
            return False, f"no prior green job at {sha[:7]}"
        parents = api.commit_parents(sha)
        if len(parents) != 1:
            return False, f"non-linear history at {sha[:7]}"
        ok, reason = is_bookkeeping_compare(api.compare(parents[0], sha))
        if not ok:
            return False, f"ancestor {sha[:7]}: {reason}"
        sha = parents[0]
    return False, "chain depth limit exceeded"


def _precondition_failure(env: Mapping[str, str], event: Mapping[str, Any]) -> str | None:
    if env.get("GITHUB_EVENT_NAME") != "pull_request":
        return f"event is {env.get('GITHUB_EVENT_NAME', 'unset')}"
    if env.get("GITHUB_RUN_ATTEMPT") != "1":
        return f"run attempt is {env.get('GITHUB_RUN_ATTEMPT', 'unset')}"
    if event.get("action") not in ALLOWED_PR_ACTIONS:
        return f"unsupported pull_request action: {event.get('action', 'unset')}"
    if not (env.get("BOOKKEEPING_JOB_NAME") or env.get("GITHUB_JOB")) or not env.get("GITHUB_RUN_ID"):
        return "missing job name or run id"
    return None


def _evaluate_label_event(event: Mapping[str, Any], api: GateApi, wf_id: int, job_name: str) -> GateDecision:
    label_name = (event.get("label") or {}).get("name", "")
    if not isinstance(label_name, str) or not label_name:
        return GateDecision(False, "missing label name")
    if label_name in RESULT_AFFECTING_LABELS:
        return GateDecision(False, f"result-affecting label changed: {label_name}")
    head_sha = ((event.get("pull_request") or {}).get("head") or {}).get("sha", "")
    if not isinstance(head_sha, str) or not head_sha:
        return GateDecision(False, "missing pull_request head sha")
    ok, reason = has_prior_green_chain(api, wf_id, head_sha, job_name)
    return GateDecision(ok, f"benign label '{label_name}': {reason}" if ok else reason)


def _evaluate_sync_event(event: Mapping[str, Any], api: GateApi, wf_id: int, job_name: str) -> GateDecision:
    before, after = event.get("before", ""), event.get("after", "")
    if not (isinstance(before, str) and isinstance(after, str)) or not before or not after:
        return GateDecision(False, "invalid synchronize commit range")
    if before in (after, ZERO_SHA) or after == ZERO_SHA:
        return GateDecision(False, "invalid synchronize commit range")
    ok, reason = is_bookkeeping_compare(api.compare(before, after))
    if not ok:
        return GateDecision(False, reason)
    chain_ok, chain_reason = has_prior_green_chain(api, wf_id, before, job_name)
    return GateDecision(chain_ok, f"bookkeeping-only push: {chain_reason}" if chain_ok else chain_reason)


def evaluate(env: Mapping[str, str], event: Mapping[str, Any], api: GateApi) -> GateDecision:
    failure = _precondition_failure(env, event)
    if failure is not None:
        return GateDecision(False, failure)
    job_name = env.get("BOOKKEEPING_JOB_NAME") or env.get("GITHUB_JOB", "")
    wf_id = api.workflow_id(env["GITHUB_RUN_ID"])
    if event["action"] == "synchronize":
        return _evaluate_sync_event(event, api, wf_id, job_name)
    return _evaluate_label_event(event, api, wf_id, job_name)


def write_github_output(decision: GateDecision, env: Mapping[str, str]) -> None:
    reason = " ".join(decision.reason.splitlines()).strip()
    output_path = env.get("GITHUB_OUTPUT", "")
    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as handle:
            handle.write(f"skip={'true' if decision.skip else 'false'}\nreason={reason}\n")


def _load_event(env: Mapping[str, str]) -> Mapping[str, Any]:
    event_path = env.get("GITHUB_EVENT_PATH", "")
    if not event_path:
        raise ValueError("missing GITHUB_EVENT_PATH")
    data = json.loads(Path(event_path).read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise TypeError("event payload is not a JSON object")
    return data


def _build_api(env: Mapping[str, str]) -> GateApi:
    repo, token = env.get("GITHUB_REPOSITORY", ""), env.get("GITHUB_TOKEN", "")
    if not repo or not token:
        raise ValueError("missing GITHUB_REPOSITORY or GITHUB_TOKEN")
    return github_api(env.get("GITHUB_API_URL", "https://api.github.com"), repo, token)


def main(env: Mapping[str, str] | None = None, api: GateApi | None = None) -> int:
    active_env = os.environ if env is None else env
    try:
        decision = evaluate(active_env, _load_event(active_env), api or _build_api(active_env))
    except API_ERRORS as exc:
        decision = GateDecision(False, f"fail-closed on error: {exc}")
    write_github_output(decision, active_env)
    print(f"Bookkeeping gate: skip={'true' if decision.skip else 'false'} ({decision.reason})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
