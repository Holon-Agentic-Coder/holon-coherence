"""Transaction timing resolution and turn ID calculation."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from holon_coherence.metrics_math import positive_seconds

__all__ = [
    "FlowTiming",
    "_wall_clock_seconds",
    "derive_turn_id",
    "get_header_case_insensitive",
    "resolve_flow_timing",
]


def get_header_case_insensitive(headers: Any, target_header: str) -> str | None:
    """Extracts header value matching target_header case-insensitively."""
    if headers:
        if hasattr(headers, "items"):
            target_lower = target_header.lower()
            for k, v in headers.items():
                if str(k).lower() == target_lower and v:
                    return str(v)
        elif hasattr(headers, "get"):
            val = headers.get(target_header)
            if val:
                return str(val)
    return None


def derive_turn_id(
    headers: Any,
    payload: dict[str, Any] | None,
    fallback_id: int = 1,
) -> int | str:
    """Derives conversation turn ID using 3-tier precedence:
    1. X-Holon-Turn-Id header
    2. Assistant completion count in message tree (+ 1)
    3. Sequential fallback counter
    """
    if headers:
        val = get_header_case_insensitive(headers, "x-holon-turn-id")
        if val is not None:
            try:
                return int(val)
            except ValueError:
                return val

    if isinstance(payload, dict):
        messages = payload.get("messages")
        if isinstance(messages, list):
            assistant_count = len([m for m in messages if isinstance(m, dict) and m.get("role") == "assistant"])
            return assistant_count + 1
        contents = payload.get("contents")
        if isinstance(contents, list):
            model_count = len([c for c in contents if isinstance(c, dict) and c.get("role") in ("model", "assistant")])
            return model_count + 1

    return fallback_id


@dataclass(frozen=True)
class FlowTiming:
    """Per-transaction timings in seconds, where ``None`` means *not measured*.

    Attributes:
        ttft_sec: Request sent -> first token (first SSE chunk, or first payload for a buffered
            reply). ``None`` when either endpoint timestamp is missing.
        total_sec: Request sent -> transaction complete.
        generation_sec: First SSE chunk -> last SSE chunk. Only populated for genuine streams; a
            buffered reply has no generation window, so ``total_sec - ttft_sec`` (socket parse time)
            must never be used as a stand-in.
        streaming: True when the upstream reply was an SSE stream.
    """

    ttft_sec: float | None = None
    total_sec: float | None = None
    generation_sec: float | None = None
    streaming: bool = False

    def decode_reason(self) -> str:
        """Human-readable explanation for an unmeasured decode throughput."""
        if not self.streaming:
            return "non-streaming"
        if self.generation_sec is None:
            return "no chunk window"
        return f"stream window {self.generation_sec * 1000:.0f}ms below floor"


def _wall_clock_seconds(*values: Any) -> float | None:
    """Return the first usable epoch timestamp, or ``None``."""
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        try:
            stamp = float(value)
        except (TypeError, ValueError):
            continue
        if stamp > 0:
            return stamp
    return None


def resolve_flow_timing(flow: Any, completed_at: float | None = None) -> FlowTiming:
    """Derive TTFT / total / generation seconds for one flow using a single clock domain.

    Prefers the ``time.perf_counter()`` stamps the addon records in ``request()`` /
    ``responseheaders()`` / the SSE chunk wrapper. When those are absent (resumed or replayed flows
    whose request hook never fired) it falls back to mitmproxy's own wall-clock timestamps instead
    of substituting ``now`` for a missing start -- that substitution is what produced
    ``ttft == 0.0`` and the resulting ``0.00 tokens/sec`` prefill readings.

    Args:
        flow: mitmproxy flow (or test double) carrying the timing attributes.
        completed_at: ``time.perf_counter()`` reading taken when the transaction finished.

    Returns:
        FlowTiming: Timings in seconds; every field that could not be measured is ``None``.
    """
    streaming = getattr(flow, "sse_chunks", None) is not None
    if completed_at is None:
        completed_at = time.perf_counter()

    req_start = getattr(flow, "request_start_time", None)
    if req_start is not None:
        headers_time = getattr(flow, "response_headers_time", None)
        first_chunk = getattr(flow, "first_chunk_time", None)
        last_chunk = getattr(flow, "last_chunk_time", None)
        end_time = last_chunk if (streaming and last_chunk is not None) else completed_at
    else:
        request = getattr(flow, "request", None)
        response = getattr(flow, "response", None)
        req_start = _wall_clock_seconds(getattr(request, "timestamp_start", None))
        headers_time = _wall_clock_seconds(getattr(response, "timestamp_first_byte", None))
        # A replayed flow exposes only byte-level markers, so first byte stands in for first token.
        first_chunk = headers_time
        end_time = _wall_clock_seconds(getattr(response, "timestamp_end", None))
        last_chunk = end_time

    ttft_sec: float | None = None
    if req_start is not None:
        first_token_time = first_chunk if first_chunk is not None else headers_time
        if first_token_time is not None:
            ttft_sec = positive_seconds(first_token_time - req_start)

    total_sec: float | None = None
    if req_start is not None and end_time is not None:
        total_sec = positive_seconds(end_time - req_start)

    generation_sec: float | None = None
    if streaming:
        # Both window endpoints must share ``first_chunk``'s clock domain. The perf_counter branch
        # always resolves an ``end_time``; in the epoch fallback a missing ``response.timestamp_end``
        # leaves the window unmeasured instead of subtracting an epoch first-chunk from a
        # perf_counter completion.
        if first_chunk is not None and end_time is not None:
            generation_sec = positive_seconds(end_time - first_chunk)
        elif total_sec is not None and ttft_sec is not None:
            generation_sec = positive_seconds(total_sec - ttft_sec)

    return FlowTiming(
        ttft_sec=ttft_sec,
        total_sec=total_sec,
        generation_sec=generation_sec,
        streaming=streaming,
    )
