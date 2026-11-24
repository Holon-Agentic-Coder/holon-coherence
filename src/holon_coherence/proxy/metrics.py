from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from holon_coherence.metrics_math import average

__all__ = ["CumulativeMetrics"]

CHARS_PER_ESTIMATED_TOKEN = 4
MILLISECONDS_PER_SECOND = 1000.0
RATE_ROUND_DIGITS = 4
METRIC_ROUND_DIGITS = 2


@dataclass
class CumulativeMetrics:
    total_turns: int = 0
    total_requests: int = 0
    cache_hits: int = 0
    tool_calls_pruned: int = 0
    tokens_reduced: int = 0
    chars_saved: int = 0
    turns_summarized: int = 0
    cache_control_injected: int = 0
    sum_ttft_ms: float = 0.0
    count_ttft: int = 0
    sum_decode_throughput_tps: float = 0.0
    count_decode: int = 0
    sum_prefill_throughput_tps: float = 0.0
    count_prefill: int = 0
    latest_prefill_tps: float = 0.0
    sum_tail_prefill_throughput_tps: float = 0.0
    count_tail_prefill: int = 0
    latest_tail_prefill_tps: float = 0.0
    latest_decode_tps: float = 0.0
    latest_ttft_ms: float = 0.0
    latest_total_time_ms: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_creation_tokens: int = 0
    total_reasoning_tokens: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record_request(self) -> None:
        with self._lock:
            self.total_requests += 1

    def record_cleaner(self, clean_res: Any) -> None:
        if clean_res is None:
            return
        with self._lock:
            self.tool_calls_pruned += getattr(clean_res, "tool_outputs_omitted", 0)
            chars = getattr(clean_res, "chars_saved", 0)
            self.chars_saved += chars
            self.tokens_reduced += chars // CHARS_PER_ESTIMATED_TOKEN
            self.turns_summarized += getattr(clean_res, "turns_summarized", 0)
            self.cache_control_injected += getattr(clean_res, "cache_control_injected", 0)

    def record_cache_hit(self) -> None:
        with self._lock:
            self.cache_hits += 1
            self.total_turns += 1

    def record_response(  # noqa: PLR0913
        self,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
        reasoning_tokens: int = 0,
        ttft: float | None = None,
        output_tps: float | None = None,
        prefill_tps: float | None = None,
        tail_prefill_tps: float | None = None,
        total_time: float | None = None,
    ) -> None:
        with self._lock:
            self.total_turns += 1
            self.total_input_tokens += input_tokens
            self.total_output_tokens += output_tokens
            self.total_cache_read_tokens += cache_read_tokens
            self.total_cache_creation_tokens += cache_creation_tokens
            self.total_reasoning_tokens += reasoning_tokens
            if ttft is not None and ttft > 0:
                self.sum_ttft_ms += ttft * MILLISECONDS_PER_SECOND
                self.count_ttft += 1
            if ttft is not None and ttft > 0:
                self.latest_ttft_ms = ttft * MILLISECONDS_PER_SECOND
            if total_time is not None and total_time > 0:
                self.latest_total_time_ms = total_time * MILLISECONDS_PER_SECOND
            if output_tps is not None and output_tps > 0:
                self.sum_decode_throughput_tps += output_tps
                self.count_decode += 1
                self.latest_decode_tps = output_tps
            if prefill_tps is not None and prefill_tps > 0:
                self.sum_prefill_throughput_tps += prefill_tps
                self.count_prefill += 1
                self.latest_prefill_tps = prefill_tps
            if tail_prefill_tps is not None and tail_prefill_tps > 0:
                self.sum_tail_prefill_throughput_tps += tail_prefill_tps
                self.count_tail_prefill += 1
                self.latest_tail_prefill_tps = tail_prefill_tps

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            hit_rate = (self.cache_hits / self.total_requests) if self.total_requests > 0 else 0.0
            provider_cache_hit_rate = (
                (self.total_cache_read_tokens / self.total_input_tokens) if self.total_input_tokens > 0 else 0.0
            )
            avg_ttft = average(self.sum_ttft_ms, self.count_ttft)
            avg_tps = average(self.sum_decode_throughput_tps, self.count_decode)
            avg_prefill = average(self.sum_prefill_throughput_tps, self.count_prefill)
            avg_tail_prefill = average(self.sum_tail_prefill_throughput_tps, self.count_tail_prefill)
            count_decode_samples = self.count_decode
            return {
                "total_turns": self.total_turns,
                "total_requests": self.total_requests,
                "cache_hits": self.cache_hits,
                "cache_misses": max(0, self.total_requests - self.cache_hits),
                "cache_hit_rate": round(hit_rate, RATE_ROUND_DIGITS),
                "provider_cache_hit_rate": round(provider_cache_hit_rate, RATE_ROUND_DIGITS),
                "tool_calls_pruned": self.tool_calls_pruned,
                "tokens_reduced": self.tokens_reduced,
                "chars_saved": self.chars_saved,
                "turns_summarized": self.turns_summarized,
                "cache_control_injected": self.cache_control_injected,
                "avg_ttft_ms": round(avg_ttft, METRIC_ROUND_DIGITS),
                "avg_decode_throughput_tps": round(avg_tps, METRIC_ROUND_DIGITS),
                "latest_decode_throughput_tps": round(self.latest_decode_tps, METRIC_ROUND_DIGITS),
                "decode_samples": count_decode_samples,
                "avg_prefill_throughput_tps": round(avg_prefill, METRIC_ROUND_DIGITS),
                "latest_prefill_tps": round(self.latest_prefill_tps, METRIC_ROUND_DIGITS),
                "latest_prefill_throughput_tps": round(self.latest_prefill_tps, METRIC_ROUND_DIGITS),
                "avg_tail_prefill_tps": round(avg_tail_prefill, METRIC_ROUND_DIGITS),
                "avg_tail_prefill_throughput_tps": round(avg_tail_prefill, METRIC_ROUND_DIGITS),
                "latest_tail_prefill_tps": round(self.latest_tail_prefill_tps, METRIC_ROUND_DIGITS),
                "latest_tail_prefill_throughput_tps": round(self.latest_tail_prefill_tps, METRIC_ROUND_DIGITS),
                "avg_prompt_prefill_speed_tps": round(avg_prefill, METRIC_ROUND_DIGITS),
                "avg_tail_prefill_speed_tps": round(avg_tail_prefill, METRIC_ROUND_DIGITS),
                "latest_ttft_ms": round(self.latest_ttft_ms, METRIC_ROUND_DIGITS),
                "latest_total_time_ms": round(self.latest_total_time_ms, METRIC_ROUND_DIGITS),
                "total_input_tokens": self.total_input_tokens,
                "total_output_tokens": self.total_output_tokens,
                "total_cache_read_tokens": self.total_cache_read_tokens,
                "total_cache_creation_tokens": self.total_cache_creation_tokens,
                "total_reasoning_tokens": self.total_reasoning_tokens,
            }
