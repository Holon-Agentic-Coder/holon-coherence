"""Unit tests for holon_coherence.commands.ab_test registration and dispatch."""

from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

from holon_coherence.commands.ab_test import ABComparisonScorecard, handle, handle_ab_test, register


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
