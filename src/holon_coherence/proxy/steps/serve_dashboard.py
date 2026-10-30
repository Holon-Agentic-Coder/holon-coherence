"""Control-plane endpoints the proxy answers itself: metrics, mode switch and the web dashboard."""

from __future__ import annotations

import json

from holon_coherence.proxy.dashboard import render_dashboard_html
from holon_coherence.proxy.routing import _make_http_response
from holon_coherence.proxy.steps.base import Outcome, RequestContext
from holon_coherence.proxy.wire_log import is_passive_monitoring

__all__ = ["serve_dashboard", "serve_html", "serve_metrics", "serve_mode"]

_METRICS_PATHS = ("/holon/api/metrics", "/_holon/metrics")
_MODE_PATHS = ("/holon/api/mode", "/_holon/mode")


def serve_metrics(ctx: RequestContext) -> Outcome:
    """GET /holon/api/metrics or /_holon/metrics: cumulative metrics snapshot."""
    if ctx.method != "GET" or ctx.path_clean not in _METRICS_PATHS:
        return Outcome.CONTINUE
    metrics_bytes = json.dumps(ctx.addon.metrics.to_dict(), indent=2).encode("utf-8")
    ctx.flow.response = _make_http_response(
        ctx.flow,
        200,
        metrics_bytes,
        {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
    )
    return Outcome.HALT


def _mode_post(ctx: RequestContext) -> None:
    addon, flow = ctx.addon, ctx.flow
    try:
        mode_data = json.loads(flow.request.get_text() or "{}")
        new_mode = str(mode_data.get("mode", "")).lower().strip()
        if new_mode in ("baseline", "passive"):
            addon.default_passive = True
        elif new_mode in ("optimized", "active"):
            addon.default_passive = False
        if mode_data.get("wire_log_dir"):
            addon.wire_log_dir = str(mode_data["wire_log_dir"])
        resp_bytes = json.dumps(
            {
                "status": "ok",
                "mode": "baseline" if getattr(addon, "default_passive", False) else "optimized",
                "wire_log_dir": addon.wire_log_dir,
            }
        ).encode("utf-8")
        flow.response = _make_http_response(flow, 200, resp_bytes, {"Content-Type": "application/json"})
    except Exception as exc:
        flow.response = _make_http_response(
            flow,
            400,
            json.dumps({"error": str(exc)}).encode("utf-8"),
            {"Content-Type": "application/json"},
        )


def _mode_get(ctx: RequestContext) -> None:
    addon = ctx.addon
    current_mode = "baseline" if getattr(addon, "default_passive", False) or is_passive_monitoring() else "optimized"
    resp_bytes = json.dumps({"mode": current_mode, "wire_log_dir": addon.wire_log_dir}).encode("utf-8")
    ctx.flow.response = _make_http_response(ctx.flow, 200, resp_bytes, {"Content-Type": "application/json"})


def serve_mode(ctx: RequestContext) -> Outcome:
    """POST/GET /holon/api/mode or /_holon/mode; any other method falls through to the proxy path."""
    if ctx.path_clean not in _MODE_PATHS:
        return Outcome.CONTINUE
    if ctx.method == "POST":
        _mode_post(ctx)
        return Outcome.HALT
    if ctx.method == "GET":
        _mode_get(ctx)
        return Outcome.HALT
    return Outcome.CONTINUE


def serve_html(ctx: RequestContext) -> Outcome:
    """GET /holon or /holon/: the live web dashboard."""
    if ctx.method != "GET" or ctx.path_clean != "/holon":
        return Outcome.CONTINUE
    dashboard_bytes = render_dashboard_html().encode("utf-8")
    ctx.flow.response = _make_http_response(
        ctx.flow,
        200,
        dashboard_bytes,
        {"Content-Type": "text/html; charset=utf-8"},
    )
    return Outcome.HALT


def serve_dashboard(ctx: RequestContext) -> Outcome:
    """Answer proxy control-plane endpoints locally, halting the pipeline when one matched."""
    for handler in (serve_metrics, serve_mode, serve_html):
        if handler(ctx) is Outcome.HALT:
            return Outcome.HALT
    return Outcome.CONTINUE
