from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

HTTP_TIMEOUT_S = 15
API_VERSION = "2022-11-28"
USER_AGENT = "holon-coherence-bookkeeping-gate"


class GitHubApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class CompareResult:
    status: str
    files: tuple[tuple[str, str | None], ...]


@dataclass(frozen=True)
class CommitInfo:
    sha: str
    parents: tuple[str, ...]
    files: tuple[tuple[str, str | None], ...]


@dataclass(frozen=True)
class CheckRunInfo:
    name: str
    status: str
    conclusion: str | None


def _get_json(url: str, token: str) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": USER_AGENT,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
            return json.loads(response.read().decode("utf-8"))
    except (
        OSError,
        urllib.error.URLError,
        http.client.HTTPException,
        json.JSONDecodeError,
        TimeoutError,
        ValueError,
    ) as exc:
        raise GitHubApiError(f"request failed for {url}: {exc}") from exc


def _parse_files(raw_files: Any) -> tuple[tuple[str, str | None], ...]:
    if not isinstance(raw_files, list):
        raise GitHubApiError("expected list for files payload")
    parsed: list[tuple[str, str | None]] = []
    for entry in raw_files:
        if not isinstance(entry, dict):
            raise GitHubApiError("expected dict for file entry")
        filename = entry.get("filename")
        previous = entry.get("previous_filename")
        if not isinstance(filename, str) or (previous is not None and not isinstance(previous, str)):
            raise GitHubApiError("invalid filename fields in file entry")
        parsed.append((filename, previous))
    return tuple(parsed)


def _parse_parents(raw_parents: Any) -> tuple[str, ...]:
    if not isinstance(raw_parents, list):
        raise GitHubApiError("expected list for commit parents")
    parents: list[str] = []
    for entry in raw_parents:
        if not isinstance(entry, dict) or not isinstance(entry.get("sha"), str):
            raise GitHubApiError("invalid parent entry in commit payload")
        parents.append(entry["sha"])
    return tuple(parents)


def _parse_check_runs(raw_runs: Any) -> tuple[CheckRunInfo, ...]:
    if not isinstance(raw_runs, list):
        raise GitHubApiError("expected list for check_runs payload")
    runs: list[CheckRunInfo] = []
    for entry in raw_runs:
        if not isinstance(entry, dict):
            raise GitHubApiError("expected dict for check-run entry")
        name = entry.get("name")
        status = entry.get("status")
        conclusion = entry.get("conclusion")
        if (
            not isinstance(name, str)
            or not isinstance(status, str)
            or (conclusion is not None and not isinstance(conclusion, str))
        ):
            raise GitHubApiError("invalid fields in check-run entry")
        runs.append(CheckRunInfo(name=name, status=status, conclusion=conclusion))
    return tuple(runs)


@dataclass(frozen=True)
class GitHubBookkeepingClient:
    api_url: str
    repo: str
    token: str

    def _repo_base(self) -> str:
        return f"{self.api_url.rstrip('/')}/repos/{self.repo}"

    def compare_commits(self, before: str, after: str) -> CompareResult:
        left = urllib.parse.quote(before, safe="")
        right = urllib.parse.quote(after, safe="")
        payload = _get_json(f"{self._repo_base()}/compare/{left}...{right}", self.token)
        if not isinstance(payload, dict) or not isinstance(payload.get("status"), str):
            raise GitHubApiError("invalid compare response payload")
        return CompareResult(status=payload["status"], files=_parse_files(payload.get("files")))

    def get_commit(self, sha: str) -> CommitInfo:
        quoted = urllib.parse.quote(sha, safe="")
        payload = _get_json(f"{self._repo_base()}/commits/{quoted}", self.token)
        if not isinstance(payload, dict) or not isinstance(payload.get("sha"), str):
            raise GitHubApiError("invalid commit response payload")
        return CommitInfo(
            sha=payload["sha"],
            parents=_parse_parents(payload.get("parents")),
            files=_parse_files(payload.get("files")),
        )

    def list_check_runs(self, sha: str, check_name: str) -> tuple[CheckRunInfo, ...]:
        quoted_sha = urllib.parse.quote(sha, safe="")
        quoted_name = urllib.parse.quote(check_name, safe="")
        url = f"{self._repo_base()}/commits/{quoted_sha}/check-runs?check_name={quoted_name}&per_page=100"
        payload = _get_json(url, self.token)
        if not isinstance(payload, dict):
            raise GitHubApiError("invalid check-runs response payload")
        return _parse_check_runs(payload.get("check_runs"))
