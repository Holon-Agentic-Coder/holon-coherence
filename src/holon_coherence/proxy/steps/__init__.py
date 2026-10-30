"""Ordered step pipelines behind the ``MitmproxyAddon`` hooks.

The pipelines are plain tuples of ``StepSpec`` so their order is data that can be inspected and tested.
``request`` runs ``REQUEST_PRELUDE`` unguarded (failures propagate to mitmproxy, as before) and then
``REQUEST_GUARDED`` under ``REQUEST_POLICY``. ``response`` runs ``RESPONSE_SUCCESS`` under
``SUCCESS_POLICY`` for HTTP 200, otherwise ``log_failure`` followed by ``RESPONSE_FAILURE`` under
``FAILURE_POLICY``.
"""

from __future__ import annotations

from holon_coherence.proxy.steps.apply_cache import serve_cached, store_response
from holon_coherence.proxy.steps.base import (
    ErrorPolicy,
    Outcome,
    RequestContext,
    ResponseContext,
    StepSpec,
    run_guarded,
    run_steps,
)
from holon_coherence.proxy.steps.clean_payload import clean_payload, passthrough_payload, snapshot_request
from holon_coherence.proxy.steps.identify_provider import identify_provider, parse_request_body
from holon_coherence.proxy.steps.load_exchange import load_request, load_response, require_payloads
from holon_coherence.proxy.steps.record_metrics import (
    compute_telemetry,
    dump_miss_transaction,
    inject_miss_headers,
    log_failure,
    log_miss_telemetry,
    record_failure,
    record_response_metrics,
)
from holon_coherence.proxy.steps.route_local_target import adapt_local_protocol, route_local_target
from holon_coherence.proxy.steps.serve_dashboard import serve_dashboard

__all__ = [
    "FAILURE_POLICY",
    "REQUEST_GUARDED",
    "REQUEST_POLICY",
    "REQUEST_PRELUDE",
    "RESPONSE_FAILURE",
    "RESPONSE_SUCCESS",
    "SUCCESS_POLICY",
    "ErrorPolicy",
    "Outcome",
    "RequestContext",
    "ResponseContext",
    "StepSpec",
    "log_failure",
    "run_guarded",
    "run_steps",
]

REQUEST_PRELUDE: tuple[StepSpec, ...] = (
    StepSpec("serve_dashboard", serve_dashboard),
    StepSpec("route_local_target", route_local_target),
    StepSpec("parse_request_body", parse_request_body),
    StepSpec("identify_provider", identify_provider),
    StepSpec("adapt_local_protocol", adapt_local_protocol),
)

REQUEST_GUARDED: tuple[StepSpec, ...] = (
    StepSpec("snapshot_request", snapshot_request),
    StepSpec("passthrough_payload", passthrough_payload, mode="passive"),
    StepSpec("clean_payload", clean_payload, mode="active"),
    StepSpec("serve_cached", serve_cached, mode="active"),
)

REQUEST_POLICY = ErrorPolicy(
    json_message="Non-JSON request body for endpoint %s: %s",
    exception_message="Mitmproxy request intercept error for endpoint: %s",
    exception_level="exception",
)

RESPONSE_SUCCESS: tuple[StepSpec, ...] = (
    StepSpec("load_request", load_request),
    StepSpec("load_response", load_response),
    StepSpec("require_payloads", require_payloads),
    StepSpec("store_response", store_response, mode="active"),
    StepSpec("compute_telemetry", compute_telemetry),
    StepSpec("inject_miss_headers", inject_miss_headers),
    StepSpec("log_miss_telemetry", log_miss_telemetry),
    StepSpec("dump_miss_transaction", dump_miss_transaction),
    StepSpec("record_response_metrics", record_response_metrics),
)

SUCCESS_POLICY = ErrorPolicy(
    json_message="Non-JSON request/response body for endpoint %s: %s",
    exception_message="Mitmproxy response intercept error for endpoint: %s",
    exception_level="exception",
)

RESPONSE_FAILURE: tuple[StepSpec, ...] = (StepSpec("record_failure", record_failure),)

FAILURE_POLICY = ErrorPolicy(
    json_message=None,
    exception_message="Failed to record non-200 wire transaction: %s",
    exception_level="debug",
    exception_arg="exc",
)
