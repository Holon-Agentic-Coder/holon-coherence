"""Unit tests for CumulativeMetrics tracking and aggregation."""

from __future__ import annotations

from unittest.mock import MagicMock

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

    # Cleaner record
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

    # Cache hit
    metrics.record_cache_hit()
    assert metrics.cache_hits == 1
    assert metrics.total_turns == 1

    # Response record
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
    assert data["total_turns"] == 2
    assert data["cache_hit_rate"] == 0.5  # 1 hit / 2 requests
    assert data["provider_cache_hit_rate"] == 0.4  # 400 / 1000
    assert data["avg_ttft_ms"] == 200.0
    assert data["avg_decode_throughput_tps"] == 50.0
    assert data["avg_prefill_throughput_tps"] == 5000.0
