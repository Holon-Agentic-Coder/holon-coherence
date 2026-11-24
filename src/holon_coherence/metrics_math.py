from __future__ import annotations

import math
from typing import Any

MIN_STREAMING_WINDOW_SEC = 0.05
UNMEASURED = "unmeasured"
DEFAULT_WIRE_LOG_DIR = ".holon/mitm_wire_logs"


def _is_finite_positive_number(seconds: float) -> bool:
    return math.isfinite(seconds) and seconds > 0.0


def positive_seconds(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if _is_finite_positive_number(seconds) else None


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
    tokens = to_int(uncached_input_tokens)
    ttft = positive_seconds(ttft_sec)
    if tokens <= 0 or ttft is None:
        return None
    return tokens / ttft


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


def format_rate(value: float | None, precision: int = 2) -> str:
    if value is None:
        return UNMEASURED
    return f"{value:.{precision}f}"
