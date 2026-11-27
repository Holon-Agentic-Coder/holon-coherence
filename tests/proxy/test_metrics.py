from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from holon_coherence.metrics.aggregation import (
    OfflineMetricsAccumulator,
    _compute_metrics_summary,
    _process_record_cache_and_deltas,
    _process_record_timing,
    _process_record_usage,
)
from holon_coherence.proxy.metrics import CumulativeMetrics

SHARED_SUMMARY_KEYS = (
    "total_turns",
    "total_requests",
    "cache_hits",
    "cache_misses",
    "cache_hit_rate",
    "provider_cache_hit_rate",
    "tool_calls_pruned",
    "tokens_reduced",
    "chars_saved",
    "turns_summarized",
    "cache_control_injected",
    "avg_ttft_ms",
    "avg_decode_throughput_tps",
    "latest_decode_throughput_tps",
    "decode_samples",
    "avg_prefill_throughput_tps",
    "latest_prefill_tps",
    "avg_tail_prefill_tps",
    "latest_tail_prefill_tps",
    "latest_ttft_ms",
    "latest_total_time_ms",
    "total_input_tokens",
    "total_output_tokens",
    "total_cache_read_tokens",
    "total_cache_creation_tokens",
    "total_reasoning_tokens",
)


def test_cumulative_metrics_initial_state() -> None:
    metrics = CumulativeMetrics()
    data = metrics.to_dict()
    assert data["total_turns"] == 0
    assert data["total_requests"] == 0
    assert data["cache_hits"] == 0
    assert data["cache_misses"] == 0
    assert data["cache_hit_rate"] == 0.0


def test_cumulative_metrics_record_flow() -> None:
    metrics = CumulativeMetrics()
    metrics.record_request()
    metrics.record_request()
    assert metrics.total_requests == 2

    clean_mock = MagicMock()
    clean_mock.tool_outputs_omitted = 3
    clean_mock.chars_saved = 400
    clean_mock.turns_summarized = 1
    clean_mock.cache_control_injected = 2
    metrics.record_cleaner(clean_mock)

    assert metrics.tool_calls_pruned == 3
    assert metrics.chars_saved == 400
    assert metrics.tokens_reduced == 100
    assert metrics.turns_summarized == 1
    assert metrics.cache_control_injected == 2

    metrics.record_cache_hit()
    assert metrics.cache_hits == 1
    assert metrics.total_turns == 1

    metrics.record_response(
        input_tokens=1000,
        output_tokens=200,
        cache_read_tokens=400,
        ttft=0.2,
        output_tps=50.0,
        prefill_tps=5000.0,
        tail_prefill_tps=3000.0,
        total_time=1.0,
    )

    data = metrics.to_dict()
    expected_hit_rate_one_of_two = 0.5
    expected_provider_kv_hit_rate = 0.4
    assert data["total_turns"] == 2
    assert data["cache_hit_rate"] == expected_hit_rate_one_of_two
    assert data["provider_cache_hit_rate"] == expected_provider_kv_hit_rate
    assert data["avg_ttft_ms"] == 200.0
    assert data["avg_decode_throughput_tps"] == 50.0
    assert data["avg_prefill_throughput_tps"] == 5000.0


def test_record_response_ignores_non_positive_ttft_and_updates_latest() -> None:
    metrics = CumulativeMetrics()
    metrics.record_response(ttft=0.0, total_time=0.5)
    metrics.record_response(ttft=-0.5, total_time=0.6)
    metrics.record_response(ttft=None, total_time=0.7)
    data = metrics.to_dict()
    assert data["avg_ttft_ms"] == 0.0
    assert data["latest_ttft_ms"] == 0.0
    assert data["latest_total_time_ms"] == 700.0

    metrics.record_response(ttft=0.25)
    metrics.record_response(ttft=0.0)
    metrics.record_response(ttft=0.75)
    updated = metrics.to_dict()
    assert updated["avg_ttft_ms"] == 500.0
    assert updated["latest_ttft_ms"] == 750.0


def test_live_and_offline_metrics_parity_across_identical_turn_stream() -> None:
    records = [
        {
            "turn_id": "t1",
            "cache_action": "HIT",
            "delta": {
                "tool_outputs_omitted": 2,
                "chars_saved": 400,
                "turns_summarized": 1,
                "cache_control_injected": 1,
            },
            "response": {"usage": {}},
            "timing": {},
        },
        {
            "turn_id": "t2",
            "cache_action": "MISS",
            "delta": {
                "tool_outputs_omitted": 1,
                "chars_saved": 200,
                "turns_summarized": 0,
                "cache_control_injected": 2,
            },
            "response": {
                "usage": {
                    "input_tokens": 1200,
                    "output_tokens": 300,
                    "cache_read_input_tokens": 600,
                    "cache_creation_input_tokens": 120,
                    "reasoning_tokens": 80,
                }
            },
            "timing": {
                "ttft_ms": 250.0,
                "total_ms": 1750.0,
                "prefill_tps": 4800.0,
                "tail_prefill_tps": 2400.0,
                "decode_tps": 200.0,
            },
        },
        {
            "turn_id": "t3",
            "cache_action": "MISS",
            "delta": {
                "tool_outputs_omitted": 0,
                "chars_saved": 0,
                "turns_summarized": 0,
                "cache_control_injected": 0,
            },
            "response": {
                "usage": {
                    "input_tokens": 800,
                    "output_tokens": 100,
                    "cache_read_input_tokens": 200,
                    "cache_creation_input_tokens": 0,
                    "reasoning_tokens": 0,
                }
            },
            "timing": {
                "ttft_ms": 500.0,
                "total_ms": 900.0,
                "prefill_tps": 1600.0,
                "tail_prefill_tps": 1200.0,
                "decode_tps": None,
            },
        },
    ]

    live = CumulativeMetrics()
    offline = OfflineMetricsAccumulator()
    for rec in records:
        _process_record_cache_and_deltas(rec, offline)
        in_toks, out_toks, cache_read = _process_record_usage(rec, offline)
        _process_record_timing(rec, in_toks, out_toks, cache_read, offline)

        live.record_request()
        live.record_cleaner(SimpleNamespace(**rec["delta"]))
        if rec["cache_action"] == "HIT":
            live.record_cache_hit()
            continue
        usage = rec["response"]["usage"]
        timing = rec["timing"]
        live.record_response(
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            cache_read_tokens=usage["cache_read_input_tokens"],
            cache_creation_tokens=usage["cache_creation_input_tokens"],
            reasoning_tokens=usage["reasoning_tokens"],
            ttft=timing["ttft_ms"] / 1000.0,
            output_tps=timing["decode_tps"],
            prefill_tps=timing["prefill_tps"],
            tail_prefill_tps=timing["tail_prefill_tps"],
            total_time=timing["total_ms"] / 1000.0,
        )

    live_summary = live.to_dict()
    offline_summary = _compute_metrics_summary(offline)
    for key in SHARED_SUMMARY_KEYS:
        assert live_summary[key] == offline_summary[key]
