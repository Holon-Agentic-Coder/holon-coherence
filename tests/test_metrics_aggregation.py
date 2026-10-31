"""Unit tests for offline wire log metrics aggregation domain module."""

from __future__ import annotations

import json
from pathlib import Path

from holon_coherence.ab_testing.evaluation import (
    ABComparisonScorecard,
    AbEvaluation,
    AbRun,
)
from holon_coherence.metrics.aggregation import (
    OfflineMetricsAccumulator,
    _compute_metrics_summary,
    _milliseconds_to_seconds,
    _process_record_cache_and_deltas,
    _process_record_timing,
    _process_record_usage,
    _stored_rate,
    read_offline_metrics,
)


def test_ab_testing_domain_aliases() -> None:
    """Verify that domain aliases and format_console work correctly."""
    assert AbRun is not None
    scorecard = AbEvaluation(total_turns=2, baseline_input_tokens=1000, optimized_input_tokens=800)
    assert isinstance(scorecard, ABComparisonScorecard)
    assert scorecard.format_console() == scorecard.render_table()
    data = scorecard.to_dict()
    assert data["summary"]["total_turns"] == 2


def test_milliseconds_to_seconds_and_stored_rate() -> None:
    """Verify timing helper conversions and stored rate resolution."""
    assert _milliseconds_to_seconds(None) is None
    assert _milliseconds_to_seconds("invalid") is None
    assert _milliseconds_to_seconds(1500) == 1.5

    assert _stored_rate(45.5, 30.0) == 45.5
    assert _stored_rate(None, 30.0) == 30.0
    assert _stored_rate(0.0, 30.0) is None


def test_read_offline_metrics_nonexistent(tmp_path: Path) -> None:
    """Missing transactions.jsonl returns None."""
    assert read_offline_metrics(str(tmp_path / "nonexistent")) is None


def test_read_offline_metrics_empty(tmp_path: Path) -> None:
    """Empty transactions.jsonl returns None."""
    log_file = tmp_path / "transactions.jsonl"
    log_file.write_text("\n\n   \n", encoding="utf-8")
    assert read_offline_metrics(str(tmp_path)) is None


def test_read_offline_metrics_authentic_records(tmp_path: Path) -> None:
    """Aggregate authentic wire-log records with multi-turn counters and throughput."""
    records = [
        {
            "turn_id": "turn-1",
            "cache_action": "HIT",
            "delta": {
                "tool_outputs_omitted": 2,
                "chars_saved": 400,
                "turns_summarized": 1,
                "cache_control_injected": 1,
            },
            "response": {
                "usage": {
                    "input_tokens": 1000,
                    "output_tokens": 200,
                    "cache_read_input_tokens": 600,
                    "cache_creation_input_tokens": 100,
                    "reasoning_tokens": 50,
                }
            },
            "timing": {
                "ttft_ms": 250.0,
                "total_ms": 1250.0,
                "prefill_tps": 4000.0,
                "tail_prefill_tps": 1600.0,
                "decode_tps": 200.0,
            },
        },
        {
            "turn_id": "turn-2",
            "cache_action": "MISS",
            "delta": {
                "tool_outputs_omitted": 1,
                "chars_saved": 200,
                "turns_summarized": 0,
                "cache_control_injected": 0,
            },
            "response": {
                "usage": {
                    "input_tokens": 1500,
                    "output_tokens": 300,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                    "reasoning_tokens": 0,
                }
            },
            "timing": {
                "ttft_ms": 500.0,
                "total_ms": 2000.0,
                "decode_tps": 200.0,
            },
        },
    ]

    log_file = tmp_path / "transactions.jsonl"
    with log_file.open("w", encoding="utf-8") as f:
        # Include an unparseable line to verify error resilience
        f.write("{invalid json line\n")
        for r in records:
            f.write(json.dumps(r) + "\n")

    summary = read_offline_metrics(str(tmp_path))
    assert summary is not None
    assert summary["total_requests"] == 2
    assert summary["total_turns"] == 2
    assert summary["cache_hits"] == 1
    assert summary["cache_misses"] == 1
    assert summary["cache_hit_rate"] == 0.5
    assert summary["tool_calls_pruned"] == 3
    assert summary["chars_saved"] == 600
    assert summary["tokens_reduced"] == 150
    assert summary["turns_summarized"] == 1
    assert summary["cache_control_injected"] == 1
    assert summary["total_input_tokens"] == 2500
    assert summary["total_output_tokens"] == 500
    assert summary["total_cache_read_tokens"] == 600
    assert summary["total_cache_creation_tokens"] == 100
    assert summary["total_reasoning_tokens"] == 50
    assert summary["provider_cache_hit_rate"] == 0.24
    assert summary["avg_ttft_ms"] == 375.0
    assert summary["avg_decode_throughput_tps"] == 200.0
    assert summary["source"] == "offline_wire_log"


def test_offline_metrics_accumulator_subroutines() -> None:
    """Directly test subroutines handling delta, usage, and timing."""
    state = OfflineMetricsAccumulator()
    rec = {
        "turn_id": "test-1",
        "cache_action": "HIT",
        "delta": {"tool_outputs_omitted": 4, "chars_saved": 800},
        "response": {"usage": {"input_tokens": 500, "output_tokens": 100}},
        "timing": {"ttft_ms": 100.0, "total_ms": 600.0},
    }

    _process_record_cache_and_deltas(rec, state)
    in_toks, out_toks, cache_read = _process_record_usage(rec, state)
    _process_record_timing(rec, in_toks, out_toks, cache_read, state)

    assert state.total_requests == 1
    assert state.cache_hits == 1
    assert state.tool_calls_pruned == 4
    assert state.chars_saved == 800
    assert state.total_input_tokens == 500
    assert state.total_output_tokens == 100

    summary = _compute_metrics_summary(state)
    assert summary["tokens_reduced"] == 200
    assert summary["avg_ttft_ms"] == 100.0
