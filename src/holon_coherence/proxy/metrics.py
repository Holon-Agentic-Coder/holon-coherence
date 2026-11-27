from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from holon_coherence.metrics_math import (
    CHARS_PER_ESTIMATED_TOKEN,
    MetricsAccumulatorCore,
    TimingSample,
    UsageSample,
)

__all__ = ["CumulativeMetrics"]


@dataclass
class CumulativeMetrics(MetricsAccumulatorCore):
    total_turns: int = 0
    tokens_reduced: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def sum_tail_prefill_throughput_tps(self) -> float:
        return self.sum_tail_prefill_tps

    @sum_tail_prefill_throughput_tps.setter
    def sum_tail_prefill_throughput_tps(self, value: float) -> None:
        self.sum_tail_prefill_tps = value

    def record_request(self) -> None:
        with self._lock:
            self.total_requests += 1

    def record_cleaner(self, clean_res: Any) -> None:
        if clean_res is None:
            return
        with self._lock:
            chars = getattr(clean_res, "chars_saved", 0)
            self.record_cleaner_delta(
                tool_outputs_omitted=getattr(clean_res, "tool_outputs_omitted", 0),
                chars_saved=chars,
                turns_summarized=getattr(clean_res, "turns_summarized", 0),
                cache_control_injected=getattr(clean_res, "cache_control_injected", 0),
            )
            self.tokens_reduced += chars // CHARS_PER_ESTIMATED_TOKEN

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
            self.record_usage(
                UsageSample(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_read_tokens=cache_read_tokens,
                    cache_creation_tokens=cache_creation_tokens,
                    reasoning_tokens=reasoning_tokens,
                )
            )
            self.record_timing(
                TimingSample(
                    ttft_sec=ttft,
                    output_tps=output_tps,
                    prefill_tps=prefill_tps,
                    tail_prefill_tps=tail_prefill_tps,
                    total_sec=total_time,
                )
            )

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            summary = self.build_summary_dict(total_turns=self.total_turns, tokens_reduced=self.tokens_reduced)
            aliases = {
                "latest_prefill_tps": (("latest_prefill_throughput_tps", summary["latest_prefill_tps"]),),
                "avg_tail_prefill_tps": (("avg_tail_prefill_throughput_tps", summary["avg_tail_prefill_tps"]),),
                "latest_tail_prefill_tps": (
                    ("latest_tail_prefill_throughput_tps", summary["latest_tail_prefill_tps"]),
                    ("avg_prompt_prefill_speed_tps", summary["avg_prefill_throughput_tps"]),
                    ("avg_tail_prefill_speed_tps", summary["avg_tail_prefill_tps"]),
                ),
            }
            result: dict[str, Any] = {}
            for key, value in summary.items():
                result[key] = value
                for alias_key, alias_value in aliases.get(key, ()):
                    result[alias_key] = alias_value
            return result
