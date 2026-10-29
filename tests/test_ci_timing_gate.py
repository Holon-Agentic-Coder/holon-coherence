"""Unit tests for scripts/ci_timing_gate.py.

The fetchers are injected fakes, so nothing here reaches the network or the GitHub API. The fakes exercise decision
logic only; the calibration replay at the end uses the real job durations measured on `main`.
"""

from __future__ import annotations

import http.client
import json
import pathlib

import pytest

from scripts import ci_timing_gate
from scripts.ci_timing_gate import (
    ACCEPT_LABEL,
    Fetchers,
    Offender,
    Skip,
    TimingRecord,
    _request,
    artefact_name,
    check_ceiling,
    check_relative,
    count_new_tests,
    decide,
    format_offenders,
    github_fetchers,
    main,
    parse_junit,
    read_junit,
    rolling_median,
    select_main_artifacts,
    test_offenders,
)

RULES = {"count": 5, "tolerance": 0.5, "min_delta": 30.0, "ceiling": 300.0, "accepted": False}


@pytest.fixture(autouse=True)
def _no_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)


def make_record(duration: float, tests: dict[str, float] | None = None) -> TimingRecord:
    return TimingRecord("Test - Unit", "unit", "Linux", duration, 0.0, duration, tests=tests or {})


def main_artifact(index: int, **run_overrides) -> dict:
    run = {"id": index, "head_branch": "main", "repository_id": 1, "head_repository_id": 1, **run_overrides}
    return {"id": index, "expired": False, "created_at": f"2026-10-{28 - index:02d}T00:00:00Z", "workflow_run": run}


def fake_fetchers(records: list[TimingRecord], labels: tuple[str, ...] = ()) -> Fetchers:
    """Records are given most recent first."""
    artifacts = [main_artifact(index) for index in range(len(records))]
    return Fetchers(
        list_artifacts=lambda name: list(reversed(artifacts)),
        download_record=lambda artifact: records[artifact["id"]],
        pr_labels=lambda number: list(labels),
    )


def run_compare(tmp_path, duration, fetchers, *extra, env=None) -> int:
    argv = [
        "compare",
        *("--workflow", "Test - Unit", "--job", "unit", "--os", "Linux", "--started-at", "1000"),
        *("--out", str(tmp_path / "out"), "--baseline-count", "5", "--tolerance-percent", "50"),
        *("--min-delta", "30", "--ceiling", "300", "--pr-number", "7"),
        *extra,
    ]
    return main(argv, fetchers=fetchers, now=lambda: 1000 + duration, env=env or {})


def write_junit(path: pathlib.Path, times: dict[str, float]) -> pathlib.Path:
    cases = "".join(
        f'<testcase classname="{test.split("::")[0]}" name="{test.split("::")[1]}" time="{seconds}" />'
        for test, seconds in times.items()
    )
    path.write_text(f'<?xml version="1.0"?><testsuites><testsuite name="pytest">{cases}</testsuite></testsuites>')
    return path


# --- 1. Rolling median ---------------------------------------------------------------------------------------------


def test_rolling_median_odd_and_even():
    assert rolling_median([3, 1, 2]) == 2
    assert rolling_median([4, 1, 3, 2]) == 2.5


def test_only_most_recent_count_records_form_the_baseline():
    # Most recent five have median 60; the stale 1000 s record must not count.
    assert check_relative(85, [60, 60, 60, 60, 60, 1000], 5, 0.5, 30) is None
    assert check_relative(100, [60, 60, 60, 60, 60, 10], 5, 0.5, 30) is not None


def test_compare_downloads_only_count_records(tmp_path):
    downloaded = []
    records = [make_record(60)] * 8
    fetchers = fake_fetchers(records)
    inner = fetchers.download_record
    fetchers.download_record = lambda artifact: downloaded.append(artifact["id"]) or inner(artifact)
    assert run_compare(tmp_path, 60, fetchers) == 0
    assert downloaded == [0, 1, 2, 3, 4]


# --- 2-3. Relative rule --------------------------------------------------------------------------------------------


def test_pass_inside_tolerance():
    assert decide(140, [100] * 5, **RULES).status == "pass"  # +40 %, +40 s
    assert decide(135, [100] * 5, **RULES).status == "pass"  # +35 %, +35 s


@pytest.mark.parametrize(
    ("median", "current", "status"),
    [
        (30, 50, "pass"),  # +67 %, +20 s: delta below the floor
        (200, 240, "pass"),  # +20 %, +40 s: below the tolerance
        (60, 100, "fail"),  # +67 %, +40 s: both exceeded
        (60, 90, "pass"),  # exactly +50 % and exactly +30 s
        (100, 150, "pass"),  # exactly +50 %, +50 s
        (20, 50, "pass"),  # +150 %, exactly +30 s
    ],
)
def test_both_thresholds_must_be_exceeded(median, current, status):
    assert decide(current, [median] * 5, **RULES).status == status


def test_relative_failure_message_states_numbers_and_thresholds():
    message = check_relative(100, [60] * 5, 5, 0.5, 30)
    assert isinstance(message, str)
    for fragment in ("100 s", "+67%", "+40 s", "median 60 s", "50%", "30 s"):
        assert fragment in message


# --- 4. Ceiling ----------------------------------------------------------------------------------------------------


def test_ceiling_boundary():
    assert check_ceiling(300, 300) is None
    assert "300 s" in check_ceiling(301, 300)


def test_ceiling_fails_with_matching_baseline_and_without_baseline():
    assert decide(301, [301] * 5, **RULES).status == "fail"
    assert decide(301, [], **RULES).status == "fail"
    assert decide(300, [], **RULES).status == "pass"


# --- 5. Cold start -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("available", [0, 4])
def test_cold_start_skips_relative_check(tmp_path, capsys, available):
    fetchers = fake_fetchers([make_record(10)] * available)
    assert run_compare(tmp_path, 200, fetchers) == 0
    assert f"relative check skipped: only {available} of 5 main records; ceiling only" in capsys.readouterr().out
    assert run_compare(tmp_path, 301, fetchers) == 1


def test_check_relative_returns_skip_when_baseline_short():
    assert isinstance(check_relative(500, [10] * 4, 5, 0.5, 30), Skip)


def test_listing_failure_degrades_to_cold_start(tmp_path, capsys):
    def broken(name):
        raise OSError("HTTP 502")

    fetchers = Fetchers(broken, lambda artifact: None, lambda number: [])
    assert run_compare(tmp_path, 200, fetchers) == 0
    out = capsys.readouterr().out
    assert "treating as 0 main records" in out
    assert "relative check skipped: only 0 of 5" in out


def test_truncated_http_response_degrades_to_cold_start(tmp_path, capsys):
    def truncated(name):
        raise http.client.IncompleteRead(b"")

    fetchers = Fetchers(truncated, lambda artifact: None, lambda number: [])
    assert run_compare(tmp_path, 200, fetchers) == 0
    assert "treating as 0 main records" in capsys.readouterr().out


def test_pr_labels_fall_back_to_event_on_truncated_response(monkeypatch, tmp_path, capsys):
    def truncated(url, token):
        raise http.client.IncompleteRead(b"")

    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"labels": [{"name": ACCEPT_LABEL}]}}))
    monkeypatch.setattr(ci_timing_gate, "_get_json", truncated)
    assert github_fetchers("https://example.invalid", "o/r", "", str(event)).pr_labels(7) == [ACCEPT_LABEL]
    assert "using the event payload labels" in capsys.readouterr().out


@pytest.mark.parametrize("payload", [[], {"pull_request": {"labels": [{"id": 1}]}}, {"pull_request": {"labels": 3}}])
def test_malformed_event_payload_yields_no_labels(tmp_path, payload):
    event = tmp_path / "event.json"
    event.write_text(json.dumps(payload))
    assert ci_timing_gate._event_labels(str(event)) == []


def test_download_record_skips_truncated_archive(monkeypatch, capsys):
    def truncated(url, token):
        raise http.client.IncompleteRead(b"")

    monkeypatch.setattr(ci_timing_gate, "_download_zip", truncated)
    fetchers = github_fetchers("https://example.invalid", "o/r", "")
    assert fetchers.download_record({"id": 3, "archive_download_url": "https://example.invalid/zip"}) is None
    assert "artefact 3 could not be read" in capsys.readouterr().out


def test_download_attempts_are_capped(tmp_path, capsys):
    attempts = []
    fetchers = fake_fetchers([make_record(60)] * 20)
    fetchers.download_record = lambda artifact: attempts.append(artifact["id"])
    assert run_compare(tmp_path, 200, fetchers) == 0
    assert len(attempts) == 10
    assert "stopped after 10 artefact downloads" in capsys.readouterr().out


@pytest.mark.parametrize("started_at", ["", "nan", "inf"])
@pytest.mark.parametrize("command", ["record", "compare"])
def test_missing_start_timestamp_skips_the_gate(tmp_path, capsys, command, started_at):
    argv = [command, "--workflow", "w", "--job", "unit", "--os", "Linux", "--started-at", started_at]
    argv += ["--out", str(tmp_path)]
    assert main(argv, fetchers=fake_fetchers([]), now=lambda: 1000, env={}) == 0
    assert "no start timestamp; gate skipped" in capsys.readouterr().out
    assert not (tmp_path / "timing.json").exists()


def test_unreadable_artefacts_shrink_the_baseline(tmp_path, capsys):
    fetchers = fake_fetchers([make_record(60)] * 5)
    fetchers.download_record = lambda artifact: None if artifact["id"] == 0 else make_record(60)
    assert run_compare(tmp_path, 200, fetchers) == 0
    assert "only 4 of 5" in capsys.readouterr().out


# --- 6. Label override ---------------------------------------------------------------------------------------------


def test_label_turns_relative_failure_into_warning(tmp_path, capsys):
    records = [make_record(60)] * 5
    assert run_compare(tmp_path, 100, fake_fetchers(records)) == 1
    assert "::error::" in capsys.readouterr().out
    assert run_compare(tmp_path, 100, fake_fetchers(records, labels=(ACCEPT_LABEL,))) == 0
    out = capsys.readouterr().out
    assert "::warning::" in out
    assert f"accepted by the pull-request label '{ACCEPT_LABEL}'" in out


def test_label_never_overrides_the_ceiling(tmp_path):
    assert decide(301, [100] * 5, **{**RULES, "accepted": True}).status == "fail"
    assert run_compare(tmp_path, 301, fake_fetchers([make_record(100)] * 5, labels=(ACCEPT_LABEL,))) == 1


def test_labels_not_read_without_pr_number(tmp_path):
    def unexpected(number):
        raise AssertionError("labels must not be read")

    fetchers = fake_fetchers([make_record(60)] * 5)
    fetchers.pr_labels = unexpected
    argv = ["compare", "--workflow", "w", "--job", "unit", "--os", "Linux", "--started-at", "0"]
    assert main([*argv, "--out", str(tmp_path)], fetchers=fetchers, now=lambda: 60, env={}) == 0


# --- 7. Per-test report --------------------------------------------------------------------------------------------


def test_offenders_ordered_by_delta_with_both_thresholds_and_limit():
    baseline = [make_record(60, {f"t::{i}": 10.0 for i in range(15)} | {"t::small": 2.0, "t::flat": 20.0})] * 3
    current = {f"t::{i}": 16.0 + i for i in range(15)} | {"t::small": 6.0, "t::flat": 26.0}
    offenders = test_offenders(current, baseline)
    assert [o.test for o in offenders] == [f"t::{i}" for i in range(14, 4, -1)]
    assert len(offenders) == 10
    # t::small is +200 % but only +4 s; t::flat is +6 s but only +30 %
    assert {"t::small", "t::flat"}.isdisjoint(o.test for o in offenders)
    assert len(test_offenders(current, baseline, limit=3)) == 3


def test_offender_boundaries_and_new_tests():
    baseline = [make_record(60, {"a::x": 10.0})]
    assert test_offenders({"a::x": 15.0}, baseline) == []  # exactly +50 % and +5 s
    assert test_offenders({"a::x": 15.1}, baseline) == [Offender("a::x", 10.0, 15.1)]
    assert count_new_tests({"a::x": 1.0, "a::new": 1.0}, baseline) == 1


def test_format_offenders():
    assert format_offenders([]) == ["no test grew by more than 50% and 5 s"]
    lines = format_offenders([Offender("tests.t::slow", 10.0, 25.0)])
    assert "tests.t::slow" in lines[1]
    assert "+15.0s" in lines[1]
    assert "+150%" in lines[1]


def test_report_printed_on_passing_run_without_changing_exit(tmp_path, capsys):
    junit = write_junit(tmp_path / "junit.xml", {"t.m::slow": 40.0})
    records = [make_record(60, {"t.m::slow": 10.0})] * 5
    assert run_compare(tmp_path, 60, fake_fetchers(records), "--junit", str(junit)) == 0
    out = capsys.readouterr().out
    assert "t.m::slow" in out
    assert "::error::" not in out


def test_report_without_baseline_skips_per_test_comparison(tmp_path, capsys):
    junit = write_junit(tmp_path / "junit.xml", {"t.m::slow": 40.0})
    assert run_compare(tmp_path, 60, fake_fetchers([]), "--junit", str(junit)) == 0
    out = capsys.readouterr().out
    assert "no main baseline yet; per-test comparison skipped" in out
    assert "no test grew" not in out
    assert "new tests without a baseline" not in out


def test_report_appended_to_failure_message(tmp_path, capsys):
    junit = write_junit(tmp_path / "junit.xml", {"t.m::slow": 40.0, "t.m::new": 1.0})
    records = [make_record(60, {"t.m::slow": 10.0})] * 5
    assert run_compare(tmp_path, 120, fake_fetchers(records), "--junit", str(junit)) == 1
    error = next(line for line in capsys.readouterr().out.splitlines() if line.startswith("::error::"))
    assert "Slowest-growing tests:" in error
    assert "t.m::slow" in error
    assert "1 new tests without a baseline" in error


def test_step_summary_is_appended(tmp_path):
    summary = tmp_path / "summary.md"
    summary.write_text("existing\n")
    run_compare(tmp_path, 60, fake_fetchers([make_record(60)] * 5), env={"GITHUB_STEP_SUMMARY": str(summary)})
    text = summary.read_text()
    assert text.startswith("existing\n")
    assert "CI timing unit (Linux): pass, 60 s" in text


# --- 8. JUnit parsing ----------------------------------------------------------------------------------------------


def test_parse_junit_testsuites_root():
    text = (
        '<?xml version="1.0" encoding="utf-8"?><testsuites name="pytest tests"><testsuite name="pytest">'
        '<testcase classname="tests.test_a.TestX" name="test_one" time="1.5" />'
        '<testcase classname="tests.test_a" name="test_param[a-1]" time="0.25"><skipped /></testcase>'
        '<testcase classname="tests.test_a" name="test_no_time" />'
        "</testsuite></testsuites>"
    )
    assert parse_junit(text) == {
        "tests.test_a.TestX::test_one": 1.5,
        "tests.test_a::test_param[a-1]": 0.25,
        "tests.test_a::test_no_time": 0.0,
    }


def test_parse_junit_bare_testsuite_and_duplicates():
    case = '<testcase classname="c" name="n" time="{}" />'
    text = f"<testsuite>{case.format(1)}{case.format(2)}</testsuite>"
    assert parse_junit(text) == {"c::n": 3.0}


def test_read_junit_missing_and_malformed(tmp_path, capsys):
    assert read_junit(None) == {}
    assert read_junit(tmp_path / "absent.xml") == {}
    bad = tmp_path / "bad.xml"
    bad.write_text("<testsuite")
    assert read_junit(bad) == {}
    assert "per-test times omitted" in capsys.readouterr().out


# --- 9. Record mode ------------------------------------------------------------------------------------------------


def test_record_writes_timing_json(tmp_path, capsys):
    junit = write_junit(tmp_path / "junit.xml", {"t.m::a": 1.25})
    argv = ["record", "--workflow", "Test - Unit", "--job", "unit", "--os", "macOS", "--started-at", "1000"]
    argv += ["--junit", str(junit), "--out", str(tmp_path / "out"), "--ceiling", "300"]
    env = {"GITHUB_SHA": "abc123", "GITHUB_RUN_ID": "42"}
    assert main(argv, now=lambda: 1115.04, env=env) == 0
    data = json.loads((tmp_path / "out" / "timing.json").read_text())
    assert data["job"] == "unit"
    assert data["os"] == "macOS"
    assert data["duration_s"] == 115.0
    assert data["tests"] == {"t.m::a": 1.25}
    assert data["sha"] == "abc123"
    assert data["run_id"] == "42"
    assert "unit (macOS): 115 s" in capsys.readouterr().out


def test_record_enforces_ceiling(tmp_path, capsys):
    argv = ["record", "--workflow", "w", "--job", "unit", "--os", "Linux", "--started-at", "0", "--out", str(tmp_path)]
    assert main(argv, now=lambda: 301, env={}) == 1
    assert "::error::" in capsys.readouterr().out
    assert main(argv, now=lambda: 300, env={}) == 0


def test_record_round_trip_and_unknown_schema(capsys):
    record = make_record(53, {"a::b": 1.0})
    assert TimingRecord.from_json(record.to_json()) == record
    assert TimingRecord.from_json(json.dumps({"schema": 2, "job": "unit"})) is None
    assert "unknown schema 2" in capsys.readouterr().out
    assert TimingRecord.from_json("[]") is None
    assert "not a JSON object" in capsys.readouterr().out


@pytest.mark.parametrize(
    "overrides",
    [
        {"duration_s": None},
        {"duration_s": "53"},
        {"duration_s": True},
        {"duration_s": 0},
        {"duration_s": float("nan")},
        {"tests": ["a::b"]},
        {"tests": {"a::b": "1.0"}},
        {"tests": {"a::b": None}},
    ],
)
def test_record_with_malformed_values_is_ignored(overrides, capsys):
    data = {**json.loads(make_record(53, {"a::b": 1.0}).to_json()), **overrides}
    assert TimingRecord.from_json(json.dumps(data)) is None
    assert "non-numeric duration or test time" in capsys.readouterr().out


def test_malformed_record_shrinks_the_baseline(tmp_path, capsys):
    bad = TimingRecord.from_json(json.dumps({**json.loads(make_record(60).to_json()), "duration_s": None}))
    assert bad is None
    assert run_compare(tmp_path, 200, fake_fetchers([bad] + [make_record(60)] * 4)) == 0
    assert "only 4 of 5 main records" in capsys.readouterr().out


def test_artefact_name():
    assert artefact_name("unit", "macOS") == "ci-timing-unit-macOS"


# --- 10. Artefact filtering ----------------------------------------------------------------------------------------


def test_select_main_artifacts_filters_and_orders():
    newest, older = main_artifact(0), main_artifact(3)
    expired = {**main_artifact(1), "expired": True}
    branch = main_artifact(2, head_branch="feature")
    fork = main_artifact(4, head_repository_id=99)
    no_run = {"id": 5, "expired": False, "created_at": "2026-10-01T00:00:00Z"}
    assert select_main_artifacts([older, expired, fork, newest, branch, no_run]) == [newest, older]


def test_request_omits_authorisation_without_token():
    assert _request("https://example.invalid", "").get_header("Authorization") is None
    assert _request("https://example.invalid", "t").get_header("Authorization") == "Bearer t"


# --- 11. Replay of the real calibration durations ------------------------------------------------------------------
# Job wall clock (seconds) from the GitHub API for successful main pushes, 2026-10-09 to 2026-10-24.

# Previous main 29b7e50 -> latest main acbe924, the previous value as a one-record baseline.
CONSECUTIVE_MAIN_RUNS = [
    ("unit ubuntu", 62, 53),
    ("unit macOS", 102, 115),
    ("integration", 81, 79),
    ("hygiene", 54, 49),
    ("docker-build", 33, 39),
]

# Worst healthy deviations against the median of the previous five main runs, reconstructed as (median, current)
# from the measured percentage and delta.
WORST_HEALTHY_DEVIATIONS = [
    ("unit ubuntu +38 %/+24 s", 63, 87),
    ("integration +31 %/+22 s", 71, 93),
    ("unit macOS +28 %/+26 s", 93, 119),
]


@pytest.mark.parametrize(("job", "previous", "latest"), CONSECUTIVE_MAIN_RUNS)
def test_replay_consecutive_main_runs_pass(job, previous, latest):
    assert decide(latest, [previous], **{**RULES, "count": 1}).status == "pass", job


@pytest.mark.parametrize(("job", "median", "current"), WORST_HEALTHY_DEVIATIONS)
def test_replay_worst_healthy_deviations_pass(job, median, current):
    assert decide(current, [median] * 5, **RULES).status == "pass", job


def test_replay_window_maximum_passes_ceiling():
    assert check_ceiling(130, 300) is None  # largest job in the window: unit macOS


def test_replay_negative_control_doubling_fails():
    assert decide(106, [53] * 5, **RULES).status == "fail"  # latest unit ubuntu job doubled
