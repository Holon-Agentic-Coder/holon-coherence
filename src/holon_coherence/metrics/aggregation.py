"""Offline wire-log metrics aggregation and cumulative statistical calculation."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from holon_coherence.metrics_math import (
    average,
    compute_decode_tps,
    compute_prefill_tps,
    compute_tail_prefill_tps,
    positive_rate,
    positive_seconds,
)


@dataclass
class OfflineMetricsAccumulator:
    """Container holding accumulated metric counters and rates across wire-log records."""

    total_requests: int = 0
    cache_hits: int = 0
    tool_calls_pruned: int = 0
    chars_saved: int = 0
    turns_summarized: int = 0
    cache_control_injected: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_creation_tokens: int = 0
    total_reasoning_tokens: int = 0
    sum_ttft_ms: float = 0.0
    count_ttft: int = 0
    sum_decode_throughput_tps: float = 0.0
    count_decode: int = 0
    sum_prefill_throughput_tps: float = 0.0
    count_prefill: int = 0
    latest_prefill_tps: float = 0.0
    sum_tail_prefill_tps: float = 0.0
    count_tail_prefill: int = 0
    latest_tail_prefill_tps: float = 0.0
    latest_decode_tps: float = 0.0
    latest_ttft_ms: float = 0.0
    latest_total_time_ms: float = 0.0
    seen_turn_ids: set[str | int] = field(default_factory=set)


def _milliseconds_to_seconds(value: Any) -> float | None:
    """Convert a wire-log millisecond reading to seconds, passing ``None`` through untouched."""
    if value is None:
        return None
    try:
        return float(value) / 1000.0
    except (TypeError, ValueError):
        return None


def _stored_rate(stored: Any, derived: float | None) -> float | None:
    """Resolve a wire-log rate against the same rate re-derived from raw timings.

    A stored positive number wins. A stored ``0.0`` (or any other unusable number) is *unmeasured*
    under this project's rate contract, so it stays unmeasured instead of being silently replaced by
    a re-derivation. A missing or ``null`` value means the writer had no rate to store, so the
    derived value is used -- which is what lets legacy records still report prefill speed.
    """
    if stored is not None and not isinstance(stored, bool):
        return positive_rate(stored)
    return derived


def _process_record_cache_and_deltas(record: dict[str, Any], state: OfflineMetricsAccumulator) -> None:
    """Extract turn ID, cache status, and delta savings from record."""
    state.total_requests += 1
    turn_id = record.get("turn_id")
    if turn_id is not None:
        state.seen_turn_ids.add(turn_id)

    if record.get("cache_action") == "HIT":
        state.cache_hits += 1

    delta = record.get("delta", {})
    if isinstance(delta, dict):
        state.tool_calls_pruned += delta.get("tool_outputs_omitted", 0)
        state.chars_saved += delta.get("chars_saved", 0)
        state.turns_summarized += delta.get("turns_summarized", 0)
        state.cache_control_injected += delta.get("cache_control_injected", 0)


def _process_record_usage(record: dict[str, Any], state: OfflineMetricsAccumulator) -> tuple[int, int, int]:
    """Safely extract token usage counters and accumulate into state."""
    resp = record.get("response", {})
    if not isinstance(resp, dict):
        return 0, 0, 0
    usage = resp.get("usage", {})
    if not isinstance(usage, dict):
        return 0, 0, 0

    in_toks = usage.get("input_tokens") or 0
    out_toks = usage.get("output_tokens") or 0
    cache_read_toks = usage.get("cache_read_input_tokens") or 0
    cache_create_toks = usage.get("cache_creation_input_tokens") or 0
    reason_toks = usage.get("reasoning_tokens") or usage.get("thinking_tokens") or 0

    state.total_input_tokens += in_toks
    state.total_output_tokens += out_toks
    state.total_cache_read_tokens += cache_read_toks
    state.total_cache_creation_tokens += cache_create_toks
    state.total_reasoning_tokens += reason_toks

    return in_toks, out_toks, cache_read_toks


def _process_record_timing(
    record: dict[str, Any],
    in_toks: int,
    out_toks: int,
    cache_read_toks: int,
    state: OfflineMetricsAccumulator,
) -> None:
    """Extract and accumulate TTFT, prefill, and decode timings from record."""
    timing = record.get("timing", {})
    if not isinstance(timing, dict):
        timing = {}

    ttft_sec = positive_seconds(_milliseconds_to_seconds(timing.get("ttft_ms")))
    total_sec = positive_seconds(_milliseconds_to_seconds(timing.get("total_ms")))
    if ttft_sec is not None:
        state.sum_ttft_ms += ttft_sec * 1000.0
        state.count_ttft += 1
        state.latest_ttft_ms = ttft_sec * 1000.0
    if total_sec is not None:
        state.latest_total_time_ms = total_sec * 1000.0

    prefill_tps = _stored_rate(timing.get("prefill_tps"), compute_prefill_tps(in_toks, ttft_sec))
    if prefill_tps is not None:
        state.sum_prefill_throughput_tps += prefill_tps
        state.count_prefill += 1
        state.latest_prefill_tps = prefill_tps

    uncached_in = max(0, in_toks - cache_read_toks)
    tail_p_tps = _stored_rate(timing.get("tail_prefill_tps"), compute_tail_prefill_tps(uncached_in, ttft_sec))
    if tail_p_tps is not None:
        state.sum_tail_prefill_tps += tail_p_tps
        state.count_tail_prefill += 1
        state.latest_tail_prefill_tps = tail_p_tps

    if "decode_tps" in timing:
        decode_tps = positive_rate(timing.get("decode_tps"))
    else:
        legacy_window = (
            positive_seconds(total_sec - ttft_sec) if total_sec is not None and ttft_sec is not None else None
        )
        decode_tps = compute_decode_tps(out_toks, legacy_window, streaming=True)
    if decode_tps is not None:
        state.sum_decode_throughput_tps += decode_tps
        state.count_decode += 1
        state.latest_decode_tps = decode_tps


def _compute_metrics_summary(state: OfflineMetricsAccumulator) -> dict[str, Any]:
    """Calculate derived summary statistics and return dictionary payload."""
    total_requests = state.total_requests
    cache_hit_rate = (state.cache_hits / total_requests) if total_requests > 0 else 0.0
    provider_cache_hit_rate = (
        (state.total_cache_read_tokens / state.total_input_tokens) if state.total_input_tokens > 0 else 0.0
    )
    avg_ttft_ms = average(state.sum_ttft_ms, state.count_ttft)
    avg_decode_throughput_tps = average(state.sum_decode_throughput_tps, state.count_decode)
    avg_prefill_throughput_tps = average(state.sum_prefill_throughput_tps, state.count_prefill)
    avg_tail_prefill_tps = average(state.sum_tail_prefill_tps, state.count_tail_prefill)
    tokens_reduced = state.chars_saved // 4

    return {
        "total_turns": len(state.seen_turn_ids) or total_requests,
        "total_requests": total_requests,
        "cache_hits": state.cache_hits,
        "cache_misses": max(0, total_requests - state.cache_hits),
        "cache_hit_rate": round(cache_hit_rate, 4),
        "provider_cache_hit_rate": round(provider_cache_hit_rate, 4),
        "tool_calls_pruned": state.tool_calls_pruned,
        "tokens_reduced": tokens_reduced,
        "chars_saved": state.chars_saved,
        "turns_summarized": state.turns_summarized,
        "cache_control_injected": state.cache_control_injected,
        "avg_ttft_ms": round(avg_ttft_ms, 2),
        "avg_decode_throughput_tps": round(avg_decode_throughput_tps, 2),
        "latest_decode_throughput_tps": round(state.latest_decode_tps, 2),
        "decode_samples": state.count_decode,
        "avg_prefill_throughput_tps": round(avg_prefill_throughput_tps, 2),
        "latest_prefill_tps": round(state.latest_prefill_tps, 2),
        "avg_tail_prefill_tps": round(avg_tail_prefill_tps, 2),
        "latest_tail_prefill_tps": round(state.latest_tail_prefill_tps, 2),
        "latest_ttft_ms": round(state.latest_ttft_ms, 2),
        "latest_total_time_ms": round(state.latest_total_time_ms, 2),
        "total_input_tokens": state.total_input_tokens,
        "total_output_tokens": state.total_output_tokens,
        "total_cache_read_tokens": state.total_cache_read_tokens,
        "total_cache_creation_tokens": state.total_cache_creation_tokens,
        "total_reasoning_tokens": state.total_reasoning_tokens,
        "source": "offline_wire_log",
    }


def read_offline_metrics(wire_log_dir: str) -> dict[str, Any] | None:
    """Calculates cumulative metrics from persisted transactions.jsonl when proxy is offline."""
    jsonl_path = os.path.join(wire_log_dir, "transactions.jsonl")
    if not os.path.exists(jsonl_path):
        return None

    state = OfflineMetricsAccumulator()
    try:
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except Exception:
                    continue
                if not isinstance(record, dict):
                    continue
                _process_record_cache_and_deltas(record, state)
                in_toks, out_toks, cache_read_toks = _process_record_usage(record, state)
                _process_record_timing(record, in_toks, out_toks, cache_read_toks, state)
    except Exception:
        return None

    if state.total_requests == 0:
        return None

    return _compute_metrics_summary(state)
