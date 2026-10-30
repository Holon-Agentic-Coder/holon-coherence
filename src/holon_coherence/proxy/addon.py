"""Core interceptor and mitmproxy addon engine."""

from __future__ import annotations

import contextlib
import copy
import json
import logging
import os
import re
import sys
import time
import uuid
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
    compute_decode_tps,
    compute_prefill_tps,
    compute_tail_prefill_tps,
    format_rate,
)
from holon_coherence.parsers import (
    extract_detailed_token_counts,
    extract_sse_content,
    extract_token_counts,
)
from holon_coherence.payload_cleaner import CleaningResult, JSONContextCleaner
from holon_coherence.proxy.dashboard import render_dashboard_html
from holon_coherence.proxy.metrics import CumulativeMetrics
from holon_coherence.proxy.normalise.anthropic import normalize_anthropic_request
from holon_coherence.proxy.routing import _make_http_response, is_local_target
from holon_coherence.proxy.scrubbing import scrub_headers, scrub_payload, scrub_string
from holon_coherence.proxy.timing import (
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
    dump_wire_transaction,
    is_flow_passive,
    is_passive_monitoring,
    is_wire_logging_enabled,
    log_telemetry,
    shutdown_wire_logs,
)

__all__ = [
    "DEFAULT_PROXY_LISTEN_PORT",
    "_MAX_SSE_BUFFER_BYTES",
    "MITMProxyInterceptor",
    "MitmproxyAddon",
    "addons",
]

logger = logging.getLogger(__name__)

DEFAULT_PROXY_LISTEN_PORT = 8080
_MAX_SSE_BUFFER_BYTES = 50 * 1024 * 1024


def _get_in_container() -> Any:
    mod = sys.modules.get("holon_coherence.mitm_addon")
    if mod is not None and hasattr(mod, "in_container"):
        return mod.in_container
    return in_container


def _get_resolve_gateway_address() -> Any:
    mod = sys.modules.get("holon_coherence.mitm_addon")
    if mod is not None and hasattr(mod, "resolve_gateway_address"):
        return mod.resolve_gateway_address
    return resolve_gateway_address


def _get_log_telemetry() -> Any:
    mod = sys.modules.get("holon_coherence.mitm_addon")
    if mod is not None and hasattr(mod, "log_telemetry"):
        return mod.log_telemetry
    return log_telemetry


def _get_ctx() -> Any:
    mod = sys.modules.get("holon_coherence.mitm_addon")
    if mod is not None and hasattr(mod, "ctx"):
        return mod.ctx
    return ctx


def _get_is_local_target() -> Any:
    mod = sys.modules.get("holon_coherence.mitm_addon")
    if mod is not None and hasattr(mod, "is_local_target"):
        return mod.is_local_target
    return is_local_target


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

    def detect_provider(self, url_or_path: str, payload: dict[str, Any] | None = None) -> str:  # noqa: PLR0911
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

        if _get_in_container()():
            return tuple(dict.fromkeys(ports)) or (DEFAULT_PROXY_LISTEN_PORT,)

        active_ctx = _get_ctx()
        with contextlib.suppress(Exception):
            if active_ctx is not None and getattr(active_ctx, "options", None) is not None:
                for name in ("listen_port", "web_port"):
                    value = getattr(active_ctx.options, name, None)
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
        ip = _get_resolve_gateway_address()()
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
        if not _get_in_container()():
            return
        targets = targets_from_env()
        if not targets:
            return

        server = getattr(data, "server", None)
        address = getattr(server, "address", None) if server is not None else None
        original = tuple(address) if address else None

        decision = rewrite_connection(data, targets, self._resolve_gateway(), self._proxy_own_ports())
        if decision.should_rewrite and decision.address is not None and original:
            _get_log_telemetry()(
                f"holon: host-local endpoint {original[0]}:{original[1]} -> "
                f"{decision.address[0]}:{decision.address[1]} ({GATEWAY_HOSTNAME}, {decision.reason})"
            )
            return

        if decision.reason == "proxy-own-port":
            if original:
                _get_log_telemetry()(
                    f"holon: BLOCKED connection to proxy's own port {original[0]}:{original[1]} "
                    "to prevent self-loop dialing"
                )
            server = getattr(data, "server", None)
            if server is not None and hasattr(server, "error"):
                server.error = "Connection to proxy's own port blocked"
            return

        if decision.reason == "gateway-unresolved" and not self._warned_gateway:
            self._warned_gateway = True
            _get_log_telemetry()(
                "holon: WARNING host-local LLM traffic needs the Docker host gateway, but "
                f"'{GATEWAY_HOSTNAME}' does not resolve inside this container. Restart the proxy so it is "
                "created with --add-host=host.docker.internal:host-gateway (Linux), or bind the model "
                "server to a non-loopback interface."
            )

    def _dump_flow_transaction(  # noqa: PLR0913
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

    def request(self, flow: Any) -> None:  # noqa: C901, PLR0912, PLR0915
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
                if _get_in_container()():
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
            is_local = _get_is_local_target()(flow)

            # Gemini v1beta bridge to OpenAI /v1/chat/completions for host-local engines
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

            # Strict Anthropic normaliser for host-local engines
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
                                _get_log_telemetry()(cleaner_log)

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
                            _get_log_telemetry()(log_msg)

                            # Dump wire transaction for cache hit
                            self._dump_flow_transaction(flow, resp_data=cached_resp, status_code=200, is_hit=True)
            except json.JSONDecodeError as exc:
                logger.debug("Non-JSON request body for endpoint %s: %s", url, exc)
            except Exception:
                logger.exception("Mitmproxy request intercept error for endpoint: %s", url)

    def responseheaders(self, flow: Any) -> None:  # noqa: C901
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
                                    flow._sse_stream_state = getattr(flow, "_sse_stream_state", None)
                                except Exception as exc:
                                    logger.debug("Failed translating bridged Gemini SSE chunk: %s", exc)
                            flow.sse_bytes = getattr(flow, "sse_bytes", 0) + len(chunk)
                            if flow.sse_bytes <= _MAX_SSE_BUFFER_BYTES:
                                flow.sse_chunks.append(chunk)
                        if callable(existing_stream):
                            return existing_stream(chunk)
                        return chunk

                    response.stream = sse_stream_wrapper

    def response(self, flow: Any) -> None:  # noqa: C901, PLR0912, PLR0915
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
                    # 0.00 tokens/sec prefill readings.
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
                    _get_log_telemetry()(log_msg)

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
            _get_log_telemetry()(log_msg)

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
