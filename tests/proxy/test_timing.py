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
    headers_with_turn_id = {"X-Holon-Turn-Id": "5"}
    turn_id_from_header = derive_turn_id(headers_with_turn_id, None, fallback_id=1)
    assert turn_id_from_header == 5

    openai_payload_with_one_assistant_turn = {
        "messages": [
            {"role": "user"},
            {"role": "assistant"},
            {"role": "user"},
        ]
    }
    assert derive_turn_id({}, openai_payload_with_one_assistant_turn, fallback_id=1) == 2

    gemini_payload_with_two_model_turns = {
        "contents": [
            {"role": "user"},
            {"role": "model"},
            {"role": "user"},
            {"role": "model"},
        ]
    }
    assert derive_turn_id({}, gemini_payload_with_two_model_turns, fallback_id=1) == 3

    empty_payload_using_fallback_id: dict[str, object] = {}
    assert derive_turn_id({}, empty_payload_using_fallback_id, fallback_id=99) == 99


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
