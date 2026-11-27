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


def test_cumulative_metrics_ttft_guard_consistency() -> None:
    metrics = CumulativeMetrics()
    metrics.record_response(ttft=0.25)
    assert metrics.count_ttft == 1
    assert metrics.sum_ttft_ms == 250.0
    assert metrics.latest_ttft_ms == 250.0

    for invalid_ttft in (0.0, -0.1, None, float("nan")):
        metrics.record_response(ttft=invalid_ttft)

    assert metrics.count_ttft == 1
    assert metrics.sum_ttft_ms == 250.0
    assert metrics.latest_ttft_ms == 250.0

    metrics.record_response(ttft=0.5)
    assert metrics.count_ttft == 2
    assert metrics.sum_ttft_ms == 750.0
    assert metrics.latest_ttft_ms == 500.0
    assert metrics.to_dict()["avg_ttft_ms"] == 375.0


def test_live_and_offline_metrics_parity_across_turn_stream() -> None:
    records = [
        {"turn_id": "turn-1", "cache_action": "HIT"},
        {
            "turn_id": "turn-2",
            "cache_action": "MISS",
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
            "turn_id": "turn-3",
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
                "prefill_tps": 3000.0,
                "tail_prefill_tps": 3000.0,
                "decode_tps": None,
            },
        },
        {
            "turn_id": "turn-4",
            "cache_action": "MISS",
            "timing": {
                "ttft_ms": 0.0,
                "total_ms": -1.0,
                "prefill_tps": 0.0,
                "tail_prefill_tps": -5.0,
                "decode_tps": None,
            },
        },
    ]

    offline_state = OfflineMetricsAccumulator()
    live_metrics = CumulativeMetrics()
    for record in records:
        _process_record_cache_and_deltas(record, offline_state)
        in_toks, out_toks, cache_read = _process_record_usage(record, offline_state)
        _process_record_timing(record, in_toks, out_toks, cache_read, offline_state)

        live_metrics.record_request()
        if record.get("cache_action") == "HIT":
            live_metrics.record_cache_hit()
            continue

        delta = record.get("delta")
        if isinstance(delta, dict):
            live_metrics.record_cleaner(SimpleNamespace(**delta))
        usage = record.get("response", {}).get("usage", {})
        timing = record.get("timing", {})
        live_metrics.record_response(
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_read_tokens=usage.get("cache_read_input_tokens", 0),
            cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
            reasoning_tokens=usage.get("reasoning_tokens", 0),
            ttft=(timing["ttft_ms"] / 1000.0) if timing.get("ttft_ms") is not None else None,
            output_tps=timing.get("decode_tps"),
            prefill_tps=timing.get("prefill_tps"),
            tail_prefill_tps=timing.get("tail_prefill_tps"),
            total_time=(timing["total_ms"] / 1000.0) if timing.get("total_ms") is not None else None,
        )

    offline_summary = _compute_metrics_summary(offline_state)
    live_summary = live_metrics.to_dict()
    shared_keys = [key for key in offline_summary if key != "source"]
    assert len(shared_keys) == 26
    assert {key: live_summary[key] for key in shared_keys} == {key: offline_summary[key] for key in shared_keys}
