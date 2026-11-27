from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

MIN_STREAMING_WINDOW_SEC = 0.05
UNMEASURED = "unmeasured"
DEFAULT_WIRE_LOG_DIR = ".holon/mitm_wire_logs"
CHARS_PER_ESTIMATED_TOKEN = 4
MILLISECONDS_PER_SECOND = 1000.0
RATE_ROUND_DIGITS = 4
METRIC_ROUND_DIGITS = 2


def positive_seconds(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if (math.isfinite(seconds) and seconds > 0.0) else None


def to_int(value: Any) -> int:
    if value is None or isinstance(value, bool):
        return 0
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def compute_prefill_tps(input_tokens: Any, ttft_sec: Any) -> float | None:
    tokens = to_int(input_tokens)
    ttft = positive_seconds(ttft_sec)
    return (tokens / ttft) if (tokens > 0 and ttft is not None) else None


compute_prefill_throughput = compute_prompt_prefill_speed = compute_prefill_tps
compute_tail_prefill_tps = compute_tail_prefill_throughput = compute_tail_prefill_speed = compute_prefill_tps


def compute_decode_tps(output_tokens: Any, generation_sec: Any, streaming: bool = False) -> float | None:
    tokens = to_int(output_tokens) if streaming else 0
    window = positive_seconds(generation_sec)
    if tokens <= 0 or window is None or window < MIN_STREAMING_WINDOW_SEC:
        return None
    return tokens / window


compute_decode_throughput = compute_decode_speed = compute_decode_tps
positive_rate = positive_seconds


def average(total: float, count: int) -> float:
    return (float(total) / count) if count > 0 else 0.0


def ratio(numerator: float, denominator: float) -> float:
    return (float(numerator) / denominator) if denominator > 0 else 0.0


def format_rate(value: float | None, precision: int = 2) -> str:
    return UNMEASURED if value is None else f"{value:.{precision}f}"


def _accumulate_rate(value: float | None, total: float, count: int, latest: float) -> tuple[float, int, float]:
    rate = positive_seconds(value)
    return (total + rate, count + 1, rate) if rate is not None else (total, count, latest)


@dataclass(frozen=True)
class UsageSample:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    reasoning_tokens: int = 0


@dataclass(frozen=True)
class TimingSample:
    ttft_sec: float | None = None
    output_tps: float | None = None
    prefill_tps: float | None = None
    tail_prefill_tps: float | None = None
    total_sec: float | None = None


@dataclass
class MetricsAccumulatorCore:
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

    def record_cleaner_delta(
        self,
        tool_outputs_omitted: int = 0,
        chars_saved: int = 0,
        turns_summarized: int = 0,
        cache_control_injected: int = 0,
    ) -> None:
        self.tool_calls_pruned += tool_outputs_omitted
        self.chars_saved += chars_saved
        self.turns_summarized += turns_summarized
        self.cache_control_injected += cache_control_injected

    def record_usage(self, usage: UsageSample) -> None:
        self.total_input_tokens += usage.input_tokens
        self.total_output_tokens += usage.output_tokens
        self.total_cache_read_tokens += usage.cache_read_tokens
        self.total_cache_creation_tokens += usage.cache_creation_tokens
        self.total_reasoning_tokens += usage.reasoning_tokens

    def record_timing(self, timing: TimingSample) -> None:
        ttft_sec = positive_seconds(timing.ttft_sec)
        ttft_ms = ttft_sec * MILLISECONDS_PER_SECOND if ttft_sec is not None else None
        self.sum_ttft_ms, self.count_ttft, self.latest_ttft_ms = _accumulate_rate(
            ttft_ms, self.sum_ttft_ms, self.count_ttft, self.latest_ttft_ms
        )
        total_sec = positive_seconds(timing.total_sec)
        if total_sec is not None:
            self.latest_total_time_ms = total_sec * MILLISECONDS_PER_SECOND
        self.sum_decode_throughput_tps, self.count_decode, self.latest_decode_tps = _accumulate_rate(
            timing.output_tps, self.sum_decode_throughput_tps, self.count_decode, self.latest_decode_tps
        )
        self.sum_prefill_throughput_tps, self.count_prefill, self.latest_prefill_tps = _accumulate_rate(
            timing.prefill_tps, self.sum_prefill_throughput_tps, self.count_prefill, self.latest_prefill_tps
        )
        self.sum_tail_prefill_tps, self.count_tail_prefill, self.latest_tail_prefill_tps = _accumulate_rate(
            timing.tail_prefill_tps, self.sum_tail_prefill_tps, self.count_tail_prefill, self.latest_tail_prefill_tps
        )

    def build_summary_dict(self, total_turns: int, tokens_reduced: int | None = None) -> dict[str, Any]:
        avg_ttft = average(self.sum_ttft_ms, self.count_ttft)
        avg_decode = average(self.sum_decode_throughput_tps, self.count_decode)
        avg_prefill = average(self.sum_prefill_throughput_tps, self.count_prefill)
        avg_tail = average(self.sum_tail_prefill_tps, self.count_tail_prefill)
        provider_hit_rate = ratio(self.total_cache_read_tokens, self.total_input_tokens)
        reduced = self.chars_saved // CHARS_PER_ESTIMATED_TOKEN if tokens_reduced is None else tokens_reduced
        return {
            "total_turns": total_turns,
            "total_requests": self.total_requests,
            "cache_hits": self.cache_hits,
            "cache_misses": max(0, self.total_requests - self.cache_hits),
            "cache_hit_rate": round(ratio(self.cache_hits, self.total_requests), RATE_ROUND_DIGITS),
            "provider_cache_hit_rate": round(provider_hit_rate, RATE_ROUND_DIGITS),
            "tool_calls_pruned": self.tool_calls_pruned,
            "tokens_reduced": reduced,
            "chars_saved": self.chars_saved,
            "turns_summarized": self.turns_summarized,
            "cache_control_injected": self.cache_control_injected,
            "avg_ttft_ms": round(avg_ttft, METRIC_ROUND_DIGITS),
            "avg_decode_throughput_tps": round(avg_decode, METRIC_ROUND_DIGITS),
            "latest_decode_throughput_tps": round(self.latest_decode_tps, METRIC_ROUND_DIGITS),
            "decode_samples": self.count_decode,
            "avg_prefill_throughput_tps": round(avg_prefill, METRIC_ROUND_DIGITS),
            "latest_prefill_tps": round(self.latest_prefill_tps, METRIC_ROUND_DIGITS),
            "avg_tail_prefill_tps": round(avg_tail, METRIC_ROUND_DIGITS),
            "latest_tail_prefill_tps": round(self.latest_tail_prefill_tps, METRIC_ROUND_DIGITS),
            "latest_ttft_ms": round(self.latest_ttft_ms, METRIC_ROUND_DIGITS),
            "latest_total_time_ms": round(self.latest_total_time_ms, METRIC_ROUND_DIGITS),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cache_read_tokens": self.total_cache_read_tokens,
            "total_cache_creation_tokens": self.total_cache_creation_tokens,
            "total_reasoning_tokens": self.total_reasoning_tokens,
        }
