"""Unit tests for scripts/check_ci_runtime_budget.py."""

from __future__ import annotations

import pathlib
from unittest import mock

from scripts import check_ci_runtime_budget


def test_missing_or_empty_start_epoch(capsys):
    ret = check_ci_runtime_budget.main(["--start-epoch", "", "--max-seconds", "300"])
    assert ret == 0
    captured = capsys.readouterr().out
    assert "skipping runtime budget check" in captured


def test_invalid_start_epoch(capsys):
    ret = check_ci_runtime_budget.main(["--start-epoch", "not-a-number", "--max-seconds", "300"])
    assert ret == 0
    captured = capsys.readouterr().out
    assert "invalid start epoch" in captured


def test_negative_start_epoch(capsys):
    ret = check_ci_runtime_budget.main(["--start-epoch", "-100", "--max-seconds", "300"])
    assert ret == 0
    captured = capsys.readouterr().out
    assert "non-positive start epoch" in captured


def test_budget_within_limit(tmp_path: pathlib.Path, capsys):
    summary_file = tmp_path / "step_summary.md"
    start_time = 1000.0
    now_time = 1100.0  # elapsed 100s <= 300s budget

    with mock.patch("time.time", return_value=now_time):
        ret = check_ci_runtime_budget.main(
            [
                "--start-epoch",
                str(start_time),
                "--max-seconds",
                "300",
                "--step-summary",
                str(summary_file),
            ]
        )

    assert ret == 0
    out = capsys.readouterr().out
    assert "within budget" in out
    assert summary_file.exists()
    content = summary_file.read_text(encoding="utf-8")
    assert "### CI Runtime Budget Check" in content
    assert "| Budget Utilisation |" in content
    assert "| Status | PASS |" in content
    assert "100.0 s" in content


def test_budget_exceeded(tmp_path: pathlib.Path, capsys):
    summary_file = tmp_path / "step_summary.md"
    start_time = 1000.0
    now_time = 1400.0  # elapsed 400s > 300s budget

    with mock.patch("time.time", return_value=now_time):
        ret = check_ci_runtime_budget.main(
            [
                "--start-epoch",
                str(start_time),
                "--max-seconds",
                "300",
                "--step-summary",
                str(summary_file),
            ]
        )

    assert ret == 1
    out = capsys.readouterr().out
    assert "::error::Job runtime (400.0s) exceeded budget (300.0s)" in out
    assert summary_file.exists()
    content = summary_file.read_text(encoding="utf-8")
    assert "### CI Runtime Budget Check" in content
    assert "| Status | FAIL |" in content
    assert "400.0 s" in content


def test_zero_max_seconds(tmp_path: pathlib.Path, capsys):
    summary_file = tmp_path / "step_summary.md"
    start_time = 1000.0
    now_time = 1005.0

    with mock.patch("time.time", return_value=now_time):
        ret = check_ci_runtime_budget.main(
            [
                "--start-epoch",
                str(start_time),
                "--max-seconds",
                "0",
                "--step-summary",
                str(summary_file),
            ]
        )

    assert ret == 1
    content = summary_file.read_text(encoding="utf-8")
    assert "N/A" in content
    assert "N/A%" not in content
