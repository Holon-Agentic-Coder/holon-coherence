"""Core interceptor and mitmproxy addon engine."""

from __future__ import annotations

import contextlib
import logging
import os
import time
from typing import Any
from urllib.parse import urlparse

from holon_coherence.host_local import GATEWAY_HOSTNAME, rewrite_connection, targets_from_env
from holon_coherence.hybrid_cache import HybridCacheStore
from holon_coherence.payload_cleaner import CleaningResult, JSONContextCleaner
from holon_coherence.proxy.metrics import CumulativeMetrics
from holon_coherence.proxy.steps import (
    FAILURE_POLICY,
    REQUEST_GUARDED,
    REQUEST_POLICY,
    REQUEST_PRELUDE,
    RESPONSE_FAILURE,
    RESPONSE_SUCCESS,
    SUCCESS_POLICY,
    Outcome,
    RequestContext,
    ResponseContext,
    log_failure,
    run_guarded,
    run_steps,
)
from holon_coherence.proxy.steps._compat import (
    _get_ctx,
    _get_in_container,
    _get_log_telemetry,
    _get_resolve_gateway_address,
)
from holon_coherence.proxy.steps.sse_tap import _MAX_SSE_BUFFER_BYTES, install_sse_tap, response_content_type
from holon_coherence.proxy.steps.wire_record import WireTransaction, build_wire_record
from holon_coherence.proxy.wire_log import (
    WIRE_LOG_DIR,
    dump_wire_transaction,
    is_passive_monitoring,
    is_wire_logging_enabled,
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

    def _dump_flow_transaction(self, flow: Any, resp_data: Any, status_code: int = 200, **fields: Any) -> None:
        """Queue the scrubbed wire record for one transaction; ``fields`` are ``WireTransaction`` facts."""
        if not is_wire_logging_enabled():
            return
        try:
            record = build_wire_record(self, flow, resp_data, status_code, WireTransaction(**fields))
            dump_wire_transaction(record, self.wire_log_dir)
        except Exception as exc:
            logger.debug("Failed to record flow wire transaction: %s", exc)

    def request(self, flow: Any) -> None:
        """Mitmproxy request callback: run the ordered request pipeline."""
        if getattr(flow, "request", None) is None:
            return
        ctx = RequestContext.from_flow(self, flow)
        if run_steps(REQUEST_PRELUDE, ctx) is Outcome.HALT:
            return
        run_guarded(REQUEST_GUARDED, ctx, REQUEST_POLICY)

    def responseheaders(self, flow: Any) -> None:
        """Mitmproxy response headers callback: stamp timing and tap event streams."""
        if getattr(flow, "provider", "unknown") == "unknown":
            return
        flow.response_headers_time = time.perf_counter()  # float: timestamp from time.perf_counter()
        flow.first_chunk_time = None
        response = getattr(flow, "response", None)
        if response is not None and "text/event-stream" in response_content_type(response).lower():
            install_sse_tap(flow, response)

    def response(self, flow: Any) -> None:
        """Mitmproxy response callback: run the ordered response pipeline."""
        ctx = ResponseContext.from_flow(self, flow)
        if ctx is None:  # no request/response, unknown provider, or served from cache
            return
        if ctx.status_code == 200:
            run_guarded(RESPONSE_SUCCESS, ctx, SUCCESS_POLICY)
        else:
            log_failure(ctx)
            run_guarded(RESPONSE_FAILURE, ctx, FAILURE_POLICY)


addons = [MitmproxyAddon()]
