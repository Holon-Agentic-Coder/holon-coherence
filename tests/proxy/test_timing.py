"""Unit tests for flow timing resolution and turn ID calculation."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from holon_coherence.proxy.timing import (
    FlowTiming,
    _wall_clock_seconds,
    derive_turn_id,
    get_header_case_insensitive,
    resolve_flow_timing,
)


def test_flow_timing_decode_reason() -> None:
    t_non_streaming = FlowTiming(streaming=False)
    assert t_non_streaming.decode_reason() == "non-streaming"

    t_no_chunks = FlowTiming(streaming=True, generation_sec=None)
    assert t_no_chunks.decode_reason() == "no chunk window"

    t_measured = FlowTiming(streaming=True, generation_sec=0.05)
    assert "below floor" in t_measured.decode_reason()


def test_wall_clock_seconds() -> None:
    assert _wall_clock_seconds(None, False, "invalid", 123.45) == 123.45
    assert _wall_clock_seconds(0, -1, None) is None


def test_derive_turn_id_precedence() -> None:
    # 1. Header precedence
    headers = {"X-Holon-Turn-Id": "5"}
    assert derive_turn_id(headers, None, fallback_id=1) == 5

    # 2. Message tree assistant count
    payload_openai = {
        "messages": [
            {"role": "user"},
            {"role": "assistant"},
            {"role": "user"},
        ]
    }
    assert derive_turn_id({}, payload_openai, fallback_id=1) == 2

    # Gemini contents model count
    payload_gemini = {
        "contents": [
            {"role": "user"},
            {"role": "model"},
            {"role": "user"},
            {"role": "model"},
        ]
    }
    assert derive_turn_id({}, payload_gemini, fallback_id=1) == 3

    # 3. Fallback ID
    assert derive_turn_id({}, {}, fallback_id=99) == 99


def test_get_header_case_insensitive() -> None:
    headers = {"Content-Type": "application/json", "X-Custom": "val"}
    assert get_header_case_insensitive(headers, "content-type") == "application/json"
    assert get_header_case_insensitive(headers, "x-custom") == "val"
    assert get_header_case_insensitive(headers, "not-found") is None


def test_resolve_flow_timing_perf_counter() -> None:
    flow = MagicMock()
    flow.sse_chunks = [b"chunk1", b"chunk2"]
    flow.request_start_time = 10.0
    flow.response_headers_time = 10.2
    flow.first_chunk_time = 10.3
    flow.last_chunk_time = 11.0

    timing = resolve_flow_timing(flow, completed_at=11.1)
    assert timing.streaming is True
    assert timing.ttft_sec == pytest.approx(0.3)
    assert timing.total_sec == pytest.approx(1.0)
    assert timing.generation_sec == pytest.approx(0.7)
