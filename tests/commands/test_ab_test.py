from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from holon_coherence.commands.ab_test import (
    ABComparisonScorecard,
    ABRunConfig,
    handle,
    handle_ab_test,
    register,
    run_workload_ab_test,
)


def test_register_ab_test():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    ab_parser = register(subparsers)
    assert ab_parser is not None

    args = parser.parse_args(
        [
            "ab-test",
            "--command",
            "pytest tests",
            "--rounds",
            "3",
            "--live",
            "--fail-under-reduction",
            "15.0",
            "--json",
        ]
    )
    assert args.command == "ab-test"
    assert args.workload_cmd == "pytest tests"
    assert args.rounds == 3
    assert args.live is True
    assert args.fail_under_reduction == 15.0
    assert args.json is True
    assert args.handler == handle
    assert args.propagates_exit is True


def test_handle_ab_test_no_arguments(capsys):
    args = argparse.Namespace(
        command="ab-test",
        workload_cmd=None,
        trace_file=None,
        baseline=None,
        optimized=None,
        live=False,
        rounds=1,
        fail_under_reduction=None,
        json=False,
    )
    res = handle(args)
    assert res == 1
    err = capsys.readouterr().err
    assert "One of --command" in err


def test_handle_ab_test_invalid_fail_under(capsys):
    args = argparse.Namespace(
        command="ab-test",
        workload_cmd="echo test",
        trace_file=None,
        baseline=None,
        optimized=None,
        live=False,
        rounds=1,
        fail_under_reduction="invalid_float",
        json=False,
    )
    res = handle_ab_test(args)
    assert res == 1
    err = capsys.readouterr().err
    assert "must be a valid float" in err


def test_handle_ab_test_success_workload(capsys):
    args = argparse.Namespace(
        command="ab-test",
        workload_cmd="echo run",
        trace_file=None,
        baseline=None,
        optimized=None,
        live=False,
        rounds=1,
        fail_under_reduction=10.0,
        json=True,
    )
    mock_scorecard = ABComparisonScorecard(
        total_turns=2,
        token_reduction_pct=25.0,
        passed_threshold=True,
        semantic_parity_verified=True,
    )
    with patch("holon_coherence.commands.ab_test.run_workload_ab_test", return_value=mock_scorecard):
        res = handle(args)
        assert res == 0
        out = capsys.readouterr().out
        assert '"token_reduction_pct": 25.0' in out


def test_run_workload_ab_test_cleans_up_temp_dirs_on_success():
    captured_dirs: list[Path] = []
    mock_scorecard = ABComparisonScorecard(
        total_turns=1,
        token_reduction_pct=20.0,
        passed_threshold=True,
        semantic_parity_verified=True,
    )

    def fake_run(_cmd, *, shell, env):
        assert shell is True
        wire_dir = Path(env["WIRE_LOG_DIR"])
        assert wire_dir.is_dir()
        captured_dirs.append(wire_dir)
        return MagicMock(returncode=0)

    with (
        patch("holon_coherence.commands.runner.build_proxy_env", return_value={}),
        patch("holon_coherence.commands.ab_test.set_proxy_mode", return_value=True),
        patch("holon_coherence.commands.ab_test.subprocess.run", side_effect=fake_run),
        patch("holon_coherence.commands.ab_test.load_transactions_from_path", return_value=[]),
        patch("holon_coherence.commands.ab_test.evaluate_runs", return_value=mock_scorecard),
    ):
        result = run_workload_ab_test(ABRunConfig(command="echo ok"))

    assert result is mock_scorecard
    assert len(captured_dirs) == 2
    baseline_dir, optimized_dir = captured_dirs
    assert baseline_dir.name == "baseline"
    assert optimized_dir.name == "optimized"
    assert baseline_dir.parent == optimized_dir.parent
    session_dir = baseline_dir.parent
    assert not baseline_dir.exists()
    assert not optimized_dir.exists()
    assert not session_dir.exists()


def test_run_workload_ab_test_cleans_up_temp_dirs_on_workload_exception():
    captured_dirs: list[Path] = []

    def fake_run(_cmd, *, shell, env):
        assert shell is True
        wire_dir = Path(env["WIRE_LOG_DIR"])
        assert wire_dir.is_dir()
        captured_dirs.append(wire_dir)
        raise RuntimeError("workload crashed")

    with (
        patch("holon_coherence.commands.runner.build_proxy_env", return_value={}),
        patch("holon_coherence.commands.ab_test.set_proxy_mode", return_value=True),
        patch("holon_coherence.commands.ab_test.subprocess.run", side_effect=fake_run),
        patch("holon_coherence.commands.ab_test.load_transactions_from_path", return_value=[]),
        patch("holon_coherence.commands.ab_test.evaluate_runs"),
        pytest.raises(RuntimeError, match="workload crashed"),
    ):
        run_workload_ab_test(ABRunConfig(command="echo fail"))

    assert len(captured_dirs) == 1
    wire_dir = captured_dirs[0]
    assert not wire_dir.exists()
    assert not wire_dir.parent.exists()
