"""Builder for the ``transactions.jsonl`` wire record.

The record is the system of record for A/B telemetry, so its schema, key order, rounding and
scrubbing must not drift. Helpers compute the sections; ``build_wire_record`` assembles them in one
place so the key order stays visible.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from holon_coherence.parsers import extract_detailed_token_counts, extract_sse_content
from holon_coherence.proxy.scrubbing import scrub_headers, scrub_payload, scrub_string
from holon_coherence.proxy.timing import derive_turn_id, get_header_case_insensitive
from holon_coherence.proxy.wire_log import is_flow_passive

__all__ = ["WireTransaction", "build_wire_record"]


@dataclass(frozen=True)
class WireTransaction:
    """Per-transaction facts the hooks know but the flow does not carry."""

    is_hit: bool = False
    is_sse: bool = False
    ttft: float | None = None
    total_time: float | None = None
    prefill_tps: float | None = None
    tail_prefill_tps: float | None = None
    decode_tps: float | None = None
    generation_time: float | None = None


def _identity(flow: Any, flow_headers: Any) -> tuple[str, str, str]:
    flow_id = getattr(flow, "id", None) or f"flow_{uuid.uuid4().hex[:8]}"
    agent_id = get_header_case_insensitive(flow_headers, "x-holon-agent-id") or os.getenv("HOLON_AGENT_ID", "agy")
    agent_role = get_header_case_insensitive(flow_headers, "x-holon-agent-role") or os.getenv("HOLON_ROLE", "executor")
    return flow_id, agent_id, agent_role


def _delta(raw_req: Any, cleaned_req: Any, clean_res: Any) -> dict[str, int]:
    try:
        raw_chars = len(json.dumps(raw_req)) if raw_req else 0
        cleaned_chars = len(json.dumps(cleaned_req)) if cleaned_req else 0
    except Exception:
        raw_chars = 0
        cleaned_chars = 0
    if not clean_res:
        return {
            "raw_chars": raw_chars,
            "cleaned_chars": cleaned_chars,
            "chars_saved": max(0, raw_chars - cleaned_chars),
            "tool_outputs_omitted": 0,
            "turns_summarized": 0,
            "cache_control_injected": 0,
        }
    return {
        "raw_chars": raw_chars,
        "cleaned_chars": cleaned_chars,
        "chars_saved": clean_res.chars_saved,
        "tool_outputs_omitted": clean_res.tool_outputs_omitted,
        "turns_summarized": clean_res.turns_summarized,
        "cache_control_injected": clean_res.cache_control_injected,
    }


def _usage(raw_req: Any, cleaned_req: Any, resp_data: Any, provider: str, is_hit: bool) -> dict[str, Any]:
    if is_hit:
        detailed_tokens = extract_detailed_token_counts(raw_req, resp_data, provider)
        detailed_tokens["cache_read_input_tokens"] = detailed_tokens["input_tokens"]
    else:
        detailed_tokens = extract_detailed_token_counts(cleaned_req, resp_data, provider)
    return {
        "input_tokens": detailed_tokens["input_tokens"],
        "cache_creation_input_tokens": detailed_tokens["cache_creation_input_tokens"],
        "cache_read_input_tokens": detailed_tokens["cache_read_input_tokens"],
        "output_tokens": detailed_tokens["output_tokens"],
        "reasoning_tokens": detailed_tokens["reasoning_tokens"],
    }


def _content(resp_data: Any, provider: str, is_sse: bool) -> Any:
    if is_sse:
        return extract_sse_content(resp_data, provider)
    if isinstance(resp_data, dict):
        return resp_data
    return str(resp_data)


def _ms(seconds: float | None) -> float | None:
    return round(seconds * 1000, 2) if seconds is not None else None


def _round(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


def _timing(tx: WireTransaction) -> dict[str, Any]:
    ttft_ms = _ms(tx.ttft)
    total_ms = _ms(tx.total_time)
    return {
        "ttft_ms": ttft_ms if ttft_ms is not None else (0.0 if tx.is_hit else None),
        "total_ms": total_ms if total_ms is not None else 0.0,
        "streaming": bool(tx.is_sse),
        "generation_ms": _ms(tx.generation_time),
        "prefill_tps": _round(tx.prefill_tps),
        "tail_prefill_tps": _round(tx.tail_prefill_tps),
        "decode_tps": _round(tx.decode_tps),
    }


def _mode(addon: Any, flow: Any) -> str:
    passive = is_flow_passive(flow, default_passive=getattr(addon, "default_passive", None))
    return "baseline" if passive else "optimized"


def build_wire_record(addon: Any, flow: Any, resp_data: Any, status_code: int, tx: WireTransaction) -> dict[str, Any]:
    """Assemble the scrubbed wire record for one transaction."""
    url = getattr(flow.request, "pretty_url", "")
    flow_headers = getattr(flow.request, "headers", {})
    provider = getattr(flow, "provider", "unknown")
    flow_id, agent_id, agent_role = _identity(flow, flow_headers)

    raw_req = getattr(flow, "raw_request_data", None) or getattr(flow, "req_data", None) or {}
    cleaned_req = getattr(flow, "req_data", None) or raw_req
    turn_id = derive_turn_id(flow_headers, raw_req, addon.total_requests)
    delta = _delta(raw_req, cleaned_req, getattr(flow, "cleaner_result", None))
    usage = _usage(raw_req, cleaned_req, resp_data, provider, tx.is_hit)
    content_val = _content(resp_data, provider, tx.is_sse)

    return {
        "turn_id": turn_id,
        "flow_id": flow_id,
        "agent_id": agent_id,
        "agent_role": agent_role,
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "provider": provider,
        "endpoint": scrub_string(url),
        "headers": scrub_headers(flow_headers),
        "raw_request": scrub_payload(raw_req),
        "cleaned_request": scrub_payload(cleaned_req),
        "delta": delta,
        "mode": _mode(addon, flow),
        "cache_action": "HIT" if tx.is_hit else "MISS",
        "response": {
            "status": status_code,
            "usage": usage,
            "content": scrub_payload(content_val),
        },
        "timing": _timing(tx),
    }
