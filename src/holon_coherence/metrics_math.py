"""Shared telemetry arithmetic for Holon Coherence.

Every surface that reports a token rate -- the live in-memory proxy, the ``/holon/api/metrics`` JSON
contract, the ``/holon/`` dashboard, the ``holon-coherence metrics`` terminal scorecard and the
offline wire-log parser -- funnels through these helpers, so a rate is computed exactly one way and
a rate that cannot be measured stays reported as *unmeasured* instead of collapsing into a
fabricated number.

Two physical facts drive the module:

1. **Prefill speed needs a real TTFT.** ``input_tokens / ttft`` is only meaningful when the proxy
   actually observed the elapsed time between sending the request and seeing the first token (or,
   for a buffered reply, the first payload). A missing timestamp is not a zero: substituting
   ``now`` for a missing request start yields ``ttft == 0`` and prints ``0.00 tokens/sec`` next to
   1.2M prompt tokens, which is the bug this module removes.
2. **Decode speed only exists while tokens are streaming.** For a non-streaming response the
   headers and the whole body land in the same network chunk, so ``total_time - ttft`` collapses to
   socket parse time (~0.001s) and ``output_tokens / that`` prints a physically impossible
   34,000-38,000 tokens/sec that poisons every cumulative average. Decode throughput is therefore
   derived exclusively from the SSE chunk window and is rejected below a realistic floor.
"""

from __future__ import annotations

from typing import Any

# Shortest genuine token-generation window we are willing to trust. Anything faster than this is
# socket/parse latency or a buffered burst, not streaming, and cannot yield a credible tok/s value.
MIN_STREAMING_WINDOW_SEC = 0.05

# Rendered in telemetry headers for rates that were not measurable for this transaction.
UNMEASURED = "unmeasured"

# Wire-log directory shared by the proxy that writes transactions and the offline metrics reader.
DEFAULT_WIRE_LOG_DIR = ".holon/mitm_wire_logs"


def positive_seconds(value: Any) -> float | None:
    """Coerce a timing value to a strictly positive float number of seconds, else ``None``.

    Args:
        value: Candidate duration in seconds (``None``, numeric, or numeric string).

    Returns:
        float | None: The duration when it is a positive number, otherwise ``None`` meaning
        "not measured" -- never ``0.0``, which would silently poison downstream divisions.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if seconds != seconds or seconds in (float("inf"), float("-inf")):  # NaN / inf guards
        return None
    return seconds if seconds > 0.0 else None


def to_int(value: Any) -> int:
    """Coerce a usage counter to a non-negative int, treating anything unusable as ``0``."""
    if value is None or isinstance(value, bool):
        return 0
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def compute_prefill_tps(input_tokens: Any, ttft_sec: Any) -> float | None:
    """Prefill throughput: prompt tokens divided by time-to-first-token.

    Args:
        input_tokens: Prompt tokens charged by the provider (including cached prefix tokens).
        ttft_sec: Measured time-to-first-token in seconds.

    Returns:
        float | None: Tokens/second when both operands are positive, otherwise ``None``.
    """
    tokens = to_int(input_tokens)
    ttft = positive_seconds(ttft_sec)
    if tokens <= 0 or ttft is None:
        return None
    return tokens / ttft


# Backward-compatible and standardized vocabulary aliases
compute_prefill_throughput = compute_prefill_tps
compute_prompt_prefill_speed = compute_prefill_tps


def compute_tail_prefill_tps(uncached_input_tokens: Any, ttft_sec: Any) -> float | None:
    """Tail prefill throughput attributable to *uncached* prompt tokens only (the real prefill work).

    Returns ``None`` when the prompt was served entirely from the provider KV cache, because zero
    uncached tokens processed in positive time is a genuine ``0`` rate that must not be averaged in
    as if the model had re-read the prompt.
    """
    tokens = to_int(uncached_input_tokens)
    ttft = positive_seconds(ttft_sec)
    if tokens <= 0 or ttft is None:
        return None
    return tokens / ttft


# Backward-compatible and standardized vocabulary aliases
compute_tail_prefill_throughput = compute_tail_prefill_tps
compute_tail_prefill_speed = compute_tail_prefill_tps


def compute_decode_tps(output_tokens: Any, generation_sec: Any, streaming: bool = False) -> float | None:
    """Decode throughput, computed only from a genuine streaming window.

    Args:
        output_tokens: Completion tokens reported by the provider.
        generation_sec: First-SSE-chunk to last-SSE-chunk window in seconds.
        streaming: True only when the upstream reply was an SSE stream.

    Returns:
        float | None: Tokens/second for a real streaming window of at least
        :data:`MIN_STREAMING_WINDOW_SEC`; ``None`` for non-streaming replies, missing timings and
        sub-floor windows, all of which measure socket latency rather than generation speed.
    """
    if not streaming:
        return None
    tokens = to_int(output_tokens)
    window = positive_seconds(generation_sec)
    if tokens <= 0 or window is None or window < MIN_STREAMING_WINDOW_SEC:
        return None
    return tokens / window


# Backward-compatible and standardized vocabulary aliases
compute_decode_throughput = compute_decode_tps
compute_decode_speed = compute_decode_tps


def positive_rate(value: Any) -> float | None:
    """Return a stored token rate when it is a positive number, else ``None`` (*not measured*).

    Same numeric contract as :func:`positive_seconds`, named separately so call sites that read
    rates back out of wire-log records stay readable.
    """
    return positive_seconds(value)


def average(total: float, count: int) -> float:
    """Arithmetic mean that reports ``0.0`` while no samples exist."""
    return (float(total) / count) if count > 0 else 0.0


def format_rate(value: float | None, precision: int = 2) -> str:
    """Render a rate for telemetry headers and terminal output, honouring *unmeasured*."""
    if value is None:
        return UNMEASURED
    return f"{value:.{precision}f}"
