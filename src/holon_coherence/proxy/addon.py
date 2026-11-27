from __future__ import annotations

import contextlib
import logging
import time
from typing import Any

from holon_coherence.host_local import GATEWAY_HOSTNAME, rewrite_connection, targets_from_env
from holon_coherence.hybrid_cache import HybridCacheStore
from holon_coherence.metrics_math import DEFAULT_WIRE_LOG_DIR
from holon_coherence.payload_cleaner import CleaningResult, JSONContextCleaner
from holon_coherence.providers.registry import UNKNOWN_PROVIDER_NAME, detect_provider_name
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
    dump_wire_transaction,
    is_passive_monitoring,
    is_wire_logging_enabled,
    shutdown_wire_logs,
)
from holon_coherence.settings import CoherenceSettings

__all__ = [
    "DEFAULT_PROXY_LISTEN_PORT",
    "_MAX_SSE_BUFFER_BYTES",
    "MITMProxyInterceptor",
    "MitmproxyAddon",
    "addons",
]

logger = logging.getLogger(__name__)

DEFAULT_PROXY_LISTEN_PORT = 8080
WIRE_LOG_SHUTDOWN_TIMEOUT_SEC = 5.0


def _is_streaming_request(endpoint: str, request_json: dict[str, Any]) -> bool:
    endpoint_lower = endpoint.lower()
    return (
        request_json.get("stream") is True or "streamgeneratecontent" in endpoint_lower or "alt=sse" in endpoint_lower
    )


class MITMProxyInterceptor:
    def __init__(self, cache_dir: str | None = None, enable_caching: bool = True):
        self.cleaner = JSONContextCleaner()
        self.cache_dir = cache_dir or str(CoherenceSettings.from_env().cache_dir)
        self.enable_caching = enable_caching
        self._cache_store: HybridCacheStore | None = None

    @property
    def cache_store(self) -> HybridCacheStore:
        if self._cache_store is None:
            self._cache_store = HybridCacheStore(cache_dir=self.cache_dir)
        return self._cache_store

    def detect_provider(self, url_or_path: str, payload: dict[str, Any] | None = None) -> str:
        return detect_provider_name(url_or_path, payload)

    def _has_custom_intercept_request_override(self) -> bool:
        custom_intercept = getattr(self, "intercept_request", None)
        if custom_intercept is None:
            return False
        func = getattr(custom_intercept, "__func__", custom_intercept)
        return func is not MITMProxyInterceptor.intercept_request

    def intercept_request_with_stats(
        self, endpoint: str, request_json: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any] | None, CleaningResult | None]:
        if self._has_custom_intercept_request_override():
            cleaned_req, cached_resp = self.intercept_request(endpoint, request_json)
            return cleaned_req, cached_resp, None

        provider = self.detect_provider(endpoint, request_json)
        if provider == UNKNOWN_PROVIDER_NAME:
            logger.warning("Unknown LLM provider for endpoint: %s. Bypassing payload cleaning.", endpoint)
            return request_json, None, None

        clean_res = self.cleaner.process_payload_with_stats(request_json, provider=provider)
        cleaned_request = clean_res.payload

        is_streaming = _is_streaming_request(endpoint, request_json)
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
        cleaned_request, cached_response, _ = self.intercept_request_with_stats(endpoint, request_json)
        return cleaned_request, cached_response

    def intercept_response(
        self,
        endpoint: str,
        request_json: dict[str, Any],
        response_json: dict[str, Any],
        status_code: int = 200,
    ) -> None:
        if not self.enable_caching:
            return

        if _is_streaming_request(endpoint, request_json):
            return

        if status_code != 200:
            logger.warning("Skipping cache put for non-200 HTTP status code (%d) on %s", status_code, endpoint)
            return

        if isinstance(response_json, dict) and ("error" in response_json or response_json.get("type") == "error"):
            logger.warning("Skipping cache put for API error response payload on %s", endpoint)
            return

        provider = self.detect_provider(endpoint, request_json)
        if provider != UNKNOWN_PROVIDER_NAME:
            try:
                self.cache_store.put(request_json, response_json, provider=provider)
            except Exception:
                logger.exception("Cache store put failed for endpoint %s.", endpoint)


class MitmproxyAddon:
    def __init__(self, cache_dir: str | None = None, wire_log_dir: str | None = None):
        self.interceptor = MITMProxyInterceptor(cache_dir=cache_dir)
        self.wire_log_dir = wire_log_dir or CoherenceSettings.from_env().wire_log_dir_override or DEFAULT_WIRE_LOG_DIR
        self.total_requests = 0
        self.cache_hits = 0
        self.metrics = CumulativeMetrics()
        self.default_passive: bool = is_passive_monitoring()
        self._gateway_ip: str | None = None
        self._warned_gateway = False

    def done(self) -> None:
        shutdown_wire_logs(wait=True, timeout=WIRE_LOG_SHUTDOWN_TIMEOUT_SEC)

    def _proxy_own_ports(self) -> tuple[int, ...]:
        ports: list[int] = []
        env_port = CoherenceSettings.from_env().proxy_port_override
        if env_port is not None:
            ports.append(env_port)

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
        if self._gateway_ip is not None:
            return self._gateway_ip
        ip = _get_resolve_gateway_address()()
        if ip is not None:
            self._gateway_ip = ip
        return ip

    def server_connect(self, data: Any) -> None:
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
        if not is_wire_logging_enabled():
            return
        try:
            record = build_wire_record(self, flow, resp_data, status_code, WireTransaction(**fields))
            dump_wire_transaction(record, self.wire_log_dir)
        except Exception as exc:
            logger.debug("Failed to record flow wire transaction: %s", exc)

    def request(self, flow: Any) -> None:
        if getattr(flow, "request", None) is None:
            return
        ctx = RequestContext.from_flow(self, flow)
        if run_steps(REQUEST_PRELUDE, ctx) is Outcome.HALT:
            return
        run_guarded(REQUEST_GUARDED, ctx, REQUEST_POLICY)

    def responseheaders(self, flow: Any) -> None:
        if getattr(flow, "provider", UNKNOWN_PROVIDER_NAME) == UNKNOWN_PROVIDER_NAME:
            return
        flow.response_headers_time = time.perf_counter()
        flow.first_chunk_time = None
        response = getattr(flow, "response", None)
        if response is not None and "text/event-stream" in response_content_type(response).lower():
            install_sse_tap(flow, response)

    def response(self, flow: Any) -> None:
        ctx = ResponseContext.from_flow(self, flow)
        if ctx is None:
            return
        if ctx.status_code == 200:
            run_guarded(RESPONSE_SUCCESS, ctx, SUCCESS_POLICY)
        else:
            log_failure(ctx)
            run_guarded(RESPONSE_FAILURE, ctx, FAILURE_POLICY)


addons = [MitmproxyAddon()]
