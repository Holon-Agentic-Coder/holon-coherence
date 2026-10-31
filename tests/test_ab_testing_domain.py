"""Unit tests for A/B testing evaluation domain module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from holon_coherence.ab_testing.evaluation import (
    ABComparisonScorecard,
    ABRunConfig,
    evaluate_offline_ab_run,
    evaluate_runs,
    load_trace_transactions,
    load_transactions_from_path,
)


def test_load_trace_transactions_json_array(tmp_path: Path) -> None:
    """Load trace transactions from JSON array file."""
    fpath = tmp_path / "trace_array.json"
    records = [{"turn_id": "t1", "raw_request": {"request": {"messages": [{"role": "user", "content": "hello"}]}}}]
    fpath.write_text(json.dumps(records), encoding="utf-8")

    loaded = load_trace_transactions(str(fpath))
    assert len(loaded) == 1
    assert loaded[0]["turn_id"] == "t1"


def test_load_trace_transactions_jsonl_with_corrupt_lines(tmp_path: Path) -> None:
    """Load trace transactions from JSONL, skipping unparseable lines."""
    fpath = tmp_path / "trace.jsonl"
    fpath.write_text(
        "   \n"
        '{"turn_id": "t1", "raw_request": {"request": {"messages": []}}}\n'
        "not json\n"
        '{"turn_id": "t2", "raw_request": {"request": {"messages": []}}}\n',
        encoding="utf-8",
    )
    loaded = load_trace_transactions(str(fpath))
    assert len(loaded) == 2
    assert loaded[0]["turn_id"] == "t1"
    assert loaded[1]["turn_id"] == "t2"


def test_load_trace_transactions_nonexistent() -> None:
    """Missing file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_trace_transactions("nonexistent_path_xyz.jsonl")


def test_load_trace_transactions_empty(tmp_path: Path) -> None:
    """Empty file raises ValueError."""
    fpath = tmp_path / "empty.jsonl"
    fpath.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="No valid transaction records"):
        load_trace_transactions(str(fpath))


def test_load_transactions_from_path_dir_walk(tmp_path: Path) -> None:
    """Walk directory to find .jsonl and turn_*.json files."""
    subdir = tmp_path / "traces"
    subdir.mkdir()
    (subdir / "run1.jsonl").write_text('{"turn_id": "t1"}\n', encoding="utf-8")
    (subdir / "turn_002.json").write_text('{"turn_id": "t2"}', encoding="utf-8")

    txs = load_transactions_from_path(str(subdir))
    turn_ids = {t["turn_id"] for t in txs}
    assert turn_ids == {"t1", "t2"}


def test_evaluate_offline_ab_run_parity_failure() -> None:
    """Detect semantic parity discrepancy when messages are missing from optimized payload."""
    tx = {
        "turn_id": "t-discrepancy",
        "provider": "anthropic",
        "raw_request": {
            "request": {
                "messages": [{"role": "user", "content": "hello"}],
            }
        },
        "response": {"usage": {"input_tokens": 100}},
    }

    class DummyCleaner:
        def process_payload_with_stats(self, payload: dict, provider: str = "anthropic"):
            from unittest.mock import MagicMock

            res = MagicMock()
            res.payload = {"no_messages": True}
            res.tool_outputs_omitted = 0
            res.cache_control_injected = 0
            return res

    scorecard = evaluate_offline_ab_run([tx], cleaner=DummyCleaner())
    assert scorecard.semantic_parity_verified is False


def test_evaluate_runs_different_turn_lengths() -> None:
    """Evaluate runs with unequal turns by pairing up to minimum turn count."""
    base_txs = [
        {
            "turn_id": "t1",
            "provider": "anthropic",
            "mode": "baseline",
            "raw_request": {"request": {"messages": [{"role": "user", "content": "hi"}]}},
            "response": {"status": 200, "usage": {"input_tokens": 1000}},
            "timing": {"ttft_ms": 100.0, "decode_tps": 50.0},
        },
        {
            "turn_id": "t2",
            "provider": "anthropic",
            "mode": "baseline",
            "raw_request": {"request": {"messages": [{"role": "user", "content": "hi 2"}]}},
            "response": {"status": 200, "usage": {"input_tokens": 1200}},
        },
    ]
    opt_txs = [
        {
            "turn_id": "t1",
            "provider": "anthropic",
            "mode": "optimized",
            "raw_request": {"request": {"messages": [{"role": "user", "content": "hi"}]}},
            "cleaned_request": {"request": {"messages": [{"role": "user", "content": "hi"}]}},
            "response": {"status": 200, "usage": {"input_tokens": 700}},
            "timing": {"ttft_ms": 80.0, "decode_tps": 60.0},
        }
    ]

    scorecard = evaluate_runs(base_txs, opt_txs, fail_under_reduction=20.0)
    assert scorecard.total_turns == 1
    assert scorecard.baseline_input_tokens == 1000
    assert scorecard.optimized_input_tokens == 700
    assert scorecard.tokens_reduced == 300
    assert scorecard.token_reduction_pct == 30.0
    assert scorecard.passed_threshold is True
    assert scorecard.baseline_ttft_ms == 100.0
    assert scorecard.optimized_ttft_ms == 80.0
    assert scorecard.ttft_delta_ms == 20.0
