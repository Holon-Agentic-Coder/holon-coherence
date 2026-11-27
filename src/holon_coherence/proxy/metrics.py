from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from holon_coherence.metrics_math import (
    CHARS_PER_ESTIMATED_TOKEN,
    MetricsAccumulator,
    TokenUsage,
)

__all__ = ["CumulativeMetrics"]


@dataclass
class CumulativeMetrics(MetricsAccumulator):
    total_turns: int = 0
    tokens_reduced: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record_request(self) -> None:
        with self._lock:
            self.total_requests += 1

    def record_cleaner(self, clean_res: Any) -> None:
        if clean_res is None:
            return
        with self._lock:
            chars = getattr(clean_res, "chars_saved", 0)
            self.record_cleaner_deltas(
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
                TokenUsage(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_read_tokens=cache_read_tokens,
                    cache_creation_tokens=cache_creation_tokens,
                    reasoning_tokens=reasoning_tokens,
                )
            )
            self.record_latency_seconds(ttft_sec=ttft, total_sec=total_time)
            self.record_throughput(
                decode_tps=output_tps,
                prefill_tps=prefill_tps,
                tail_prefill_tps=tail_prefill_tps,
            )

    @property
    def count_ttft(self) -> int:
        return self.ttft_ms.count

    @property
    def count_decode(self) -> int:
        return self.decode_tps.count

    @property
    def count_prefill(self) -> int:
        return self.prefill_tps.count

    @property
    def count_tail_prefill(self) -> int:
        return self.tail_prefill_tps.count

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            core = self.core_summary(total_turns=self.total_turns, tokens_reduced=self.tokens_reduced)
            summary: dict[str, Any] = {}
            for key, value in core.items():
                summary[key] = value
                if key == "latest_prefill_tps":
                    summary["latest_prefill_throughput_tps"] = value
                elif key == "avg_tail_prefill_tps":
                    summary["avg_tail_prefill_throughput_tps"] = value
                elif key == "latest_tail_prefill_tps":
                    summary["latest_tail_prefill_throughput_tps"] = value
                    summary["avg_prompt_prefill_speed_tps"] = core["avg_prefill_throughput_tps"]
                    summary["avg_tail_prefill_speed_tps"] = core["avg_tail_prefill_tps"]
            return summary
