#!/usr/bin/env python3
"""CI timing regression gate.

Measures the wall-clock duration of a CI job and compares it against the recent history of the same job on `main`.

Two modes:

- `record` (pushes to `main`, manual runs): writes `timing.json` (job duration plus per-test times parsed from the
  pytest JUnit report) for upload as the artefact `ci-timing-<job>-<OS>`, and enforces the absolute ceiling.
- `compare` (pull requests): fetches the most recent `main` records for the same job and OS, fails when the duration
  exceeds the rolling median by more than the relative tolerance *and* the absolute floor, or exceeds the ceiling,
  and summarises the tests that grew the most.

Every threshold is a command-line flag so the numbers live in the workflow files. Standard library only, and kept
compatible with Python 3.11 so the runner's system `python3` can run it outside Conda and `uv`.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

SCHEMA = 1
RECORD_FILE = "timing.json"
ACCEPT_LABEL = "timing-regression-accepted"
HTTP_TIMEOUT_S = 20
REDIRECT_CODES = (301, 302, 303, 307, 308)


def notice(message: str) -> None:
    """Print an informational GitHub Actions annotation."""
    print(annotation("notice", message))


def annotation(level: str, message: str) -> str:
    """Format a workflow command, escaping the characters GitHub treats specially."""
    escaped = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return f"::{level}::{escaped}"


# --- Records -----------------------------------------------------------------------------------------------------


@dataclass
class TimingRecord:
    workflow: str
    job: str
    os: str
    duration_s: float
    started_at: float
    finished_at: float
    sha: str = ""
    run_id: str = ""
    tests: dict[str, float] = field(default_factory=dict)
    schema: int = SCHEMA

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> TimingRecord | None:
        data = json.loads(text)
        if data.get("schema") != SCHEMA:
            notice(f"ignoring timing record with unknown schema {data.get('schema')!r}")
            return None
        known = {f.name for f in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in known})


def artefact_name(job: str, os_name: str) -> str:
    return f"ci-timing-{job}-{os_name}"


# --- Pure decision core ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Skip:
    message: str


@dataclass
class Verdict:
    status: str  # "pass", "warn" or "fail"
    messages: list[str] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)


def rolling_median(values: list[float]) -> float:
    return statistics.median(values)


def check_ceiling(duration: float, ceiling: float) -> str | None:
    if duration <= ceiling:
        return None
    return f"duration {duration:.0f} s exceeds the absolute ceiling of {ceiling:.0f} s"


def check_relative(
    duration: float, baseline: list[float], count: int, tolerance: float, min_delta: float
) -> str | Skip | None:
    """Compare against the median of the most recent `count` durations (most recent first)."""
    if len(baseline) < count:
        return Skip(f"relative check skipped: only {len(baseline)} of {count} main records; ceiling only")
    median = rolling_median(baseline[:count])
    delta = duration - median
    if duration <= median * (1 + tolerance) or delta <= min_delta:
        return None
    return (
        f"duration {duration:.0f} s is {delta / median:+.0%} ({delta:+.0f} s) over the rolling median {median:.0f} s"
        f" of the last {count} main records; fails when more than {tolerance:.0%} and more than {min_delta:.0f} s"
    )


def _relative_verdict(relative: str | Skip | None, accepted: bool, accept_label: str) -> Verdict:
    if relative is None:
        return Verdict("pass")
    if isinstance(relative, Skip):
        return Verdict("pass", notices=[relative.message])
    if accepted:
        return Verdict("warn", [f"{relative}; accepted by the pull-request label '{accept_label}'"])
    return Verdict("fail", [relative])


def decide(
    duration: float,
    baseline: list[float],
    *,
    count: int,
    tolerance: float,
    min_delta: float,
    ceiling: float,
    accepted: bool,
    accept_label: str = ACCEPT_LABEL,
) -> Verdict:
    """Combine both checks; the label can soften a relative failure but never the ceiling."""
    verdict = _relative_verdict(check_relative(duration, baseline, count, tolerance, min_delta), accepted, accept_label)
    ceiling_failure = check_ceiling(duration, ceiling)
    if ceiling_failure:
        verdict = Verdict("fail", [ceiling_failure, *verdict.messages], verdict.notices)
    return verdict


# --- JUnit parsing and the per-test report -----------------------------------------------------------------------


def parse_junit(text: str) -> dict[str, float]:
    """Map `classname::name` to seconds for every testcase (bare `testsuite` or `testsuites` root)."""
    times: dict[str, float] = {}
    for case in ET.fromstring(text).iter("testcase"):
        key = f"{case.get('classname', '')}::{case.get('name', '')}"
        times[key] = times.get(key, 0.0) + float(case.get("time") or 0)
    return times


def read_junit(path: Path | None) -> dict[str, float]:
    if path is None:
        return {}
    try:
        return parse_junit(path.read_text(encoding="utf-8"))
    except (OSError, ET.ParseError, ValueError) as exc:
        notice(f"JUnit report {path} could not be read ({exc}); per-test times omitted")
        return {}


@dataclass(frozen=True)
class Offender:
    test: str
    baseline: float
    current: float

    @property
    def delta(self) -> float:
        return self.current - self.baseline


def _test_median(test: str, records: list[TimingRecord]) -> float | None:
    times = [record.tests[test] for record in records if test in record.tests]
    return rolling_median(times) if times else None


def test_offenders(
    current: Mapping[str, float],
    baseline_records: list[TimingRecord],
    *,
    tolerance: float = 0.5,
    min_delta: float = 5.0,
    limit: int = 10,
) -> list[Offender]:
    """Tests slower than their baseline median by more than `tolerance` and `min_delta`, largest delta first."""
    offenders = []
    for test, seconds in current.items():
        median = _test_median(test, baseline_records)
        if median is not None and seconds > median * (1 + tolerance) and seconds - median > min_delta:
            offenders.append(Offender(test, median, seconds))
    return sorted(offenders, key=lambda offender: offender.delta, reverse=True)[:limit]


test_offenders.__test__ = False  # not a pytest test, despite the name


def count_new_tests(current: Mapping[str, float], baseline_records: list[TimingRecord]) -> int:
    return sum(1 for test in current if _test_median(test, baseline_records) is None)


def format_offenders(offenders: list[Offender], tolerance: float = 0.5, min_delta: float = 5.0) -> list[str]:
    if not offenders:
        return [f"no test grew by more than {tolerance:.0%} and {min_delta:.0f} s"]
    width = max(len(offender.test) for offender in offenders)
    lines = [f"{'test':<{width}}  {'median':>8}  {'current':>8}  {'delta':>8}  {'change':>7}"]
    for o in offenders:
        change = f"{o.delta / o.baseline:+.0%}" if o.baseline else "n/a"
        lines.append(f"{o.test:<{width}}  {o.baseline:>7.1f}s  {o.current:>7.1f}s  {o.delta:>+7.1f}s  {change:>7}")
    return lines


# --- Artefact selection and the injectable I/O layer -------------------------------------------------------------


def is_main_artifact(artifact: Mapping) -> bool:
    """An unexpired artefact from a `main` run of this repository (not a fork branch also called `main`)."""
    run = artifact.get("workflow_run") or {}
    same_repo = run.get("repository_id") is not None and run.get("head_repository_id") == run.get("repository_id")
    return not artifact.get("expired") and run.get("head_branch") == "main" and same_repo


def select_main_artifacts(artifacts: list[Mapping]) -> list[Mapping]:
    """Main-branch artefacts, most recent first."""
    selected = [artifact for artifact in artifacts if is_main_artifact(artifact)]
    return sorted(selected, key=lambda artifact: artifact.get("created_at", ""), reverse=True)


@dataclass
class Fetchers:
    list_artifacts: Callable[[str], list[Mapping]]
    download_record: Callable[[Mapping], TimingRecord | None]
    pr_labels: Callable[[int], list[str]]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # surface the redirect as an HTTPError instead of following it
        return None


def _request(url: str, token: str) -> urllib.request.Request:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=headers)


def _get_json(url: str, token: str):
    with urllib.request.urlopen(_request(url, token), timeout=HTTP_TIMEOUT_S) as response:
        return json.load(response)


def _download_zip(url: str, token: str) -> bytes:
    """Fetch an artefact archive; the token is never sent to the blob-storage redirect target."""
    try:
        with urllib.request.build_opener(_NoRedirect()).open(_request(url, token), timeout=HTTP_TIMEOUT_S) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        location = exc.headers.get("Location")
        if exc.code not in REDIRECT_CODES or not location:
            raise
    with urllib.request.urlopen(location, timeout=HTTP_TIMEOUT_S) as response:
        return response.read()


def _event_labels(event_path: str) -> list[str]:
    try:
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [label["name"] for label in (event.get("pull_request") or {}).get("labels", [])]


def github_fetchers(api_url: str, repo: str, token: str, event_path: str = "") -> Fetchers:
    base = f"{api_url.rstrip('/')}/repos/{repo}"

    def list_artifacts(name: str) -> list[Mapping]:
        return _get_json(f"{base}/actions/artifacts?name={urllib.parse.quote(name)}&per_page=100", token)["artifacts"]

    def download_record(artifact: Mapping) -> TimingRecord | None:
        try:
            with zipfile.ZipFile(io.BytesIO(_download_zip(artifact["archive_download_url"], token))) as archive:
                return TimingRecord.from_json(archive.read(RECORD_FILE).decode("utf-8"))
        except (OSError, KeyError, TypeError, ValueError, zipfile.BadZipFile) as exc:
            notice(f"artefact {artifact.get('id')} could not be read ({exc}); skipped")
            return None

    def pr_labels(number: int) -> list[str]:
        # Read live so that re-running a job after adding the label honours it; the event payload of a re-run is stale.
        try:
            return [label["name"] for label in _get_json(f"{base}/issues/{number}/labels", token)]
        except (OSError, KeyError, TypeError, ValueError):
            return _event_labels(event_path)

    return Fetchers(list_artifacts, download_record, pr_labels)


# --- Command-line interface --------------------------------------------------------------------------------------


def _percent(text: str) -> float:
    return float(text) / 100


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CI timing regression gate (standard library only).")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("record", "write timing.json and enforce the ceiling"),
        ("compare", "gate a pull request"),
    ):
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("--workflow", required=True)
        sub.add_argument("--job", required=True)
        sub.add_argument("--os", required=True, dest="os_name", metavar="OS")
        sub.add_argument("--started-at", required=True, type=float, help="job start, epoch seconds")
        sub.add_argument("--junit", type=Path, help="pytest JUnit XML report for per-test times")
        sub.add_argument("--out", required=True, type=Path, help="directory for timing.json")
        sub.add_argument("--ceiling", type=float, default=300, help="absolute limit in seconds (default 300)")
    compare = commands.choices["compare"]
    compare.add_argument("--artifact-name", help="default: ci-timing-<job>-<os>")
    compare.add_argument("--baseline-count", type=int, default=5)
    compare.add_argument("--tolerance-percent", type=_percent, default=0.5, dest="tolerance")
    compare.add_argument("--min-delta", type=float, default=30)
    compare.add_argument("--accept-label", default=ACCEPT_LABEL)
    compare.add_argument("--pr-number", type=int)
    compare.add_argument("--test-tolerance-percent", type=_percent, default=0.5, dest="test_tolerance")
    compare.add_argument("--test-min-delta", type=float, default=5)
    compare.add_argument("--test-limit", type=int, default=10)
    return parser


def build_record(args: argparse.Namespace, now: float, env: Mapping[str, str]) -> TimingRecord:
    return TimingRecord(
        workflow=args.workflow,
        job=args.job,
        os=args.os_name,
        duration_s=round(now - args.started_at, 1),
        started_at=args.started_at,
        finished_at=now,
        sha=env.get("GITHUB_SHA", ""),
        run_id=env.get("GITHUB_RUN_ID", ""),
        tests=read_junit(args.junit),
    )


def write_record(record: TimingRecord, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / RECORD_FILE
    path.write_text(record.to_json() + "\n", encoding="utf-8")
    return path


def _summarise(lines: list[str], env: Mapping[str, str]) -> None:
    print("\n".join(lines))
    summary = env.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("```text\n" + "\n".join(lines) + "\n```\n")


def run_record(args: argparse.Namespace, now: float, env: Mapping[str, str]) -> int:
    record = build_record(args, now, env)
    path = write_record(record, args.out)
    print(f"{record.job} ({record.os}): {record.duration_s:.0f} s, {len(record.tests)} test times -> {path}")
    failure = check_ceiling(record.duration_s, args.ceiling)
    if failure:
        print(annotation("error", f"CI timing {record.job} ({record.os}): {failure}"))
    return 1 if failure else 0


def load_baseline(fetchers: Fetchers, name: str, count: int) -> list[TimingRecord]:
    """The most recent `count` readable main records; a listing failure means a cold start, never a crash."""
    try:
        artifacts = select_main_artifacts(fetchers.list_artifacts(name))
    except (OSError, KeyError, TypeError, ValueError) as exc:
        notice(f"artefact listing for {name} failed ({exc}); treating as 0 main records")
        return []
    records: list[TimingRecord] = []
    for artifact in artifacts:
        record = fetchers.download_record(artifact)
        records += [record] if record else []
        if len(records) >= count:
            break
    return records


def _accepted(fetchers: Fetchers, pr_number: int | None, label: str) -> bool:
    return pr_number is not None and label in fetchers.pr_labels(pr_number)


def run_compare(args: argparse.Namespace, fetchers: Fetchers, now: float, env: Mapping[str, str]) -> int:
    current = build_record(args, now, env)
    write_record(current, args.out)
    baseline = load_baseline(fetchers, args.artifact_name or artefact_name(args.job, args.os_name), args.baseline_count)
    verdict = decide(
        current.duration_s,
        [record.duration_s for record in baseline],
        count=args.baseline_count,
        tolerance=args.tolerance,
        min_delta=args.min_delta,
        ceiling=args.ceiling,
        accepted=_accepted(fetchers, args.pr_number, args.accept_label),
        accept_label=args.accept_label,
    )
    report = _test_report(args, current, baseline)
    _summarise([f"CI timing {current.job} ({current.os}): {verdict.status}, {current.duration_s:.0f} s", *report], env)
    _annotate(verdict, f"CI timing {current.job} ({current.os})", report)
    return 1 if verdict.status == "fail" else 0


def _test_report(args: argparse.Namespace, current: TimingRecord, baseline: list[TimingRecord]) -> list[str]:
    if args.junit is None:
        return []
    offenders = test_offenders(
        current.tests, baseline, tolerance=args.test_tolerance, min_delta=args.test_min_delta, limit=args.test_limit
    )
    lines = format_offenders(offenders, args.test_tolerance, args.test_min_delta)
    new = count_new_tests(current.tests, baseline)
    return lines + ([f"{new} new tests without a baseline"] if new else [])


def _annotate(verdict: Verdict, prefix: str, report: list[str]) -> None:
    for message in verdict.notices:
        notice(f"{prefix}: {message}")
    level = {"pass": "notice", "warn": "warning", "fail": "error"}[verdict.status]
    detail = "\n".join(["", "Slowest-growing tests:", *report]) if verdict.status == "fail" and report else ""
    if verdict.messages:
        print(annotation(level, f"{prefix}: " + "; ".join(verdict.messages) + detail))


def main(
    argv: list[str] | None = None,
    *,
    fetchers: Fetchers | None = None,
    now: Callable[[], float] = time.time,
    env: Mapping[str, str] = os.environ,
) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "record":
        return run_record(args, now(), env)
    if fetchers is None:
        fetchers = github_fetchers(
            env.get("GITHUB_API_URL", "https://api.github.com"),
            env.get("GITHUB_REPOSITORY", ""),
            env.get("GITHUB_TOKEN", ""),
            env.get("GITHUB_EVENT_PATH", ""),
        )
    return run_compare(args, fetchers, now(), env)


if __name__ == "__main__":
    sys.exit(main())
