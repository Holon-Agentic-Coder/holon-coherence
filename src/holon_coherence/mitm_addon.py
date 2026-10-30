"""Backward-compatible entry point re-exporting proxy components."""

from __future__ import annotations

import os

from holon_coherence.metrics_math import (
    DEFAULT_WIRE_LOG_DIR,
    UNMEASURED,
    average,
    compute_decode_tps,
    compute_prefill_tps,
    compute_tail_prefill_tps,
    format_rate,
    positive_seconds,
)
from holon_coherence.parsers import (
    TokenCounts,
    estimate_chars,
    extract_detailed_token_counts,
    extract_sse_cache_read_tokens,
    extract_sse_content,
    extract_sse_token_counts,
    extract_token_counts,
    find_nested_key,
    safe_int,
)
from holon_coherence.proxy.addon import (
    DEFAULT_PROXY_LISTEN_PORT,
    MITMProxyInterceptor,
    MitmproxyAddon,
    _MAX_SSE_BUFFER_BYTES,
    addons,
)
from holon_coherence.proxy.dashboard import render_dashboard_html
from holon_coherence.proxy.metrics import CumulativeMetrics
from holon_coherence.proxy.normalise.anthropic import normalize_anthropic_request
from holon_coherence.proxy.routing import _make_http_response, is_local_target
from holon_coherence.proxy.scrubbing import (
    _BODY_SECRET_PATTERNS,
    _SECRET_DICT_KEY_PATTERN,
    _SECRET_HEADER_NAMES,
    _URL_QUERY_SECRET_PATTERN,
    scrub_headers,
    scrub_payload,
    scrub_string,
)
from holon_coherence.proxy.timing import (
    FlowTiming,
    _wall_clock_seconds,
    derive_turn_id,
    get_header_case_insensitive,
    resolve_flow_timing,
)
from holon_coherence.proxy.translation.gemini_openai import (
    translate_gemini_to_openai_request,
    translate_openai_sse_chunk_to_gemini,
    translate_openai_to_gemini_response,
)
from holon_coherence.proxy.wire_log import (
    WIRE_LOG_DIR,
    _discard_pending_future,
    _get_wire_log_executor,
    _pending_wire_log_futures,
    _wire_log_executor,
    _wire_log_lock,
    _write_transaction_sync,
    dump_wire_transaction,
    flush_wire_logs,
    is_flow_passive,
    is_passive_monitoring,
    is_wire_logging_enabled,
    log_telemetry,
    shutdown_wire_logs,
)

CACHE_DIR = os.getenv("CACHE_DIR", os.path.expanduser("~/.holon/cache"))

__all__ = [
    "CACHE_DIR",
    "CumulativeMetrics",
    "DEFAULT_PROXY_LISTEN_PORT",
    "DEFAULT_WIRE_LOG_DIR",
    "FlowTiming",
    "MITMProxyInterceptor",
    "MitmproxyAddon",
    "TokenCounts",
    "UNMEASURED",
    "WIRE_LOG_DIR",
    "_BODY_SECRET_PATTERNS",
    "_MAX_SSE_BUFFER_BYTES",
    "_SECRET_DICT_KEY_PATTERN",
    "_SECRET_HEADER_NAMES",
    "_URL_QUERY_SECRET_PATTERN",
    "_discard_pending_future",
    "_get_wire_log_executor",
    "_make_http_response",
    "_pending_wire_log_futures",
    "_wall_clock_seconds",
    "_wire_log_executor",
    "_wire_log_lock",
    "_write_transaction_sync",
    "addons",
    "average",
    "compute_decode_tps",
    "compute_prefill_tps",
    "compute_tail_prefill_tps",
    "derive_turn_id",
    "dump_wire_transaction",
    "estimate_chars",
    "extract_detailed_token_counts",
    "extract_sse_cache_read_tokens",
    "extract_sse_content",
    "extract_sse_token_counts",
    "extract_token_counts",
    "find_nested_key",
    "flush_wire_logs",
    "format_rate",
    "get_header_case_insensitive",
    "is_flow_passive",
    "is_local_target",
    "is_passive_monitoring",
    "is_wire_logging_enabled",
    "log_telemetry",
    "normalize_anthropic_request",
    "positive_seconds",
    "render_dashboard_html",
    "resolve_flow_timing",
    "safe_int",
    "scrub_headers",
    "scrub_payload",
    "scrub_string",
    "shutdown_wire_logs",
    "translate_gemini_to_openai_request",
    "translate_openai_sse_chunk_to_gemini",
    "translate_openai_to_gemini_response",
]
