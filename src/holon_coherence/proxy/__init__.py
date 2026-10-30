"""Holon Coherence Proxy package."""

from __future__ import annotations

from holon_coherence.proxy.addon import (
    _MAX_SSE_BUFFER_BYTES,
    DEFAULT_PROXY_LISTEN_PORT,
    MitmproxyAddon,
    MITMProxyInterceptor,
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

__all__ = [
    "DEFAULT_PROXY_LISTEN_PORT",
    "WIRE_LOG_DIR",
    "_BODY_SECRET_PATTERNS",
    "_MAX_SSE_BUFFER_BYTES",
    "_SECRET_DICT_KEY_PATTERN",
    "_SECRET_HEADER_NAMES",
    "_URL_QUERY_SECRET_PATTERN",
    "CumulativeMetrics",
    "FlowTiming",
    "MITMProxyInterceptor",
    "MitmproxyAddon",
    "_discard_pending_future",
    "_get_wire_log_executor",
    "_make_http_response",
    "_pending_wire_log_futures",
    "_wall_clock_seconds",
    "_wire_log_executor",
    "_wire_log_lock",
    "_write_transaction_sync",
    "addons",
    "derive_turn_id",
    "dump_wire_transaction",
    "flush_wire_logs",
    "get_header_case_insensitive",
    "is_flow_passive",
    "is_local_target",
    "is_passive_monitoring",
    "is_wire_logging_enabled",
    "log_telemetry",
    "normalize_anthropic_request",
    "render_dashboard_html",
    "resolve_flow_timing",
    "scrub_headers",
    "scrub_payload",
    "scrub_string",
    "shutdown_wire_logs",
    "translate_gemini_to_openai_request",
    "translate_openai_sse_chunk_to_gemini",
    "translate_openai_to_gemini_response",
]
