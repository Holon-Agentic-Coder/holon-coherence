from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from scripts.ci_bookkeeping_api import (
        CheckRunInfo,
        GitHubApiError,
        GitHubBookkeepingClient,
    )
except ModuleNotFoundError:
    from ci_bookkeeping_api import (
        CheckRunInfo,
        GitHubApiError,
        GitHubBookkeepingClient,
    )

ALLOWED_PREFIXES = ("plans/", "executions/", "holon-knowledge/")
ALLOWED_SUFFIXES = (".md", ".json", ".jsonl")
RESULT_AFFECTING_LABELS = frozenset(
    {
        "module-budget-change",
        "ci-timing-override",
        "timing-regression-accepted",
    }
)
MAX_COMPARE_FILES = 300
MAX_CHAIN_DEPTH = 20
DEFAULT_API_URL = "https://api.github.com"


@dataclass(frozen=True)
class GateDecision:
    skip: bool
    reason: str


def is_bookkeeping_path(path: str) -> bool:
    if not path or path.startswith("/") or "\\" in path:
        return False
    pure = PurePosixPath(path)
    if ".." in pure.parts:
        return False
    return path.startswith(ALLOWED_PREFIXES) and pure.suffix in ALLOWED_SUFFIXES


def all_bookkeeping_files(files: tuple[tuple[str, str | None], ...]) -> bool:
    if not files or len(files) >= MAX_COMPARE_FILES:
        return False
    for filename, previous_filename in files:
        if not is_bookkeeping_path(filename):
            return False
        if previous_filename and not is_bookkeeping_path(previous_filename):
            return False
    return True


def _has_green_check(runs: tuple[CheckRunInfo, ...], check_name: str) -> bool:
    return any(run.name == check_name and run.status == "completed" and run.conclusion == "success" for run in runs)


def verify_green_ancestor_chain(
    client: Any,
    start_sha: str,
    check_name: str,
    max_depth: int = MAX_CHAIN_DEPTH,
) -> GateDecision:
    visited: set[str] = set()
    sha = start_sha
    for _ in range(max_depth):
        if not sha or sha in visited:
            return GateDecision(False, "invalid or cyclic ancestor sha")
        visited.add(sha)
        runs = client.list_check_runs(sha, check_name)
        if not _has_green_check(runs, check_name):
            return GateDecision(False, f"no green check-run for {check_name} on {sha[:12]}")
        commit = client.get_commit(sha)
        if not all_bookkeeping_files(commit.files):
            return GateDecision(True, f"verified green ancestor {sha[:12]}")
        if len(commit.parents) != 1:
            return GateDecision(False, f"non-linear bookkeeping ancestor {sha[:12]}")
        sha = commit.parents[0]
    return GateDecision(False, "ancestor chain exceeded max depth")


def _evaluate_label_event(event: Mapping[str, Any], client: Any, check_name: str) -> GateDecision:
    label = event.get("label")
    label_name = label.get("name", "") if isinstance(label, Mapping) else ""
    if not isinstance(label_name, str) or not label_name or label_name in RESULT_AFFECTING_LABELS:
        return GateDecision(False, f"result-affecting label: {label_name or 'unknown'}")
    pr = event.get("pull_request")
    head = pr.get("head") if isinstance(pr, Mapping) else None
    head_sha = head.get("sha", "") if isinstance(head, Mapping) else ""
    if not isinstance(head_sha, str) or not head_sha:
        return GateDecision(False, "missing pull_request head sha")
    return verify_green_ancestor_chain(client, head_sha, check_name)


def _evaluate_synchronize_event(event: Mapping[str, Any], client: Any, check_name: str) -> GateDecision:
    before = event.get("before", "")
    after = event.get("after", "")
    if not isinstance(before, str) or not isinstance(after, str) or not before or not after or before == after:
        return GateDecision(False, "missing or identical before/after sha")
    compare = client.compare_commits(before, after)
    if compare.status != "ahead":
        return GateDecision(False, f"compare status is {compare.status}, not ahead")
    if not all_bookkeeping_files(compare.files):
        return GateDecision(False, "diff includes non-bookkeeping or truncated files")
    return verify_green_ancestor_chain(client, before, check_name)


def _check_gate_preconditions(env: Mapping[str, str], check_name: str) -> GateDecision | None:
    if env.get("GITHUB_EVENT_NAME") != "pull_request":
        return GateDecision(False, f"non-pull_request event: {env.get('GITHUB_EVENT_NAME', 'unknown')}")
    if env.get("GITHUB_RUN_ATTEMPT", "1") != "1":
        return GateDecision(False, f"re-run attempt {env.get('GITHUB_RUN_ATTEMPT')}")
    if not check_name:
        return GateDecision(False, "missing check name")
    return None


def evaluate_gate(event: Mapping[str, Any], env: Mapping[str, str], client: Any, check_name: str) -> GateDecision:
    precondition = _check_gate_preconditions(env, check_name)
    if precondition is not None:
        return precondition
    action = event.get("action")
    try:
        if action in {"labeled", "unlabeled"}:
            return _evaluate_label_event(event, client, check_name)
        if action == "synchronize":
            return _evaluate_synchronize_event(event, client, check_name)
        return GateDecision(False, f"unsupported pull_request action: {action}")
    except GitHubApiError as exc:
        return GateDecision(False, f"github api error: {exc}")


def _write_outputs(decision: GateDecision, env: Mapping[str, str]) -> None:
    clean_reason = " ".join(decision.reason.replace("\r", " ").replace("\n", " ").split())
    skip_val = "true" if decision.skip else "false"
    output_path = env.get("GITHUB_OUTPUT")
    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as handle:
            handle.write(f"skip={skip_val}\nreason={clean_reason}\n")
    print(f"::notice::Bookkeeping gate skip={skip_val} ({clean_reason})")


def _run_from_env(args: argparse.Namespace, env: Mapping[str, str]) -> GateDecision:
    event_path_str = args.event_path or env.get("GITHUB_EVENT_PATH", "")
    token = env.get("GITHUB_TOKEN", "")
    repo = env.get("GITHUB_REPOSITORY", "")
    if not event_path_str:
        return GateDecision(False, "missing GITHUB_EVENT_PATH")
    if not token:
        return GateDecision(False, "missing GITHUB_TOKEN")
    if not repo:
        return GateDecision(False, "missing GITHUB_REPOSITORY")
    event = json.loads(Path(event_path_str).read_text(encoding="utf-8"))
    if not isinstance(event, dict):
        return GateDecision(False, "event payload is not a JSON object")
    client = GitHubBookkeepingClient(
        api_url=env.get("GITHUB_API_URL", DEFAULT_API_URL),
        repo=repo,
        token=token,
    )
    return evaluate_gate(event, env, client, args.check_name)


def main(argv: list[str] | None = None, env: Mapping[str, str] = os.environ) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-name", required=True)
    parser.add_argument("--event-path", default=None)
    args = parser.parse_args(argv)
    try:
        decision = _run_from_env(args, env)
    except (OSError, json.JSONDecodeError, GitHubApiError, KeyError, TypeError, ValueError) as exc:
        decision = GateDecision(False, f"gate error: {exc}")
    _write_outputs(decision, env)
    return 0


if __name__ == "__main__":
    sys.exit(main())
