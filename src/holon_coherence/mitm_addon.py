"""MITM proxy interceptor & addon for LLM API request optimization and response caching (Phase 3)."""

import atexit
import concurrent.futures
import contextlib
import copy
import json
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

try:
    from mitmproxy import ctx, http
except ImportError:
    ctx = None
    http = None

from holon_coherence.host_local import (
    GATEWAY_HOSTNAME,
    in_container,
    resolve_gateway_address,
    rewrite_connection,
    targets_from_env,
)
from holon_coherence.hybrid_cache import HybridCacheStore
from holon_coherence.metrics_math import (
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
from holon_coherence.payload_cleaner import CleaningResult, JSONContextCleaner

__all__ = [
    "CumulativeMetrics",
    "MITMProxyInterceptor",
    "MitmproxyAddon",
    "TokenCounts",
    "estimate_chars",
    "extract_detailed_token_counts",
    "extract_sse_cache_read_tokens",
    "extract_sse_content",
    "extract_sse_token_counts",
    "extract_token_counts",
    "find_nested_key",
    "is_flow_passive",
    "is_local_target",
    "is_passive_monitoring",
    "normalize_anthropic_request",
    "render_dashboard_html",
    "safe_int",
    "translate_gemini_to_openai_request",
    "translate_openai_sse_chunk_to_gemini",
    "translate_openai_to_gemini_response",
]

logger = logging.getLogger(__name__)

WIRE_LOG_DIR = os.getenv("WIRE_LOG_DIR", "todo/mitm_wire_logs")
CACHE_DIR = os.getenv("CACHE_DIR", os.path.expanduser("~/.holon/cache"))
DEFAULT_PROXY_LISTEN_PORT = 8080

_MAX_SSE_BUFFER_BYTES = 50 * 1024 * 1024

_SECRET_HEADER_NAMES = {
    "authorization",
    "auth",
    "credential",
    "credentials",
    "x-api-key",
    "api-key",
    "x-anthropic-api-key",
    "x-goog-api-key",
    "holon-agent-key",
    "proxy-authorization",
    "x-amz-security-token",
    "cookie",
    "set-cookie",
    "x-auth-token",
    "openai-api-key",
    "x-session-token",
}

_URL_QUERY_SECRET_PATTERN = re.compile(
    r'(?i)([?&](?:key|api_key|apiKey|api-key|apikey|token|access_token|auth_token|secret)=)[^&\s"\'`<>#]+'
)

_BODY_SECRET_PATTERNS = [
    # Anthropic
    re.compile(r"\bsk-ant-[a-zA-Z0-9_\-]{20,}\b"),
    # OpenAI
    re.compile(r"\bsk-(?:proj-|admin-|svcacct-)?[a-zA-Z0-9_\-]{20,}\b"),
    # Google Cloud / Vertex AI
    re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b"),
    # GitHub tokens
    re.compile(r"\bgh[pousr]_[a-zA-Z0-9]{36}\b"),
    re.compile(r"\bgithub_pat_[a-zA-Z0-9_]{22,}\b"),
    # AWS access keys
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bASIA[0-9A-Z]{16}\b"),
    # AWS secret access key
    re.compile(
        r'(?i)\b(?:aws_secret_access_key|aws_secret_key|secret_access_key)\s*[:=]\s*["\']?(?:[A-Za-z0-9/+=]{40})["\']?'
    ),
    # Hugging Face
    re.compile(r"\bhf_[a-zA-Z0-9]{34,}\b"),
    # JWT Bearer tokens
    re.compile(r"\beyJ[a-zA-Z0-9_\-]{20,}\.[a-zA-Z0-9_\-]{20,}\.[a-zA-Z0-9_\-]{20,}\b"),
    # PEM & PGP Private Key Blocks (including PKCS#8)
    re.compile(
        r"-----BEGIN (?:[A-Z\s]+ )?PRIVATE KEY(?: BLOCK)?-----"
        r"[\s\S]*?-----END (?:[A-Z\s]+ )?PRIVATE KEY(?: BLOCK)?-----"
    ),
]

_SECRET_DICT_KEY_PATTERN = re.compile(
    r"(?i)^(?:auth|authorization|credential|credentials|password|passwd|token|api[-_]?key|apikey|api[-_]?token|auth[-_]?token|access[-_]?token|refresh[-_]?token|id[-_]?token|secret[-_]?key|secret|private[-_]?key|client[-_]?secret|session[-_]?token)$"
)


def scrub_string(text: str) -> str:
    """Scrubs sensitive credentials from string payloads or URLs."""
    if not isinstance(text, str) or not text:
        return text
    # 1. URL query parameters
    text = _URL_QUERY_SECRET_PATTERN.sub(r"\1[REDACTED]", text)
    # 2. Body secret patterns
    for pattern in _BODY_SECRET_PATTERNS:
        text = pattern.sub("[REDACTED_SECRET]", text)
    return text


def scrub_headers(headers: Any) -> dict[str, str]:
    """Scrubs sensitive credentials and normalizes header keys."""
    cleaned: dict[str, str] = {}
    if hasattr(headers, "items"):
        items = headers.items()
    elif isinstance(headers, (list, tuple)):
        items = headers
    elif isinstance(headers, dict):
        items = headers.items()
    else:
        return {}

    for k, v in items:
        k_str = str(k).lower()
        if (
            k_str in _SECRET_HEADER_NAMES
            or _SECRET_DICT_KEY_PATTERN.match(k_str)
            or "token" in k_str
            or "secret" in k_str
        ):
            cleaned[k_str] = "[REDACTED]"
        else:
            cleaned[k_str] = scrub_string(str(v))
    return cleaned


def scrub_payload(data: Any, max_depth: int = 50) -> Any:
    """Recursively scrubs sensitive keys and credentials in JSON-serializable payloads."""
    if max_depth <= 0:
        return data
    if isinstance(data, dict):
        cleaned: dict[str, Any] = {}
        for k, v in data.items():
            k_str = str(k).lower()
            if _SECRET_DICT_KEY_PATTERN.match(k_str):
                cleaned[k] = "[REDACTED]"
            else:
                cleaned[k] = scrub_payload(v, max_depth=max_depth - 1)
        return cleaned
    elif isinstance(data, (list, tuple)):
        scrubbed_seq = [scrub_payload(elem, max_depth=max_depth - 1) for elem in data]
        return tuple(scrubbed_seq) if isinstance(data, tuple) else scrubbed_seq
    elif isinstance(data, str):
        return scrub_string(data)
    else:
        return data


def is_wire_logging_enabled() -> bool:
    """Checks whether wire logging is enabled via environment configuration."""
    flag = os.getenv("ENABLE_WIRE_LOGGING", "1").lower().strip()
    return flag not in ("0", "false", "no", "off")


def is_passive_monitoring() -> bool:
    """Checks whether proxy operates in passive monitoring mode (logging only, no reduction/caching)."""
    flag = os.getenv("HOLON_PASSIVE_MONITORING", "0").lower().strip()
    if flag in ("1", "true", "yes", "on"):
        return True
    tr_flag = os.getenv("COHERENCE_TOKEN_REDUCTION", "1").lower().strip()
    return tr_flag in ("0", "false", "no", "off")


def is_flow_passive(flow: Any, default_passive: bool | None = None) -> bool:
    """Checks whether the flow should be handled in passive monitoring mode (baseline)."""
    try:
        if flow and hasattr(flow, "request") and hasattr(flow.request, "headers"):
            headers = flow.request.headers
            for key in ("x-holon-passive", "x-holon-mode", "X-Holon-Passive", "X-Holon-Mode"):
                val = headers.get(key)
                if val:
                    val_clean = val.strip().lower()
                    if val_clean in ("1", "true", "yes", "baseline", "passive"):
                        return True
                    if val_clean in ("0", "false", "no", "optimized", "active"):
                        return False
    except Exception:
        pass
    if default_passive is not None:
        return default_passive
    return is_passive_monitoring()


_wire_log_executor: concurrent.futures.ThreadPoolExecutor | None = None
_pending_wire_log_futures: set[concurrent.futures.Future] = set()
_wire_log_lock = threading.Lock()


def _get_wire_log_executor() -> concurrent.futures.ThreadPoolExecutor:
    global _wire_log_executor
    with _wire_log_lock:
        if _wire_log_executor is None or getattr(_wire_log_executor, "_shutdown", False):
            _wire_log_executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="mitm_wire_logger"
            )
        return _wire_log_executor


def _write_transaction_sync(record: dict[str, Any], wire_log_dir: str) -> None:
    try:
        os.makedirs(wire_log_dir, mode=0o700, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(wire_log_dir, 0o700)
        turn_id = record.get("turn_id", 0)
        flow_id = record.get("flow_id", "flow")
        safe_turn_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(turn_id))
        safe_flow_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(flow_id))
        filename = f"turn_{safe_turn_id}_{safe_flow_id}.json"
        filepath = os.path.join(wire_log_dir, filename)

        tmp_filepath = f"{filepath}.{uuid.uuid4().hex[:6]}.tmp"
        try:
            fd = os.open(tmp_filepath, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(record, f, indent=2, ensure_ascii=False, default=str)
            with contextlib.suppress(OSError):
                os.chmod(tmp_filepath, 0o600)
            os.replace(tmp_filepath, filepath)
            with contextlib.suppress(OSError):
                os.chmod(filepath, 0o600)
        except Exception:
            if os.path.exists(tmp_filepath):
                with contextlib.suppress(OSError):
                    os.unlink(tmp_filepath)
            raise

        jsonl_path = os.path.join(wire_log_dir, "transactions.jsonl")
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        j_fd = os.open(jsonl_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(j_fd, "a", encoding="utf-8") as f:
            f.write(line)
        with contextlib.suppress(OSError):
            os.chmod(jsonl_path, 0o600)
    except Exception as exc:
        logger.warning("Failed to persist wire log transaction: %s", exc)


def dump_wire_transaction(record: dict[str, Any], wire_log_dir: str | None = None) -> concurrent.futures.Future:
    """Asynchronously writes turn-scoped JSON dump and atomic JSONL entry."""
    target_dir = wire_log_dir or os.getenv("WIRE_LOG_DIR", WIRE_LOG_DIR)
    if not is_wire_logging_enabled() or not target_dir:
        dummy: concurrent.futures.Future = concurrent.futures.Future()
        dummy.set_result(None)
        return dummy

    future = _get_wire_log_executor().submit(_write_transaction_sync, record, target_dir)
    with _wire_log_lock:
        _pending_wire_log_futures.add(future)
    future.add_done_callback(_discard_pending_future)
    return future


def _discard_pending_future(future: concurrent.futures.Future) -> None:
    with _wire_log_lock:
        _pending_wire_log_futures.discard(future)


def flush_wire_logs(timeout: float = 5.0) -> None:
    """Blocks until all queued background wire log writes complete."""
    with _wire_log_lock:
        pending = list(_pending_wire_log_futures)
    if pending:
        concurrent.futures.wait(pending, timeout=timeout)


def shutdown_wire_logs(wait: bool = True, timeout: float = 5.0) -> None:
    """Blocks until pending wire log writes finish and cleanly shuts down the ThreadPoolExecutor."""
    global _wire_log_executor
    flush_wire_logs(timeout=timeout)
    with _wire_log_lock:
        if _wire_log_executor is not None and not getattr(_wire_log_executor, "_shutdown", False):
            try:
                _wire_log_executor.shutdown(wait=wait)
            except Exception as exc:
                logger.debug("Error shutting down wire log executor: %s", exc)
            _wire_log_executor = None


atexit.register(shutdown_wire_logs)


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
    """Per-transaction timings in seconds, where ``None`` means *not measured* (Bean 0097).

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


@dataclass
class CumulativeMetrics:
    """Thread-safe cumulative metrics tracking context optimization and cache performance (Bean 0043)."""

    total_turns: int = 0
    total_requests: int = 0
    cache_hits: int = 0
    tool_calls_pruned: int = 0
    tokens_reduced: int = 0
    chars_saved: int = 0
    turns_summarized: int = 0
    cache_control_injected: int = 0
    sum_ttft_ms: float = 0.0
    count_ttft: int = 0
    sum_decode_throughput_tps: float = 0.0
    count_decode: int = 0
    sum_prefill_throughput_tps: float = 0.0
    count_prefill: int = 0
    latest_prefill_tps: float = 0.0
    sum_tail_prefill_throughput_tps: float = 0.0
    count_tail_prefill: int = 0
    latest_tail_prefill_tps: float = 0.0
    latest_decode_tps: float = 0.0
    latest_ttft_ms: float = 0.0
    latest_total_time_ms: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_creation_tokens: int = 0
    total_reasoning_tokens: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record_request(self) -> None:
        """Records an intercepted request."""
        with self._lock:
            self.total_requests += 1

    def record_cleaner(self, clean_res: Any) -> None:
        """Accumulates optimization statistics from a CleaningResult."""
        if clean_res is None:
            return
        with self._lock:
            self.tool_calls_pruned += getattr(clean_res, "tool_outputs_omitted", 0)
            chars = getattr(clean_res, "chars_saved", 0)
            self.chars_saved += chars
            self.tokens_reduced += chars // 4
            self.turns_summarized += getattr(clean_res, "turns_summarized", 0)
            self.cache_control_injected += getattr(clean_res, "cache_control_injected", 0)

    def record_cache_hit(self) -> None:
        """Records a successful local cache hit."""
        with self._lock:
            self.cache_hits += 1
            self.total_turns += 1

    def record_response(
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
        """Records completed response metrics including token counts and timing.

        Throughput arguments use ``None`` for *not measured* (Bean 0097): a non-streaming reply or
        a sub-floor streaming window must be omitted from the averages rather than entered as a
        fabricated rate.
        """
        with self._lock:
            self.total_turns += 1
            self.total_input_tokens += input_tokens
            self.total_output_tokens += output_tokens
            self.total_cache_read_tokens += cache_read_tokens
            self.total_cache_creation_tokens += cache_creation_tokens
            self.total_reasoning_tokens += reasoning_tokens
            if ttft is not None and ttft > 0:
                self.sum_ttft_ms += ttft * 1000.0
                self.count_ttft += 1
            if ttft is not None and ttft > 0:
                self.latest_ttft_ms = ttft * 1000.0
            if total_time is not None and total_time > 0:
                self.latest_total_time_ms = total_time * 1000.0
            if output_tps is not None and output_tps > 0:
                self.sum_decode_throughput_tps += output_tps
                self.count_decode += 1
                self.latest_decode_tps = output_tps
            if prefill_tps is not None and prefill_tps > 0:
                self.sum_prefill_throughput_tps += prefill_tps
                self.count_prefill += 1
                self.latest_prefill_tps = prefill_tps
            if tail_prefill_tps is not None and tail_prefill_tps > 0:
                self.sum_tail_prefill_throughput_tps += tail_prefill_tps
                self.count_tail_prefill += 1
                self.latest_tail_prefill_tps = tail_prefill_tps

    def to_dict(self) -> dict[str, Any]:
        """Produces a snapshot dictionary of cumulative metrics and derived rates."""
        with self._lock:
            hit_rate = (self.cache_hits / self.total_requests) if self.total_requests > 0 else 0.0
            provider_cache_hit_rate = (
                (self.total_cache_read_tokens / self.total_input_tokens) if self.total_input_tokens > 0 else 0.0
            )
            avg_ttft = average(self.sum_ttft_ms, self.count_ttft)
            avg_tps = average(self.sum_decode_throughput_tps, self.count_decode)
            avg_prefill = average(self.sum_prefill_throughput_tps, self.count_prefill)
            avg_tail_prefill = average(self.sum_tail_prefill_throughput_tps, self.count_tail_prefill)
            count_decode_samples = self.count_decode
            return {
                "total_turns": self.total_turns,
                "total_requests": self.total_requests,
                "cache_hits": self.cache_hits,
                "cache_misses": max(0, self.total_requests - self.cache_hits),
                "cache_hit_rate": round(hit_rate, 4),
                "provider_cache_hit_rate": round(provider_cache_hit_rate, 4),
                "tool_calls_pruned": self.tool_calls_pruned,
                "tokens_reduced": self.tokens_reduced,
                "chars_saved": self.chars_saved,
                "turns_summarized": self.turns_summarized,
                "cache_control_injected": self.cache_control_injected,
                "avg_ttft_ms": round(avg_ttft, 2),
                "avg_decode_throughput_tps": round(avg_tps, 2),
                "latest_decode_throughput_tps": round(self.latest_decode_tps, 2),
                "decode_samples": count_decode_samples,
                "avg_prefill_throughput_tps": round(avg_prefill, 2),
                "latest_prefill_tps": round(self.latest_prefill_tps, 2),
                "latest_prefill_throughput_tps": round(self.latest_prefill_tps, 2),
                "avg_tail_prefill_tps": round(avg_tail_prefill, 2),
                "avg_tail_prefill_throughput_tps": round(avg_tail_prefill, 2),
                "latest_tail_prefill_tps": round(self.latest_tail_prefill_tps, 2),
                "latest_tail_prefill_throughput_tps": round(self.latest_tail_prefill_tps, 2),
                "avg_prompt_prefill_speed_tps": round(avg_prefill, 2),
                "avg_tail_prefill_speed_tps": round(avg_tail_prefill, 2),
                "latest_ttft_ms": round(self.latest_ttft_ms, 2),
                "latest_total_time_ms": round(self.latest_total_time_ms, 2),
                "total_input_tokens": self.total_input_tokens,
                "total_output_tokens": self.total_output_tokens,
                "total_cache_read_tokens": self.total_cache_read_tokens,
                "total_cache_creation_tokens": self.total_cache_creation_tokens,
                "total_reasoning_tokens": self.total_reasoning_tokens,
            }


def _make_http_response(flow: Any, status_code: int, content: bytes, headers: dict[str, str]) -> Any:
    """Creates an HTTP response object compatible with both live mitmproxy and mock test harnesses."""
    response_cls = getattr(http, "Response", None) or getattr(flow, "Response", None) or globals().get("Response")
    if response_cls and hasattr(response_cls, "make"):
        return response_cls.make(status_code, content, headers)

    class _SimpleResponse:
        def __init__(self, sc: int, body: bytes, hdrs: dict[str, str]):
            self.status_code = sc
            self.headers = hdrs
            self.content = body
            self._text = body.decode("utf-8", errors="ignore")

        def get_text(self) -> str:
            return self._text

        def set_text(self, text: str) -> None:
            self._text = text
            self.content = text.encode("utf-8")

    return _SimpleResponse(status_code, content, headers)


def is_local_target(flow: Any) -> bool:
    """Checks whether flow is directed to a local or non-cloud target."""
    req = getattr(flow, "request", None)
    if req is None:
        return False
    host = getattr(req, "pretty_host", "") or getattr(req, "host", "")
    url = getattr(req, "pretty_url", "")
    if not host and url:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        host = parsed.hostname or ""

    host_lower = host.lower()
    if host_lower in ("localhost", "127.0.0.1", "::1", "127.0.0.1.nip.io", "localhost.nip.io", GATEWAY_HOSTNAME):
        return True

    targets = targets_from_env()
    for t in targets:
        if t.host == host_lower or t.canonical == host_lower:
            return True
        if (
            hasattr(req, "port")
            and t.port
            and t.port == req.port
            and t.host in ("localhost", "127.0.0.1", "::1", host_lower)
        ):
            return True

    cloud_anthropic = ("api.anthropic.com", "anthropic.com")
    provider = getattr(flow, "provider", "unknown")
    if provider == "anthropic" and host_lower and host_lower not in cloud_anthropic:
        return True

    cloud_gemini = ("generativelanguage.googleapis.com", "googleapis.com")
    return bool(provider == "gemini" and host_lower and not any(host_lower.endswith(c) for c in cloud_gemini))


def normalize_anthropic_request(
    flow: Any,
    data: dict[str, Any],
    is_local: bool | None = None,
) -> tuple[dict[str, Any], bool]:
    """Normalizes Anthropic request for host-local engines by stripping vendor-specific fields.

    Strips thinking, output_config, context_management, vendor anthropic-beta headers,
    and prompt cache control blocks when targeting host-local servers.
    """
    if is_local is None:
        is_local = is_local_target(flow)

    if not is_local:
        return data, False

    # 1. Pop unsupported vendor blocks from top-level body
    data.pop("thinking", None)
    data.pop("output_config", None)
    data.pop("context_management", None)

    # 2. Recursively strip cache_control from messages
    messages = data.get("messages")
    if isinstance(messages, list):
        for msg in messages:
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict):
                            part.pop("cache_control", None)
                elif isinstance(content, dict):
                    content.pop("cache_control", None)

    # 3. Strip cache_control from system prompts
    system = data.get("system")
    if isinstance(system, list):
        for part in system:
            if isinstance(part, dict):
                part.pop("cache_control", None)
    elif isinstance(system, dict):
        system.pop("cache_control", None)

    # 4. Strip cache_control from tool definitions
    tools = data.get("tools")
    if isinstance(tools, list):
        for tool in tools:
            if isinstance(tool, dict):
                tool.pop("cache_control", None)

    # 5. Remove vendor anthropic-beta header from request headers
    req = getattr(flow, "request", None)
    if req is not None and hasattr(req, "headers") and req.headers is not None:
        headers = req.headers
        if hasattr(headers, "keys"):
            for k in list(headers.keys()):
                if str(k).lower() == "anthropic-beta":
                    del headers[k]

    return data, True


def translate_gemini_to_openai_request(
    gemini_req: dict[str, Any],
    model: str | None = None,
) -> dict[str, Any]:
    """Translates a Gemini v1beta generateContent/streamGenerateContent request to OpenAI format."""
    openai_messages: list[dict[str, Any]] = []
    pending_tool_call_ids: dict[str, list[str]] = {}
    tool_call_counts: dict[str, int] = {}

    # 1. System instruction translation
    sys_inst = gemini_req.get("systemInstruction") or gemini_req.get("system_instruction")
    if isinstance(sys_inst, dict):
        parts = sys_inst.get("parts", [])
        sys_texts = [p["text"] for p in parts if isinstance(p, dict) and "text" in p]
        if sys_texts:
            openai_messages.append({"role": "system", "content": "\n\n".join(sys_texts)})

    # 2. Contents translation
    contents = gemini_req.get("contents", [])
    if isinstance(contents, list):
        for item in contents:
            if not isinstance(item, dict):
                continue
            role = item.get("role", "user")
            mapped_role = "assistant" if role in ("model", "assistant") else "user"
            parts = item.get("parts", [])

            text_chunks: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            tool_responses: list[dict[str, Any]] = []

            for p in parts:
                if not isinstance(p, dict):
                    continue
                if "text" in p:
                    text_chunks.append(str(p["text"]))
                elif "functionCall" in p:
                    fc = p["functionCall"]
                    fn_name = fc.get("name", "")
                    fn_args = fc.get("args", {})
                    call_id = fc.get("id")
                    if not call_id:
                        tool_call_counts[fn_name] = tool_call_counts.get(fn_name, 0) + 1
                        idx = tool_call_counts[fn_name]
                        call_id = f"call_{fn_name}" if idx == 1 else f"call_{fn_name}_{idx}"
                    pending_tool_call_ids.setdefault(fn_name, []).append(call_id)
                    tool_calls.append(
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": fn_name,
                                "arguments": json.dumps(fn_args) if not isinstance(fn_args, str) else fn_args,
                            },
                        }
                    )
                elif "functionResponse" in p:
                    fr = p["functionResponse"]
                    fn_name = fr.get("name", "")
                    resp_val = fr.get("response", {})
                    fr_id = fr.get("id")
                    tool_responses.append(
                        {
                            "name": fn_name,
                            "response": resp_val,
                            "id": fr_id,
                        }
                    )

            if tool_responses:
                for tr in tool_responses:
                    resp_data = tr["response"]
                    if isinstance(resp_data, dict) and "content" in resp_data:
                        content_body = (
                            json.dumps(resp_data["content"])
                            if not isinstance(resp_data["content"], str)
                            else resp_data["content"]
                        )
                    else:
                        content_body = json.dumps(resp_data) if not isinstance(resp_data, str) else resp_data

                    fn_name = tr["name"]
                    tool_call_id = tr.get("id")
                    if not tool_call_id:
                        if pending_tool_call_ids.get(fn_name):
                            tool_call_id = pending_tool_call_ids[fn_name].pop(0)
                        else:
                            tool_call_id = f"call_{fn_name}"

                    openai_messages.append(
                        {
                            "role": "tool",
                            "name": fn_name,
                            "tool_call_id": tool_call_id,
                            "content": content_body,
                        }
                    )
            else:
                msg: dict[str, Any] = {"role": mapped_role}
                if text_chunks:
                    msg["content"] = "\n".join(text_chunks)
                else:
                    msg["content"] = "" if not tool_calls else None
                if tool_calls:
                    msg["tool_calls"] = tool_calls
                openai_messages.append(msg)

    openai_req: dict[str, Any] = {"messages": openai_messages}

    # 3. Model name
    if model:
        openai_req["model"] = model
    elif gemini_req.get("model"):
        openai_req["model"] = gemini_req["model"]
    else:
        openai_req["model"] = "default"

    # 4. Tools translation
    tools = gemini_req.get("tools")
    if isinstance(tools, list):
        openai_tools: list[dict[str, Any]] = []
        for t in tools:
            if not isinstance(t, dict):
                continue
            for fd in t.get("functionDeclarations", []):
                if not isinstance(fd, dict):
                    continue
                tool_dict: dict[str, Any] = {
                    "type": "function",
                    "function": {
                        "name": fd.get("name", ""),
                        "description": fd.get("description", ""),
                    },
                }
                if "parameters" in fd and isinstance(fd["parameters"], dict):
                    tool_dict["function"]["parameters"] = copy.deepcopy(fd["parameters"])
                openai_tools.append(tool_dict)
        if openai_tools:
            openai_req["tools"] = openai_tools

    # 5. Generation config
    gen_config = gemini_req.get("generationConfig", {})
    if isinstance(gen_config, dict):
        if "temperature" in gen_config:
            openai_req["temperature"] = gen_config["temperature"]
        if "maxOutputTokens" in gen_config:
            openai_req["max_tokens"] = gen_config["maxOutputTokens"]
        if "topP" in gen_config:
            openai_req["top_p"] = gen_config["topP"]
        if "stopSequences" in gen_config:
            openai_req["stop"] = gen_config["stopSequences"]

    return openai_req


def translate_openai_to_gemini_response(openai_resp: dict[str, Any]) -> dict[str, Any]:
    """Translates an OpenAI chat completion response to Gemini v1beta candidate structure."""
    candidates: list[dict[str, Any]] = []
    choices = openai_resp.get("choices", [])

    if isinstance(choices, list) and choices:
        for idx, choice in enumerate(choices):
            if not isinstance(choice, dict):
                continue
            message = choice.get("message", {})
            parts: list[dict[str, Any]] = []

            # 1. Text content
            content = message.get("content")
            if content:
                parts.append({"text": content})

            # 2. Tool calls
            tool_calls = message.get("tool_calls", [])
            if isinstance(tool_calls, list):
                for tc in tool_calls:
                    if not isinstance(tc, dict):
                        continue
                    fn = tc.get("function", {})
                    fn_name = fn.get("name", "")
                    raw_args = fn.get("arguments", "{}")
                    if isinstance(raw_args, str):
                        try:
                            parsed_args = json.loads(raw_args)
                        except Exception:
                            parsed_args = {"raw": raw_args}
                    elif isinstance(raw_args, dict):
                        parsed_args = raw_args
                    else:
                        parsed_args = {}
                    parts.append(
                        {
                            "functionCall": {
                                "name": fn_name,
                                "args": parsed_args,
                            }
                        }
                    )

            if not parts:
                parts.append({"text": ""})

            # Map finish reason
            finish_reason = choice.get("finish_reason")
            mapped_reason = "STOP"
            if finish_reason == "length":
                mapped_reason = "MAX_TOKENS"
            elif finish_reason == "tool_calls":
                mapped_reason = "STOP"

            candidates.append(
                {
                    "index": choice.get("index", idx),
                    "content": {
                        "role": "model",
                        "parts": parts,
                    },
                    "finishReason": mapped_reason,
                }
            )
    else:
        candidates.append(
            {
                "index": 0,
                "content": {
                    "role": "model",
                    "parts": [{"text": ""}],
                },
                "finishReason": "STOP",
            }
        )

    # Usage metadata
    usage = openai_resp.get("usage", {})
    prompt_toks = usage.get("prompt_tokens", 0) if isinstance(usage, dict) else 0
    completion_toks = usage.get("completion_tokens", 0) if isinstance(usage, dict) else 0
    total_toks = usage.get("total_tokens", prompt_toks + completion_toks) if isinstance(usage, dict) else 0

    return {
        "candidates": candidates,
        "usageMetadata": {
            "promptTokenCount": prompt_toks,
            "candidatesTokenCount": completion_toks,
            "totalTokenCount": total_toks,
        },
    }


def translate_openai_sse_chunk_to_gemini(
    chunk_str: str,
    stream_state: dict[str, Any] | None = None,
) -> str:
    """Translates OpenAI SSE streaming chunk(s) to Gemini v1beta candidate SSE chunks."""
    output_lines: list[str] = []
    lines = chunk_str.split("\n")

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == "data: [DONE]":
            continue
        if stripped.startswith("data:"):
            payload_str = stripped[len("data:") :].strip()
            if not payload_str:
                continue
            try:
                chunk_json = json.loads(payload_str)
            except Exception:
                continue

            usage = chunk_json.get("usage")
            usage_metadata: dict[str, Any] | None = None
            if isinstance(usage, dict):
                usage_metadata = {
                    "promptTokenCount": usage.get("prompt_tokens", 0),
                    "candidatesTokenCount": usage.get("completion_tokens", 0),
                    "totalTokenCount": usage.get("total_tokens", 0),
                }

            choices = chunk_json.get("choices", [])
            if not choices and usage_metadata:
                output_lines.append(f"data: {json.dumps({'usageMetadata': usage_metadata})}")
                continue

            for choice in choices:
                delta = choice.get("delta", {})
                parts: list[dict[str, Any]] = []

                if "content" in delta and delta["content"] is not None:
                    parts.append({"text": delta["content"]})

                tool_calls = delta.get("tool_calls", [])
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    fn_name = fn.get("name", "")
                    raw_args = fn.get("arguments", "")

                    if stream_state is not None:
                        idx = tc.get("index", 0)
                        tool_buf = stream_state.setdefault("tool_calls", {}).setdefault(
                            idx, {"name": "", "arguments": ""}
                        )
                        if fn_name:
                            tool_buf["name"] = fn_name
                        if raw_args:
                            tool_buf["arguments"] += raw_args
                    else:
                        if not fn_name and not raw_args:
                            continue
                        if not fn_name:
                            continue
                        if isinstance(raw_args, str):
                            try:
                                parsed_args = json.loads(raw_args) if raw_args else {}
                            except Exception:
                                continue
                        elif isinstance(raw_args, dict):
                            parsed_args = raw_args
                        else:
                            parsed_args = {}
                        parts.append({"functionCall": {"name": fn_name, "args": parsed_args}})

                finish_reason = choice.get("finish_reason")
                if finish_reason == "tool_calls" and stream_state is not None:
                    buffered_calls = stream_state.pop("tool_calls", {})
                    for idx in sorted(buffered_calls.keys()):
                        b_call = buffered_calls[idx]
                        b_name = b_call.get("name", "")
                        b_args_raw = b_call.get("arguments", "{}")
                        if not b_name:
                            continue
                        try:
                            b_args = json.loads(b_args_raw) if b_args_raw else {}
                        except Exception:
                            b_args = {"raw": b_args_raw}
                        parts.append({"functionCall": {"name": b_name, "args": b_args}})

                gemini_candidate: dict[str, Any] = {}
                if parts:
                    gemini_candidate["content"] = {"role": "model", "parts": parts}
                if finish_reason:
                    gemini_candidate["finishReason"] = (
                        "STOP" if finish_reason in ("stop", "tool_calls") else "MAX_TOKENS"
                    )

                if gemini_candidate:
                    gemini_payload = {"candidates": [gemini_candidate]}
                    if usage_metadata:
                        gemini_payload["usageMetadata"] = usage_metadata
                        usage_metadata = None
                    output_lines.append(f"data: {json.dumps(gemini_payload)}")
                elif usage_metadata:
                    output_lines.append(f"data: {json.dumps({'usageMetadata': usage_metadata})}")
                    usage_metadata = None

    if not output_lines:
        return ""
    return "\n\n".join(output_lines) + "\n\n"


def render_dashboard_html() -> str:
    """Renders the self-contained HTML/CSS/JS dashboard for /holon/ (Bean 0043)."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Holon Coherence — Live Optimization Dashboard</title>
  <style>
    :root {
      --bg: #0b0f17;
      --card-bg: #151d2a;
      --card-border: #243044;
      --text-main: #f1f5f9;
      --text-muted: #94a3b8;
      --accent-emerald: #10b981;
      --accent-blue: #3b82f6;
      --accent-indigo: #6366f1;
      --accent-amber: #f59e0b;
      --danger: #ef4444;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg);
      color: var(--text-main);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      padding: 24px;
      line-height: 1.5;
    }
    .container {
      max-width: 1100px;
      margin: 0 auto;
    }
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 24px;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--card-border);
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .brand h1 {
      font-size: 1.5rem;
      font-weight: 700;
      letter-spacing: -0.02em;
    }
    .badge {
      font-size: 0.75rem;
      padding: 4px 10px;
      border-radius: 9999px;
      background: rgba(16, 185, 129, 0.15);
      color: var(--accent-emerald);
      border: 1px solid rgba(16, 185, 129, 0.3);
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .badge.disconnected {
      background: rgba(239, 68, 68, 0.15);
      color: var(--danger);
      border-color: rgba(239, 68, 68, 0.3);
    }
    .pulse-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: currentColor;
    }
    .controls {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    button {
      background: #1e293b;
      color: var(--text-main);
      border: 1px solid var(--card-border);
      padding: 8px 14px;
      border-radius: 6px;
      font-size: 0.85rem;
      cursor: pointer;
      font-weight: 500;
      transition: background 0.15s, border-color 0.15s;
    }
    button:hover {
      background: #334155;
      border-color: #475569;
    }
    button.primary {
      background: #2563eb;
      border-color: #3b82f6;
    }
    button.primary:hover {
      background: #1d4ed8;
    }
    .metrics-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 18px;
      margin-bottom: 24px;
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 20px;
      display: flex;
      flex-direction: column;
      position: relative;
      overflow: hidden;
    }
    .card-title {
      font-size: 0.85rem;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 8px;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .card-val {
      font-size: 2.2rem;
      font-weight: 700;
      letter-spacing: -0.03em;
      margin-bottom: 4px;
    }
    .card-val.emerald { color: var(--accent-emerald); }
    .card-val.blue { color: var(--accent-blue); }
    .card-val.indigo { color: var(--accent-indigo); }
    .card-val.amber { color: var(--accent-amber); }
    .card-desc {
      font-size: 0.8rem;
      color: var(--text-muted);
      margin-top: auto;
    }
    .details-table-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 24px;
    }
    .details-table-card h2 {
      font-size: 1.1rem;
      font-weight: 600;
      margin-bottom: 16px;
      border-bottom: 1px solid var(--card-border);
      padding-bottom: 12px;
    }
    .details-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 16px;
    }
    .detail-item {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    .detail-label {
      font-size: 0.8rem;
      color: var(--text-muted);
    }
    .detail-value {
      font-size: 1.15rem;
      font-weight: 600;
    }
    footer {
      margin-top: 24px;
      text-align: center;
      font-size: 0.75rem;
      color: var(--text-muted);
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="brand">
        <h1>Holon Coherence</h1>
        <span id="status-badge" class="badge">
          <span class="pulse-dot"></span>
          <span id="status-text">Connected</span>
        </span>
      </div>
      <div class="controls">
        <span id="last-updated" style="font-size: 0.8rem; color: var(--text-muted);">Updating...</span>
        <button id="toggle-refresh" onclick="toggleAutoRefresh()">Pause</button>
        <button class="primary" onclick="fetchMetrics()">Refresh Now</button>
      </div>
    </header>

    <div class="metrics-grid">
      <div class="card">
        <div class="card-title">🔧 Tool Calls Pruned</div>
        <div id="tool-calls-pruned" class="card-val emerald">0</div>
        <div class="card-desc">Redundant tool outputs omitted from context</div>
      </div>
      <div class="card">
        <div class="card-title">⚡ Tokens Reduced</div>
        <div id="tokens-reduced" class="card-val blue">0</div>
        <div class="card-desc">Estimated prompt tokens saved via compression</div>
      </div>
      <div class="card">
        <div class="card-title">🎯 Cache Hit Rate</div>
        <div id="cache-hit-rate" class="card-val indigo">0.0%</div>
        <div class="card-desc"><span id="cache-hits">0</span> hits / <span id="total-requests">0</span> requests</div>
      </div>
      <div class="card">
        <div class="card-title">⏱️ Latency & Throughput</div>
        <div id="avg-ttft" class="card-val amber">0.0 ms</div>
        <div class="card-desc">
          Prefill: <span id="prefill-tps">0.0</span> t/s (latest: <span id="latest-prefill-tps">0.0</span>) |
          Decode: <span id="decode-tps">0.0</span> t/s (latest: <span id="latest-decode-tps">0.0</span>)
        </div>
      </div>
    </div>

    <div class="details-table-card">
      <h2>Cumulative Telemetry Summary</h2>
      <div class="details-grid">
        <div class="detail-item">
          <span class="detail-label">Total Conversation Turns</span>
          <span id="total-turns" class="detail-value">0</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Upstream Cache Misses</span>
          <span id="cache-misses" class="detail-value">0</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Prefill Throughput (Avg)</span>
          <span id="avg-prefill-val" class="detail-value">0.0 tok/s</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Tail Prefill Throughput</span>
          <span id="tail-prefill-val" class="detail-value">0.0 tok/s</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Decode Samples (streaming only)</span>
          <span id="decode-samples" class="detail-value">0</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Total Input Tokens</span>
          <span id="total-input-tokens" class="detail-value">0</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Total Output Tokens</span>
          <span id="total-output-tokens" class="detail-value">0</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Cache Read Tokens</span>
          <span id="total-cache-read-tokens" class="detail-value">0</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Provider KV Cache Hit Rate</span>
          <span id="provider-cache-hit-rate" class="detail-value">0.0%</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Provider Cache Creation Tokens</span>
          <span id="cache-creation-tokens" class="detail-value">0</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Reasoning Tokens</span>
          <span id="reasoning-tokens" class="detail-value">0</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Raw Characters Saved</span>
          <span id="chars-saved" class="detail-value">0</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Turns Summarized</span>
          <span id="turns-summarized" class="detail-value">0</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Cache Control Breakpoints</span>
          <span id="cache-control-injected" class="detail-value">0</span>
        </div>
      </div>
    </div>

    <footer>
      Holon Coherence Optimization Gateway &bull; Live In-Memory Telemetry &bull; Polling /holon/api/metrics
    </footer>
  </div>

  <script>
    let isAutoRefreshing = true;
    let refreshInterval = null;

    function formatNumber(num) {
      if (num === null || num === undefined) return "0";
      return Number(num).toLocaleString();
    }

    async function fetchMetrics() {
      try {
        const resp = await fetch("/holon/api/metrics", { cache: "no-store" });
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        const data = await resp.json();

        document.getElementById("tool-calls-pruned").textContent = formatNumber(data.tool_calls_pruned);
        document.getElementById("tokens-reduced").textContent = formatNumber(data.tokens_reduced);
        document.getElementById("cache-hit-rate").textContent = ((data.cache_hit_rate || 0) * 100).toFixed(1) + "%";
        document.getElementById("cache-hits").textContent = formatNumber(data.cache_hits);
        document.getElementById("total-requests").textContent = formatNumber(data.total_requests);

        const hasTtft = data.avg_ttft_ms !== null && data.avg_ttft_ms !== undefined;
        const avgTtft = hasTtft ? data.avg_ttft_ms.toFixed(1) : "0.0";
        document.getElementById("avg-ttft").textContent = avgTtft + " ms";
        document.getElementById("decode-tps").textContent = (data.avg_decode_throughput_tps || 0).toFixed(1);
        document.getElementById("latest-decode-tps").textContent = (data.latest_decode_throughput_tps || 0).toFixed(1);
        document.getElementById("decode-samples").textContent = formatNumber(data.decode_samples);

        const prefillTps = (data.avg_prefill_throughput_tps || 0).toFixed(1);
        const latestPrefill = (data.latest_prefill_tps || 0).toFixed(1);
        const tailPrefill = (data.avg_tail_prefill_tps || 0).toFixed(1);
        document.getElementById("prefill-tps").textContent = prefillTps;
        document.getElementById("latest-prefill-tps").textContent = latestPrefill;
        document.getElementById("avg-prefill-val").textContent = prefillTps + " tok/s";
        document.getElementById("tail-prefill-val").textContent = tailPrefill + " tok/s";
        const kvHitPct = ((data.provider_cache_hit_rate || 0) * 100).toFixed(1);
        document.getElementById("provider-cache-hit-rate").textContent = kvHitPct + "%";
        document.getElementById("cache-creation-tokens").textContent = formatNumber(data.total_cache_creation_tokens);
        document.getElementById("reasoning-tokens").textContent = formatNumber(data.total_reasoning_tokens);

        document.getElementById("total-turns").textContent = formatNumber(data.total_turns);
        document.getElementById("cache-misses").textContent = formatNumber(data.cache_misses);
        document.getElementById("total-input-tokens").textContent = formatNumber(data.total_input_tokens);
        document.getElementById("total-output-tokens").textContent = formatNumber(data.total_output_tokens);
        document.getElementById("total-cache-read-tokens").textContent = formatNumber(data.total_cache_read_tokens);
        document.getElementById("chars-saved").textContent = formatNumber(data.chars_saved);
        document.getElementById("turns-summarized").textContent = formatNumber(data.turns_summarized);
        document.getElementById("cache-control-injected").textContent = formatNumber(data.cache_control_injected);

        document.getElementById("status-badge").className = "badge";
        document.getElementById("status-text").textContent = "Connected";
        document.getElementById("last-updated").textContent = "Updated " + new Date().toLocaleTimeString();
      } catch (err) {
        document.getElementById("status-badge").className = "badge disconnected";
        document.getElementById("status-text").textContent = "Disconnected";
        document.getElementById("last-updated").textContent = "Update failed: " + err.message;
      }
    }

    function toggleAutoRefresh() {
      isAutoRefreshing = !isAutoRefreshing;
      const btn = document.getElementById("toggle-refresh");
      if (isAutoRefreshing) {
        btn.textContent = "Pause";
        startPolling();
      } else {
        btn.textContent = "Resume";
        stopPolling();
      }
    }

    function startPolling() {
      if (refreshInterval) clearInterval(refreshInterval);
      fetchMetrics();
      refreshInterval = setInterval(fetchMetrics, 2000);
    }

    function stopPolling() {
      if (refreshInterval) {
        clearInterval(refreshInterval);
        refreshInterval = null;
      }
    }

    startPolling();
  </script>
</body>
</html>
"""


class MITMProxyInterceptor:
    """Interceptor for LLM requests that performs context cleaning,
    deduplication, prompt cache optimization, and local response caching.
    """

    def __init__(self, cache_dir: str | None = None, enable_caching: bool = True):
        self.cleaner = JSONContextCleaner()
        self.cache_dir = cache_dir or os.getenv("CACHE_DIR", os.path.expanduser("~/.holon/cache"))
        self.enable_caching = enable_caching
        self._cache_store: HybridCacheStore | None = None

    @property
    def cache_store(self) -> HybridCacheStore:
        if self._cache_store is None:
            self._cache_store = HybridCacheStore(cache_dir=self.cache_dir)
        return self._cache_store

    def detect_provider(self, url_or_path: str, payload: dict[str, Any] | None = None) -> str:
        """Determines the provider protocol family (anthropic, openai, gemini)
        based on target URL, path, or payload structure.
        """
        url_lower = url_or_path.lower()
        parse_target = url_lower if "://" in url_lower else f"https://{url_lower}"
        parsed = urlparse(parse_target)
        hostname = parsed.hostname or url_lower

        if "anthropic" in url_lower or "v1/messages" in url_lower:
            return "anthropic"
        if (
            hostname == "generativelanguage.googleapis.com"
            or hostname.endswith(".generativelanguage.googleapis.com")
            or "gemini" in url_lower
            or "generatecontent" in url_lower
            or "streamgeneratecontent" in url_lower
        ):
            return "gemini"

        openai_providers = [
            "openai",
            "openrouter",
            "deepseek",
            "groq",
            "together",
            "mistral",
            "fireworks",
            "ollama",
            "vllm",
            "lmstudio",
            "chat/completions",
            "v1/completions",
        ]
        if any(p in url_lower for p in openai_providers):
            return "openai"

        if payload and isinstance(payload, dict):
            if "anthropic-version" in payload or "anthropic_version" in payload:
                return "anthropic"
            if "contents" in payload:
                return "gemini"
            if "messages" in payload or "prompt" in payload:
                return "openai"
            if "system" in payload:
                return "anthropic"

        return "unknown"

    def intercept_request_with_stats(
        self, endpoint: str, request_json: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any] | None, CleaningResult | None]:
        """Intercepts and optimizes an outgoing JSON API request payload, returning per-request stats cleanly.

        Tuple Return Design:
            1. First Element (cleaned_request_json): The cleaned request body (with deduplicated tool
               outputs and cache control breakpoints).
            2. Second Element (cached_response_or_none): The pre-cached LLM response payload served from the
               local SQLite database (llm_cache.db), or None on a cache miss.
            3. Third Element (cleaner_result_or_none): The CleaningResult dataclass capturing cleaner metrics,
               or None if provider is unknown.

        Args:
            endpoint: The API endpoint URL or path.
            request_json: Incoming JSON body from agent.

        Returns:
            tuple[dict[str, Any], dict[str, Any] | None, CleaningResult | None]:
                (cleaned_request_json, cached_response_or_none, cleaner_result_or_none)
        """
        # Backward compatibility if intercept_request was overridden on class or monkeypatched on instance
        custom_intercept = getattr(self, "intercept_request", None)
        if custom_intercept is not None:
            func = getattr(custom_intercept, "__func__", custom_intercept)
            if func is not MITMProxyInterceptor.intercept_request:
                cleaned_req, cached_resp = self.intercept_request(endpoint, request_json)
                return cleaned_req, cached_resp, None

        provider = self.detect_provider(endpoint, request_json)
        if provider == "unknown":
            logger.warning("Unknown LLM provider for endpoint: %s. Bypassing payload cleaning.", endpoint)
            return request_json, None, None

        # Step 1: Clean and optimize request payload
        clean_res = self.cleaner.process_payload_with_stats(request_json, provider=provider)
        cleaned_request = clean_res.payload

        # Step 2: Check local cache if enabled (bypassed for streaming requests)
        is_streaming = (
            request_json.get("stream") is True
            or "streamgeneratecontent" in endpoint.lower()
            or "alt=sse" in endpoint.lower()
        )
        if self.enable_caching and not is_streaming:
            try:
                cached_response = self.cache_store.get(cleaned_request, provider=provider)
                if cached_response is not None:
                    logger.info("Serving response from local cache for endpoint %s", endpoint)
                    return cleaned_request, cached_response, clean_res
            except Exception:
                logger.exception("Cache lookup failed for endpoint %s; bypassing cache.", endpoint)

        return cleaned_request, None, clean_res

    def intercept_request(
        self, endpoint: str, request_json: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Intercepts and optimizes an outgoing JSON API request payload (backward-compatible 2-tuple)."""
        cleaned_request, cached_response, _ = self.intercept_request_with_stats(endpoint, request_json)
        return cleaned_request, cached_response

    def intercept_response(
        self,
        endpoint: str,
        request_json: dict[str, Any],
        response_json: dict[str, Any],
        status_code: int = 200,
    ) -> None:
        """Records an LLM response into the local cache.

        Args:
            endpoint: The API endpoint URL or path.
            request_json: Cleaned request JSON payload.
            response_json: Received response JSON from provider API.
            status_code: HTTP status code of the response.
        """
        if not self.enable_caching:
            return

        if (
            request_json.get("stream") is True
            or "streamgeneratecontent" in endpoint.lower()
            or "alt=sse" in endpoint.lower()
        ):
            return

        if status_code != 200:
            logger.warning("Skipping cache put for non-200 HTTP status code (%d) on %s", status_code, endpoint)
            return

        if isinstance(response_json, dict) and ("error" in response_json or response_json.get("type") == "error"):
            logger.warning("Skipping cache put for API error response payload on %s", endpoint)
            return

        provider = self.detect_provider(endpoint, request_json)
        if provider != "unknown":
            try:
                self.cache_store.put(request_json, response_json, provider=provider)
            except Exception:
                logger.exception("Cache store put failed for endpoint %s.", endpoint)


def log_telemetry(msg: str) -> None:
    """Logs telemetry message to mitmproxy console context if available, falling back to standard logger."""
    if ctx and hasattr(ctx, "log") and hasattr(ctx.log, "info"):
        try:
            ctx.log.info(msg)
            return
        except Exception:
            # mitmproxy context is unavailable or inactive in this execution context
            pass

    logger.info(msg)


# mitmproxy addon entrypoint compatible function
class MitmproxyAddon:
    """Addon for mitmproxy command line tool."""

    def __init__(self, cache_dir: str | None = None, wire_log_dir: str | None = None):
        self.interceptor = MITMProxyInterceptor(cache_dir=cache_dir)
        self.wire_log_dir = wire_log_dir or os.getenv("WIRE_LOG_DIR", WIRE_LOG_DIR)
        self.total_requests = 0
        self.cache_hits = 0
        self.metrics = CumulativeMetrics()
        self.default_passive: bool = is_passive_monitoring()
        self._gateway_ip: str | None = None
        self._warned_gateway = False

    def done(self) -> None:
        """Called when mitmproxy is shutting down to flush in-flight logs."""
        shutdown_wire_logs(wait=True, timeout=5.0)

    def _proxy_own_ports(self) -> tuple[int, ...]:
        """Ports the proxy itself listens on, which must never be rewritten onto the gateway.

        Rewriting them would dial the proxy's own published mapping and loop. In container mode,
        dialing the host gateway reaches the host, so only the host-published port
        (HOLON_PROXY_PORT, defaulting to DEFAULT_PROXY_LISTEN_PORT) constitutes a self-loop hazard.
        Internal container listen ports (e.g. 8080 inside the container) must not be treated as
        host-published ports.
        """
        ports: list[int] = []
        env_port = os.getenv("HOLON_PROXY_PORT")
        if env_port:
            with contextlib.suppress(ValueError):
                parsed = int(env_port)
                if 1 <= parsed <= 65535:
                    ports.append(parsed)

        if in_container():
            return tuple(dict.fromkeys(ports)) or (DEFAULT_PROXY_LISTEN_PORT,)

        with contextlib.suppress(Exception):
            if ctx is not None and getattr(ctx, "options", None) is not None:
                for name in ("listen_port", "web_port"):
                    value = getattr(ctx.options, name, None)
                    if isinstance(value, int) and value > 0:
                        ports.append(value)
        return tuple(dict.fromkeys(ports)) or (DEFAULT_PROXY_LISTEN_PORT,)

    def _resolve_gateway(self) -> str | None:
        """Resolve the Docker host gateway and cache successful resolutions.

        If resolution fails (e.g. transient container DNS hiccup), do not permanently
        latch None so subsequent requests can retry.
        """
        if self._gateway_ip is not None:
            return self._gateway_ip
        ip = resolve_gateway_address()
        if ip is not None:
            self._gateway_ip = ip
        return ip

    def server_connect(self, data: Any) -> None:
        """Route host-local LLM endpoints through the Docker host gateway.

        Inside the container ``localhost`` / ``127.0.0.1`` resolve to the container itself
        and the host's LAN address is unroutable from the Docker Desktop VM, so a
        request the agent addressed at its own machine (Ollama, vMLX, LM Studio, vLLM)
        would die with 502 or a timeout. Only loopback and authorities explicitly declared
        via ``HOLON_HOST_LOCAL_HOSTS`` are rewritten; anything else is left alone so a
        genuinely remote peer on the LAN is never hijacked onto the host.

        Rewriting the dial address leaves ``flow.request`` -- and therefore the wire logs
        and token telemetry -- reporting the authority the agent actually asked for.
        """
        if not in_container():
            return
        targets = targets_from_env()
        if not targets:
            return

        server = getattr(data, "server", None)
        address = getattr(server, "address", None) if server is not None else None
        original = tuple(address) if address else None

        decision = rewrite_connection(data, targets, self._resolve_gateway(), self._proxy_own_ports())
        if decision.should_rewrite and decision.address is not None and original:
            log_telemetry(
                f"holon: host-local endpoint {original[0]}:{original[1]} -> "
                f"{decision.address[0]}:{decision.address[1]} ({GATEWAY_HOSTNAME}, {decision.reason})"
            )
            return

        if decision.reason == "proxy-own-port":
            if original:
                log_telemetry(
                    f"holon: BLOCKED connection to proxy's own port {original[0]}:{original[1]} "
                    "to prevent self-loop dialing"
                )
            server = getattr(data, "server", None)
            if server is not None and hasattr(server, "error"):
                server.error = "Connection to proxy's own port blocked"
            return

        if decision.reason == "gateway-unresolved" and not self._warned_gateway:
            self._warned_gateway = True
            log_telemetry(
                "holon: WARNING host-local LLM traffic needs the Docker host gateway, but "
                f"'{GATEWAY_HOSTNAME}' does not resolve inside this container. Restart the proxy so it is "
                "created with --add-host=host.docker.internal:host-gateway (Linux), or bind the model "
                "server to a non-loopback interface."
            )

    def _dump_flow_transaction(
        self,
        flow: Any,
        resp_data: Any,
        status_code: int = 200,
        is_hit: bool = False,
        is_sse: bool = False,
        ttft: float | None = None,
        total_time: float | None = None,
        prefill_tps: float | None = None,
        tail_prefill_tps: float | None = None,
        decode_tps: float | None = None,
        generation_time: float | None = None,
    ) -> None:
        if not is_wire_logging_enabled():
            return
        try:
            url = getattr(flow.request, "pretty_url", "")
            flow_headers = getattr(flow.request, "headers", {})
            provider = getattr(flow, "provider", "unknown")

            # IDs and Role
            flow_id = getattr(flow, "id", None) or f"flow_{uuid.uuid4().hex[:8]}"
            agent_id = get_header_case_insensitive(flow_headers, "x-holon-agent-id") or os.getenv(
                "HOLON_AGENT_ID", "agy"
            )
            agent_role = get_header_case_insensitive(flow_headers, "x-holon-agent-role") or os.getenv(
                "HOLON_ROLE", "executor"
            )

            raw_req = getattr(flow, "raw_request_data", None) or getattr(flow, "req_data", None) or {}
            cleaned_req = getattr(flow, "req_data", None) or raw_req
            turn_id = derive_turn_id(flow_headers, raw_req, self.total_requests)

            clean_res = getattr(flow, "cleaner_result", None)
            try:
                raw_chars = len(json.dumps(raw_req)) if raw_req else 0
                cleaned_chars = len(json.dumps(cleaned_req)) if cleaned_req else 0
            except Exception:
                raw_chars = 0
                cleaned_chars = 0
            chars_saved = max(0, raw_chars - cleaned_chars)
            delta = {
                "raw_chars": raw_chars,
                "cleaned_chars": cleaned_chars,
                "chars_saved": clean_res.chars_saved if clean_res else chars_saved,
                "tool_outputs_omitted": clean_res.tool_outputs_omitted if clean_res else 0,
                "turns_summarized": clean_res.turns_summarized if clean_res else 0,
                "cache_control_injected": clean_res.cache_control_injected if clean_res else 0,
            }

            # Token metrics extraction
            if is_hit:
                detailed_tokens = extract_detailed_token_counts(raw_req, resp_data, provider)
                detailed_tokens["cache_read_input_tokens"] = detailed_tokens["input_tokens"]
            else:
                detailed_tokens = extract_detailed_token_counts(cleaned_req, resp_data, provider)

            # Content extraction
            if is_sse:
                content_val = extract_sse_content(resp_data, provider)
            elif isinstance(resp_data, dict):
                content_val = resp_data
            else:
                content_val = str(resp_data)

            record = {
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
                "mode": (
                    "baseline"
                    if is_flow_passive(flow, default_passive=getattr(self, "default_passive", None))
                    else "optimized"
                ),
                "cache_action": "HIT" if is_hit else "MISS",
                "response": {
                    "status": status_code,
                    "usage": {
                        "input_tokens": detailed_tokens["input_tokens"],
                        "cache_creation_input_tokens": detailed_tokens["cache_creation_input_tokens"],
                        "cache_read_input_tokens": detailed_tokens["cache_read_input_tokens"],
                        "output_tokens": detailed_tokens["output_tokens"],
                        "reasoning_tokens": detailed_tokens["reasoning_tokens"],
                    },
                    "content": scrub_payload(content_val),
                },
                "timing": {
                    "ttft_ms": round(ttft * 1000, 2) if ttft is not None else (0.0 if is_hit else None),
                    "total_ms": round(total_time * 1000, 2) if total_time is not None else 0.0,
                    "streaming": bool(is_sse),
                    "generation_ms": round(generation_time * 1000, 2) if generation_time is not None else None,
                    "prefill_tps": round(prefill_tps, 2) if prefill_tps is not None else None,
                    "tail_prefill_tps": round(tail_prefill_tps, 2) if tail_prefill_tps is not None else None,
                    "decode_tps": round(decode_tps, 2) if decode_tps is not None else None,
                },
            }

            dump_wire_transaction(record, self.wire_log_dir)
        except Exception as exc:
            logger.debug("Failed to record flow wire transaction: %s", exc)

    def request(self, flow: Any) -> None:
        """Mitmproxy request callback."""
        if getattr(flow, "request", None) is None:
            return
        url = getattr(flow.request, "pretty_url", "")
        raw_path = getattr(flow.request, "path", "") or urlparse(url if "://" in url else f"http://{url}").path
        path_clean = raw_path.split("?")[0].rstrip("/")
        method = (getattr(flow.request, "method", "") or "GET").upper()

        # Intercept metrics endpoint: GET /holon/api/metrics or /_holon/metrics
        if method == "GET" and path_clean in ("/holon/api/metrics", "/_holon/metrics"):
            metrics_bytes = json.dumps(self.metrics.to_dict(), indent=2).encode("utf-8")
            flow.response = _make_http_response(
                flow,
                200,
                metrics_bytes,
                {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
            )
            return

        # Intercept mode control endpoint: POST /holon/api/mode or GET /holon/api/mode
        if path_clean in ("/holon/api/mode", "/_holon/mode"):
            if method == "POST":
                try:
                    mode_data = json.loads(flow.request.get_text() or "{}")
                    new_mode = str(mode_data.get("mode", "")).lower().strip()
                    if new_mode in ("baseline", "passive"):
                        self.default_passive = True
                    elif new_mode in ("optimized", "active"):
                        self.default_passive = False
                    if mode_data.get("wire_log_dir"):
                        self.wire_log_dir = str(mode_data["wire_log_dir"])
                    resp_bytes = json.dumps(
                        {
                            "status": "ok",
                            "mode": "baseline" if getattr(self, "default_passive", False) else "optimized",
                            "wire_log_dir": self.wire_log_dir,
                        }
                    ).encode("utf-8")
                    flow.response = _make_http_response(flow, 200, resp_bytes, {"Content-Type": "application/json"})
                    return
                except Exception as exc:
                    flow.response = _make_http_response(
                        flow,
                        400,
                        json.dumps({"error": str(exc)}).encode("utf-8"),
                        {"Content-Type": "application/json"},
                    )
                    return
            elif method == "GET":
                current_mode = (
                    "baseline" if getattr(self, "default_passive", False) or is_passive_monitoring() else "optimized"
                )
                resp_bytes = json.dumps({"mode": current_mode, "wire_log_dir": self.wire_log_dir}).encode("utf-8")
                flow.response = _make_http_response(flow, 200, resp_bytes, {"Content-Type": "application/json"})
                return

        # Intercept web dashboard: GET /holon/ or /holon
        if method == "GET" and path_clean == "/holon":
            dashboard_bytes = render_dashboard_html().encode("utf-8")
            flow.response = _make_http_response(
                flow,
                200,
                dashboard_bytes,
                {"Content-Type": "text/html; charset=utf-8"},
            )
            return

        # Reverse proxy rewrite if agent addresses the proxy's own port directly
        req_host = (getattr(flow.request, "pretty_host", "") or getattr(flow.request, "host", "")).lower()
        req_port = getattr(flow.request, "port", None)
        if (
            req_host in ("127.0.0.1", "localhost", "127.0.0.1.nip.io", "localhost.nip.io")
            and req_port in self._proxy_own_ports()
        ):
            targets = targets_from_env()
            if targets:
                target = targets[0]
                if in_container():
                    flow.request.host = GATEWAY_HOSTNAME
                else:
                    flow.request.host = target.host
                if target.port:
                    flow.request.port = target.port
                flow.request.scheme = "http"
                url = getattr(flow.request, "pretty_url", "")

        data = None
        try:
            content = flow.request.get_text()
            if content:
                data = json.loads(content)
        except Exception as exc:
            # Request body is non-JSON or unparseable; proceed with URL-based provider detection
            logger.debug("Non-JSON or unparseable request body for endpoint %s: %s", url, exc)

        provider = self.interceptor.detect_provider(url, data)
        if provider != "unknown":
            flow.provider = provider
            flow.request_start_time = time.perf_counter()  # float: timestamp from time.perf_counter()
            self.total_requests += 1
            self.metrics.record_request()
            is_local = is_local_target(flow)

            # Bean 0051: Gemini v1beta bridge to OpenAI /v1/chat/completions for host-local engines
            if provider == "gemini" and is_local and data is not None:
                flow.is_gemini_bridged = True
                target_model = os.getenv("AGY_MODEL") or os.getenv("HOLON_LOCAL_MODEL")
                if not target_model:
                    path_or_url = getattr(flow.request, "path", "") or url
                    match = re.search(r"/models/([^/:]+)", path_or_url)
                    if match:
                        target_model = match.group(1)
                data = translate_gemini_to_openai_request(data, model=target_model or "default")
                flow.request.path = "/v1/chat/completions"
                if ":streamgeneratecontent" in url.lower() or "alt=sse" in url.lower():
                    data["stream"] = True
                flow.request.set_text(json.dumps(data))

            # Bean 0051: Strict Anthropic normalizer for host-local engines
            if provider == "anthropic" and is_local and data is not None:
                data, _ = normalize_anthropic_request(flow, data, is_local=True)
                flow.request.set_text(json.dumps(data))

            try:
                if data is not None:
                    flow.raw_request_data = copy.deepcopy(data)
                    if is_flow_passive(flow, default_passive=getattr(self, "default_passive", None)):
                        # Passive mode: bypass cleaning and cache lookup, preserving raw payload for baseline logging
                        flow.cleaner_result = None
                        flow.req_data = data
                    else:
                        if hasattr(self.interceptor, "intercept_request_with_stats"):
                            cleaned_data, cached_resp, clean_res = self.interceptor.intercept_request_with_stats(
                                url, data
                            )
                        else:
                            cleaned_data, cached_resp = self.interceptor.intercept_request(url, data)
                            clean_res = None

                        if is_local and clean_res:
                            clean_res.cache_control_injected = 0
                            if isinstance(cleaned_data, dict):
                                cleaned_data, _ = normalize_anthropic_request(flow, cleaned_data, is_local=True)

                        flow.cleaner_result = clean_res
                        flow.req_data = cleaned_data
                        flow.request.set_text(json.dumps(cleaned_data))

                        if clean_res:
                            self.metrics.record_cleaner(clean_res)
                            if (
                                clean_res.chars_saved > 0
                                or clean_res.tool_outputs_omitted > 0
                                or clean_res.turns_summarized > 0
                                or clean_res.cache_control_injected > 0
                            ):
                                cleaner_log = (
                                    f"🧹 [CLEANER_METRICS] Chars Saved: {clean_res.chars_saved} | "
                                    f"Tool Outputs Omitted: {clean_res.tool_outputs_omitted} | "
                                    f"Turns Summarized: {clean_res.turns_summarized} | "
                                    f"Cache Control Injected: {clean_res.cache_control_injected}"
                                )
                                log_telemetry(cleaner_log)

                        if cached_resp:
                            self.cache_hits += 1
                            self.metrics.record_cache_hit()
                            flow.is_cached = True

                            headers = {"Content-Type": "application/json"}
                            response_cls = (
                                getattr(http, "Response", None)
                                or getattr(flow, "Response", None)
                                or globals().get("Response")
                            )
                            if response_cls and hasattr(response_cls, "make"):
                                flow.response = response_cls.make(200, json.dumps(cached_resp).encode("utf-8"), headers)

                            # Inject telemetry headers on cache hit
                            hit_rate = self.cache_hits / self.total_requests if self.total_requests > 0 else 0.0
                            if (
                                getattr(flow, "response", None) is not None
                                and hasattr(flow.response, "headers")
                                and flow.response.headers is not None
                                and hasattr(flow.response.headers, "__setitem__")
                            ):
                                flow.response.headers["X-Holon-Cache-Hit-Rate"] = f"{hit_rate:.4f}"
                                flow.response.headers["X-Holon-TTFT-Ms"] = "0.00"
                                flow.response.headers["X-Holon-Prefill-TPS"] = "0.0000"
                                flow.response.headers["X-Holon-Tail-Prefill-TPS"] = "0.0000"
                                flow.response.headers["X-Holon-Decode-Time-Sec"] = "0.000"
                                flow.response.headers["X-Holon-Output-TPS"] = "0.0000"
                                flow.response.headers["X-Holon-Total-Time-Ms"] = "0.00"

                            log_msg = (
                                f"📊 [TELEMETRY] Provider: {provider.upper()} | "
                                f"Cache: HIT (Hit Rate: {hit_rate * 100:.1f}%) | "
                                f"TTFT: 0.00ms | Prefill: 0.00 t/s | Output: 0.00 t/s | "
                                f"Total: 0.00ms"
                            )
                            log_telemetry(log_msg)

                            # Dump wire transaction for cache hit
                            self._dump_flow_transaction(flow, resp_data=cached_resp, status_code=200, is_hit=True)
            except json.JSONDecodeError as exc:
                logger.debug("Non-JSON request body for endpoint %s: %s", url, exc)
            except Exception:
                logger.exception("Mitmproxy request intercept error for endpoint: %s", url)

    def responseheaders(self, flow: Any) -> None:
        """Mitmproxy response headers callback."""
        if getattr(flow, "provider", "unknown") != "unknown":
            flow.response_headers_time = time.perf_counter()  # float: timestamp from time.perf_counter()
            flow.first_chunk_time = None
            response = getattr(flow, "response", None)
            if response is not None:
                headers = getattr(response, "headers", None)
                content_type = ""
                if headers:
                    if hasattr(headers, "get"):
                        content_type = headers.get("Content-Type") or headers.get("content-type") or ""
                    elif isinstance(headers, dict):
                        for k, v in headers.items():
                            if k.lower() == "content-type":
                                content_type = v
                                break
                if "text/event-stream" in content_type.lower():
                    flow.sse_chunks = []
                    flow.sse_bytes = 0
                    flow._sse_stream_state = {}
                    existing_stream = getattr(response, "stream", None)

                    def sse_stream_wrapper(chunk: bytes) -> bytes:
                        if chunk:
                            if getattr(flow, "first_chunk_time", None) is None:
                                flow.first_chunk_time = time.perf_counter()
                            flow.last_chunk_time = time.perf_counter()
                            if getattr(flow, "is_gemini_bridged", False):
                                try:
                                    chunk_text = chunk.decode("utf-8", errors="ignore")
                                    translated = translate_openai_sse_chunk_to_gemini(
                                        chunk_text,
                                        stream_state=getattr(flow, "_sse_stream_state", None),
                                    )
                                    chunk = translated.encode("utf-8")
                                except Exception as exc:
                                    logger.debug("Failed translating bridged Gemini SSE chunk: %s", exc)
                            flow.sse_bytes = getattr(flow, "sse_bytes", 0) + len(chunk)
                            if flow.sse_bytes <= _MAX_SSE_BUFFER_BYTES:
                                flow.sse_chunks.append(chunk)
                        if callable(existing_stream):
                            return existing_stream(chunk)
                        return chunk

                    response.stream = sse_stream_wrapper

    def response(self, flow: Any) -> None:
        """Mitmproxy response callback."""
        if getattr(flow, "request", None) is None or getattr(flow, "response", None) is None:
            return

        url = getattr(flow.request, "pretty_url", "")
        status_code = getattr(flow.response, "status_code", 200)

        provider = getattr(flow, "provider", "unknown")
        if provider == "unknown" or getattr(flow, "is_cached", False):
            return

        if status_code == 200:
            try:
                req_data = getattr(flow, "req_data", None)
                if req_data is None:
                    req_text = flow.request.get_text()
                    if req_text:
                        req_data = json.loads(req_text)

                sse_chunks = getattr(flow, "sse_chunks", None)
                is_sse = sse_chunks is not None

                if is_sse:
                    resp_data = b"".join(sse_chunks).decode("utf-8", errors="ignore")
                else:
                    resp_text = flow.response.get_text()
                    resp_data = json.loads(resp_text) if resp_text else None
                    if getattr(flow, "is_gemini_bridged", False) and isinstance(resp_data, dict):
                        try:
                            gemini_data = translate_openai_to_gemini_response(resp_data)
                            flow.response.set_text(json.dumps(gemini_data))
                            resp_data = gemini_data
                        except Exception as exc:
                            logger.debug("Failed translating bridged Gemini response: %s", exc)

                if req_data is not None and resp_data:
                    # Note: Response caching is explicitly bypassed for SSE streams (is_sse is True)
                    # because streaming responses cannot be served statically from cache, but telemetry
                    # metrics (token counts, TTFT, TPS) are still calculated and logged.
                    if not is_sse and not is_flow_passive(flow, default_passive=getattr(self, "default_passive", None)):
                        self.interceptor.intercept_response(url, req_data, resp_data, status_code=status_code)

                    # Extract token counts and cache read tokens in a single pass
                    token_counts = extract_token_counts(req_data, resp_data, provider)
                    input_tokens = token_counts[0]
                    output_tokens = token_counts[1]
                    cache_read_tokens = token_counts[2]
                    cache_creation_tokens = getattr(token_counts, "cache_creation_tokens", 0)
                    reasoning_tokens = getattr(token_counts, "reasoning_tokens", 0)

                    # Compute timing from one clock domain; a missing stamp means "not measured"
                    # and must never be replaced by `now`, which is what yielded ttft == 0.0 and the
                    # 0.00 tokens/sec prefill readings (Bean 0097).
                    now = time.perf_counter()
                    timing = resolve_flow_timing(flow, completed_at=now)
                    ttft = timing.ttft_sec
                    total_time = timing.total_sec
                    generation_time = timing.generation_sec

                    uncached_input_tokens = max(0, input_tokens - cache_read_tokens)
                    prefill_tps = compute_prefill_tps(input_tokens, ttft)
                    tail_prefill_tps = compute_tail_prefill_tps(uncached_input_tokens, ttft)
                    output_tps = compute_decode_tps(output_tokens, generation_time, streaming=timing.streaming)
                    hit_rate = self.cache_hits / self.total_requests if self.total_requests > 0 else 0.0

                    # Inject telemetry headers on cache miss
                    if (
                        getattr(flow, "response", None) is not None
                        and hasattr(flow.response, "headers")
                        and flow.response.headers is not None
                        and hasattr(flow.response.headers, "__setitem__")
                    ):
                        flow.response.headers["X-Holon-Cache-Hit-Rate"] = f"{hit_rate:.4f}"
                        flow.response.headers["X-Holon-Streaming"] = "true" if timing.streaming else "false"
                        flow.response.headers["X-Holon-TTFT-Ms"] = (
                            f"{ttft * 1000:.2f}" if ttft is not None else UNMEASURED
                        )
                        flow.response.headers["X-Holon-Prefill-TPS"] = format_rate(prefill_tps, 4)
                        flow.response.headers["X-Holon-Tail-Prefill-TPS"] = format_rate(tail_prefill_tps, 4)
                        flow.response.headers["X-Holon-Decode-Time-Sec"] = (
                            f"{generation_time:.3f}" if generation_time is not None else UNMEASURED
                        )
                        flow.response.headers["X-Holon-Output-TPS"] = format_rate(output_tps, 4)
                        flow.response.headers["X-Holon-Total-Time-Ms"] = (
                            f"{total_time * 1000:.2f}" if total_time is not None else UNMEASURED
                        )

                    ttft_label = f"{ttft * 1000:.1f}ms" if ttft is not None else UNMEASURED
                    total_label = f"{total_time * 1000:.1f}ms" if total_time is not None else UNMEASURED
                    if output_tps is not None and generation_time is not None:
                        output_label = f"{output_tps:.2f} t/s ({output_tokens} tok in {generation_time:.2f}s)"
                    else:
                        output_label = f"n/a [{timing.decode_reason()}] ({output_tokens} tok)"
                    log_msg = (
                        f"📊 [TELEMETRY] Provider: {provider.upper()} | "
                        f"Cache: MISS (Hit Rate: {hit_rate * 100:.1f}%) | "
                        f"TTFT: {ttft_label} | "
                        f"Prefill: {format_rate(prefill_tps)} t/s ({input_tokens} tok) | "
                        f"Output: {output_label} | "
                        f"Total: {total_label}"
                    )
                    log_telemetry(log_msg)

                    # Persist wire transaction dump
                    self._dump_flow_transaction(
                        flow,
                        resp_data=resp_data,
                        status_code=status_code,
                        is_hit=False,
                        is_sse=is_sse,
                        ttft=ttft,
                        total_time=total_time,
                        prefill_tps=prefill_tps,
                        tail_prefill_tps=tail_prefill_tps,
                        decode_tps=output_tps,
                        generation_time=generation_time,
                    )

                    # Update in-memory cumulative optimization metrics
                    self.metrics.record_response(
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        cache_read_tokens=cache_read_tokens,
                        cache_creation_tokens=cache_creation_tokens,
                        reasoning_tokens=reasoning_tokens,
                        ttft=ttft,
                        output_tps=output_tps,
                        prefill_tps=prefill_tps,
                        tail_prefill_tps=tail_prefill_tps,
                        total_time=total_time,
                    )
            except json.JSONDecodeError as exc:
                logger.debug("Non-JSON request/response body for endpoint %s: %s", url, exc)
            except Exception:
                logger.exception("Mitmproxy response intercept error for endpoint: %s", url)
        else:
            logger.warning("Skipping caching response with HTTP status code %d for %s", status_code, url)
            start_t = getattr(flow, "request_start_time", None) or time.perf_counter()
            elapsed_ms = (time.perf_counter() - start_t) * 1000
            log_msg = f"⚠️ [TELEMETRY] Provider: {provider.upper()} | Status: {status_code} | Total: {elapsed_ms:.1f}ms"
            log_telemetry(log_msg)

            try:
                if (
                    getattr(flow, "req_data", None) is None
                    and getattr(flow, "request", None)
                    and hasattr(flow.request, "get_text")
                ):
                    req_text = flow.request.get_text()
                    if req_text:
                        try:
                            flow.req_data = json.loads(req_text)
                        except Exception:
                            flow.req_data = req_text

                resp_data = None
                if getattr(flow, "response", None) and hasattr(flow.response, "get_text"):
                    resp_text = flow.response.get_text()
                    if resp_text:
                        try:
                            resp_data = json.loads(resp_text)
                        except Exception:
                            resp_data = resp_text

                self._dump_flow_transaction(
                    flow,
                    resp_data=resp_data,
                    status_code=status_code,
                    is_hit=False,
                    is_sse=False,
                    ttft=None,
                    total_time=(elapsed_ms / 1000.0),
                )
                self.metrics.record_response(
                    input_tokens=0,
                    output_tokens=0,
                    cache_read_tokens=0,
                    cache_creation_tokens=0,
                    reasoning_tokens=0,
                    ttft=None,
                    output_tps=None,
                    prefill_tps=None,
                    tail_prefill_tps=None,
                )
            except Exception as exc:
                logger.debug("Failed to record non-200 wire transaction: %s", exc)


addons = [MitmproxyAddon()]
