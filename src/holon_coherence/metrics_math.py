from __future__ import annotations

import math
from dataclasses import dataclass, field
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
    return seconds if math.isfinite(seconds) and seconds > 0.0 else None


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
    if tokens <= 0 or ttft is None:
        return None
    return tokens / ttft


compute_prefill_throughput = compute_prefill_tps
compute_prompt_prefill_speed = compute_prefill_tps


def compute_tail_prefill_tps(uncached_input_tokens: Any, ttft_sec: Any) -> float | None:
    return compute_prefill_tps(uncached_input_tokens, ttft_sec)


compute_tail_prefill_throughput = compute_tail_prefill_tps
compute_tail_prefill_speed = compute_tail_prefill_tps


def compute_decode_tps(output_tokens: Any, generation_sec: Any, streaming: bool = False) -> float | None:
    if not streaming:
        return None
    tokens = to_int(output_tokens)
    window = positive_seconds(generation_sec)
    if tokens <= 0 or window is None or window < MIN_STREAMING_WINDOW_SEC:
        return None
    return tokens / window


compute_decode_throughput = compute_decode_tps
compute_decode_speed = compute_decode_tps


def positive_rate(value: Any) -> float | None:
    return positive_seconds(value)


def average(total: float, count: int) -> float:
    return (float(total) / count) if count > 0 else 0.0


def ratio(numerator: float, denominator: float) -> float:
    return (float(numerator) / denominator) if denominator > 0 else 0.0


def format_rate(value: float | None, precision: int = 2) -> str:
    return UNMEASURED if value is None else f"{value:.{precision}f}"


@dataclass
class SampleAccumulator:
    total: float = 0.0
    count: int = 0
    latest: float = 0.0

    def record(self, value: float | None) -> None:
        if value is not None and value > 0:
            self.total += value
            self.count += 1
            self.latest = value

    def average(self) -> float:
        return average(self.total, self.count)


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    reasoning_tokens: int = 0


@dataclass
class MetricsAccumulator:
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
    ttft_ms: SampleAccumulator = field(default_factory=SampleAccumulator)
    decode_tps: SampleAccumulator = field(default_factory=SampleAccumulator)
    prefill_tps: SampleAccumulator = field(default_factory=SampleAccumulator)
    tail_prefill_tps: SampleAccumulator = field(default_factory=SampleAccumulator)
    latest_total_time_ms: float = 0.0

    def record_cleaner_deltas(
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

    def record_usage(self, usage: TokenUsage) -> None:
        self.total_input_tokens += usage.input_tokens
        self.total_output_tokens += usage.output_tokens
        self.total_cache_read_tokens += usage.cache_read_tokens
        self.total_cache_creation_tokens += usage.cache_creation_tokens
        self.total_reasoning_tokens += usage.reasoning_tokens

    def record_latency_seconds(self, ttft_sec: float | None = None, total_sec: float | None = None) -> None:
        if ttft_sec is not None and ttft_sec > 0:
            self.ttft_ms.record(ttft_sec * MILLISECONDS_PER_SECOND)
        if total_sec is not None and total_sec > 0:
            self.latest_total_time_ms = total_sec * MILLISECONDS_PER_SECOND

    def record_throughput(
        self,
        decode_tps: float | None = None,
        prefill_tps: float | None = None,
        tail_prefill_tps: float | None = None,
    ) -> None:
        self.decode_tps.record(decode_tps)
        self.prefill_tps.record(prefill_tps)
        self.tail_prefill_tps.record(tail_prefill_tps)

    def core_summary(self, total_turns: int, tokens_reduced: int | None = None) -> dict[str, Any]:
        reduced = self.chars_saved // CHARS_PER_ESTIMATED_TOKEN if tokens_reduced is None else tokens_reduced
        provider_hit_rate = ratio(self.total_cache_read_tokens, self.total_input_tokens)
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
            "avg_ttft_ms": round(self.ttft_ms.average(), METRIC_ROUND_DIGITS),
            "avg_decode_throughput_tps": round(self.decode_tps.average(), METRIC_ROUND_DIGITS),
            "latest_decode_throughput_tps": round(self.decode_tps.latest, METRIC_ROUND_DIGITS),
            "decode_samples": self.decode_tps.count,
            "avg_prefill_throughput_tps": round(self.prefill_tps.average(), METRIC_ROUND_DIGITS),
            "latest_prefill_tps": round(self.prefill_tps.latest, METRIC_ROUND_DIGITS),
            "avg_tail_prefill_tps": round(self.tail_prefill_tps.average(), METRIC_ROUND_DIGITS),
            "latest_tail_prefill_tps": round(self.tail_prefill_tps.latest, METRIC_ROUND_DIGITS),
            "latest_ttft_ms": round(self.ttft_ms.latest, METRIC_ROUND_DIGITS),
            "latest_total_time_ms": round(self.latest_total_time_ms, METRIC_ROUND_DIGITS),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cache_read_tokens": self.total_cache_read_tokens,
            "total_cache_creation_tokens": self.total_cache_creation_tokens,
            "total_reasoning_tokens": self.total_reasoning_tokens,
        }
