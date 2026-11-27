from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from holon_coherence.metrics_math import (
    MILLISECONDS_PER_SECOND,
    MetricsAccumulator,
    TokenUsage,
    compute_decode_tps,
    compute_prefill_tps,
    compute_tail_prefill_tps,
    positive_rate,
    positive_seconds,
)

WIRE_LOG_FILENAME = "transactions.jsonl"


@dataclass
class OfflineMetricsAccumulator(MetricsAccumulator):
    seen_turn_ids: set[str | int] = field(default_factory=set)


def _milliseconds_to_seconds(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value) / MILLISECONDS_PER_SECOND
    except (TypeError, ValueError):
        return None


def _stored_rate(stored: Any, derived: float | None) -> float | None:
    if stored is not None and not isinstance(stored, bool):
        return positive_rate(stored)
    return derived


def _process_record_cache_and_deltas(record: dict[str, Any], state: OfflineMetricsAccumulator) -> None:
    state.total_requests += 1
    turn_id = record.get("turn_id")
    if turn_id is not None:
        state.seen_turn_ids.add(turn_id)

    if record.get("cache_action") == "HIT":
        state.cache_hits += 1

    delta = record.get("delta", {})
    if isinstance(delta, dict):
        state.record_cleaner_deltas(
            tool_outputs_omitted=delta.get("tool_outputs_omitted", 0),
            chars_saved=delta.get("chars_saved", 0),
            turns_summarized=delta.get("turns_summarized", 0),
            cache_control_injected=delta.get("cache_control_injected", 0),
        )


def _process_record_usage(record: dict[str, Any], state: OfflineMetricsAccumulator) -> tuple[int, int, int]:
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

    state.record_usage(
        TokenUsage(
            input_tokens=in_toks,
            output_tokens=out_toks,
            cache_read_tokens=cache_read_toks,
            cache_creation_tokens=cache_create_toks,
            reasoning_tokens=reason_toks,
        )
    )

    return in_toks, out_toks, cache_read_toks


def _process_record_timing(
    record: dict[str, Any],
    in_toks: int,
    out_toks: int,
    cache_read_toks: int,
    state: OfflineMetricsAccumulator,
) -> None:
    timing = record.get("timing", {})
    if not isinstance(timing, dict):
        timing = {}

    ttft_sec = positive_seconds(_milliseconds_to_seconds(timing.get("ttft_ms")))
    total_sec = positive_seconds(_milliseconds_to_seconds(timing.get("total_ms")))
    prefill_tps = _stored_rate(timing.get("prefill_tps"), compute_prefill_tps(in_toks, ttft_sec))
    uncached_in = max(0, in_toks - cache_read_toks)
    tail_p_tps = _stored_rate(timing.get("tail_prefill_tps"), compute_tail_prefill_tps(uncached_in, ttft_sec))

    if "decode_tps" in timing:
        decode_tps = positive_rate(timing.get("decode_tps"))
    else:
        legacy_window = (
            positive_seconds(total_sec - ttft_sec) if total_sec is not None and ttft_sec is not None else None
        )
        decode_tps = compute_decode_tps(out_toks, legacy_window, streaming=True)

    state.record_latency_seconds(ttft_sec=ttft_sec, total_sec=total_sec)
    state.record_throughput(decode_tps=decode_tps, prefill_tps=prefill_tps, tail_prefill_tps=tail_p_tps)


def _compute_metrics_summary(state: OfflineMetricsAccumulator) -> dict[str, Any]:
    summary = state.core_summary(total_turns=len(state.seen_turn_ids) or state.total_requests)
    summary["source"] = "offline_wire_log"
    return summary


def read_offline_metrics(wire_log_dir: str) -> dict[str, Any] | None:
    jsonl_path = os.path.join(wire_log_dir, WIRE_LOG_FILENAME)
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
