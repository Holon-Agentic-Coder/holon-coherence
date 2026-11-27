#!/usr/bin/env python3
from __future__ import annotations

import http.client
import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

HTTP_TIMEOUT_S = 20
API_VERSION = "2022-11-28"
API_ERRORS = (
    OSError,
    http.client.HTTPException,
    json.JSONDecodeError,
    KeyError,
    TypeError,
    ValueError,
    AttributeError,
)


@dataclass(frozen=True)
class CompareResult:
    status: str
    ahead_by: int
    behind_by: int
    files: tuple[tuple[str, str | None], ...]


@dataclass(frozen=True)
class JobStep:
    name: str
    status: str
    conclusion: str | None


@dataclass(frozen=True)
class JobRecord:
    name: str
    status: str
    conclusion: str | None
    steps: tuple[JobStep, ...]


@dataclass(frozen=True)
class GateApi:
    workflow_id: Callable[[str], int]
    compare: Callable[[str, str], CompareResult]
    commit_parents: Callable[[str], tuple[str, ...]]
    runs_for_sha: Callable[[int, str], tuple[int, ...]]
    jobs_for_run: Callable[[int], tuple[JobRecord, ...]]


def _request(url: str, token: str) -> urllib.request.Request:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=headers)


def _get_json(url: str, token: str) -> Any:
    with urllib.request.urlopen(_request(url, token), timeout=HTTP_TIMEOUT_S) as response:
        return json.load(response)


def _parse_compare(data: Any) -> CompareResult:
    status = data["status"]
    ahead_by = data["ahead_by"]
    behind_by = data["behind_by"]
    raw_files = data["files"]
    if not isinstance(status, str) or isinstance(ahead_by, bool) or isinstance(behind_by, bool):
        raise TypeError("invalid compare metadata")
    if not isinstance(ahead_by, int) or not isinstance(behind_by, int) or not isinstance(raw_files, list):
        raise TypeError("invalid compare payload")
    parsed_files: list[tuple[str, str | None]] = []
    for entry in raw_files:
        filename = entry["filename"]
        previous = entry.get("previous_filename")
        if not isinstance(filename, str) or (previous is not None and not isinstance(previous, str)):
            raise TypeError("invalid compare file entry")
        parsed_files.append((filename, previous))
    return CompareResult(status=status, ahead_by=ahead_by, behind_by=behind_by, files=tuple(parsed_files))


def _parse_job(entry: Any) -> JobRecord:
    steps = tuple(
        JobStep(name=step["name"], status=step["status"], conclusion=step.get("conclusion"))
        for step in (entry.get("steps") or [])
    )
    return JobRecord(
        name=entry["name"],
        status=entry["status"],
        conclusion=entry.get("conclusion"),
        steps=steps,
    )


def github_api(api_url: str, repo: str, token: str) -> GateApi:
    base = f"{api_url.rstrip('/')}/repos/{repo}"

    def workflow_id(run_id: str) -> int:
        quoted = urllib.parse.quote(str(run_id), safe="")
        data = _get_json(f"{base}/actions/runs/{quoted}", token)
        return int(data["workflow_id"])

    def compare(before: str, after: str) -> CompareResult:
        q_before = urllib.parse.quote(before, safe="")
        q_after = urllib.parse.quote(after, safe="")
        data = _get_json(f"{base}/compare/{q_before}...{q_after}", token)
        return _parse_compare(data)

    def commit_parents(sha: str) -> tuple[str, ...]:
        quoted = urllib.parse.quote(sha, safe="")
        data = _get_json(f"{base}/commits/{quoted}", token)
        return tuple(parent["sha"] for parent in data["parents"])

    def runs_for_sha(wf_id: int, sha: str) -> tuple[int, ...]:
        quoted = urllib.parse.quote(sha, safe="")
        data = _get_json(f"{base}/actions/workflows/{wf_id}/runs?head_sha={quoted}&per_page=100", token)
        runs = [
            run
            for run in data["workflow_runs"]
            if run.get("status") == "completed" and run.get("conclusion") == "success"
        ]
        runs.sort(key=lambda run: (run.get("created_at", ""), int(run["id"])), reverse=True)
        return tuple(int(run["id"]) for run in runs)

    def jobs_for_run(run_id: int) -> tuple[JobRecord, ...]:
        data = _get_json(f"{base}/actions/runs/{run_id}/jobs?per_page=100", token)
        return tuple(_parse_job(entry) for entry in data["jobs"])

    return GateApi(
        workflow_id=workflow_id,
        compare=compare,
        commit_parents=commit_parents,
        runs_for_sha=runs_for_sha,
        jobs_for_run=jobs_for_run,
    )
