from __future__ import annotations

import hmac
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from holon_coherence.proxy.dashboard import render_dashboard_html
from holon_coherence.proxy.routing import _make_http_response
from holon_coherence.proxy.steps.base import Outcome, RequestContext
from holon_coherence.proxy.wire_log import is_passive_monitoring
from holon_coherence.settings import CoherenceSettings

__all__ = ["serve_dashboard", "serve_html", "serve_metrics", "serve_mode"]

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_METRICS_PATHS = ("/holon/api/metrics", "/_holon/metrics")
_MODE_PATHS = ("/holon/api/mode", "/_holon/mode")
_JSON_HEADERS = {"Content-Type": "application/json"}


def _get_header(flow: Any, name: str) -> str:
    headers = getattr(flow.request, "headers", None) or {}
    target = name.lower()
    for key, value in headers.items():
        if str(key).lower() == target:
            return str(value)
    return ""


def _is_loopback_host(raw_host: str) -> bool:
    host = raw_host.strip().lower()
    if not host or any(ch.isspace() or ch in "/\\@?#" for ch in host):
        return False
    if host in ("::1", "[::1]"):
        return True
    try:
        parsed = urlparse(f"http://{host}")
        _ = parsed.port
    except ValueError:
        return False
    return parsed.hostname in _LOOPBACK_HOSTS and parsed.username is None and parsed.password is None


def _is_loopback_request(ctx: RequestContext) -> bool:
    host_header = _get_header(ctx.flow, "host").strip()
    if host_header:
        return _is_loopback_host(host_header)
    if ctx.url:
        try:
            url_host = urlparse(ctx.url if "://" in ctx.url else f"http://{ctx.url}").hostname or ""
        except ValueError:
            return False
    else:
        url_host = str(getattr(ctx.flow.request, "host", "") or "")
    return _is_loopback_host(url_host)


def _is_loopback_origin(origin: str) -> bool:
    try:
        parsed = urlparse(origin.strip())
        _ = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme in ("http", "https")
        and (parsed.hostname or "").lower() in _LOOPBACK_HOSTS
        and parsed.username is None
        and parsed.password is None
    )


def _expected_api_token() -> str:
    settings = CoherenceSettings.from_env()
    return settings.api_token or settings.web_password or ""


def _is_authorized_bearer(flow: Any) -> bool:
    expected = _expected_api_token()
    if not expected:
        return False
    auth = _get_header(flow, "authorization").strip()
    scheme, _, provided = auth.partition(" ")
    if scheme.lower() != "bearer" or not provided.strip():
        return False
    return hmac.compare_digest(provided.strip().encode("utf-8"), expected.encode("utf-8"))


def _allowed_wire_log_base(addon: Any) -> Path:
    env_base = CoherenceSettings.from_env().wire_log_base_dir
    if env_base is not None:
        return env_base.resolve()
    initial = getattr(addon, "_base_wire_log_dir", None)
    if initial is None:
        initial = addon.wire_log_dir
        addon._base_wire_log_dir = initial
    return Path(str(initial)).expanduser().resolve()


def _resolve_confined_wire_log_dir(addon: Any, raw_dir: Any) -> str:
    if not isinstance(raw_dir, str) or not raw_dir.strip() or "\x00" in raw_dir:
        raise ValueError("Invalid wire_log_dir")
    base = _allowed_wire_log_base(addon)
    try:
        expanded = Path(raw_dir.strip()).expanduser()
    except RuntimeError as exc:
        raise ValueError("Invalid wire_log_dir") from exc
    candidate = (base / expanded).resolve()
    if not candidate.is_relative_to(base):
        raise ValueError("wire_log_dir outside allowed base directory")
    return str(candidate)


def _json_response(flow: Any, status: int, payload: dict[str, Any]) -> None:
    flow.response = _make_http_response(flow, status, json.dumps(payload).encode("utf-8"), _JSON_HEADERS)


def serve_metrics(ctx: RequestContext) -> Outcome:
    if ctx.method != "GET" or ctx.path_clean not in _METRICS_PATHS or not _is_loopback_request(ctx):
        return Outcome.CONTINUE
    metrics_bytes = json.dumps(ctx.addon.metrics.to_dict(), indent=2).encode("utf-8")
    ctx.flow.response = _make_http_response(ctx.flow, 200, metrics_bytes, _JSON_HEADERS)
    return Outcome.HALT


def _mode_post(ctx: RequestContext) -> None:
    addon, flow = ctx.addon, ctx.flow
    origin = _get_header(flow, "origin").strip()
    if origin and not _is_loopback_origin(origin):
        _json_response(flow, 403, {"error": "Forbidden origin"})
        return
    if not _is_authorized_bearer(flow):
        _json_response(flow, 401, {"error": "Unauthorized"})
        return
    try:
        mode_data = json.loads(flow.request.get_text() or "{}")
        if not isinstance(mode_data, dict):
            raise ValueError("Invalid JSON object")
        new_mode = str(mode_data.get("mode", "")).lower().strip()
        next_passive: bool | None = None
        if new_mode in ("baseline", "passive"):
            next_passive = True
        elif new_mode in ("optimized", "active"):
            next_passive = False
        next_wire_log_dir: str | None = None
        if mode_data.get("wire_log_dir"):
            next_wire_log_dir = _resolve_confined_wire_log_dir(addon, mode_data["wire_log_dir"])
        if next_passive is not None:
            addon.default_passive = next_passive
        if next_wire_log_dir is not None:
            addon.wire_log_dir = next_wire_log_dir
        mode_name = "baseline" if getattr(addon, "default_passive", False) else "optimized"
        _json_response(flow, 200, {"status": "ok", "mode": mode_name, "wire_log_dir": addon.wire_log_dir})
    except (ValueError, OSError) as exc:
        _json_response(flow, 400, {"error": str(exc)})


def _mode_get(ctx: RequestContext) -> None:
    addon = ctx.addon
    default_passive = getattr(addon, "default_passive", None)
    is_passive = default_passive if isinstance(default_passive, bool) else is_passive_monitoring()
    current_mode = "baseline" if is_passive else "optimized"
    _json_response(ctx.flow, 200, {"mode": current_mode, "wire_log_dir": addon.wire_log_dir})


def serve_mode(ctx: RequestContext) -> Outcome:
    if ctx.path_clean not in _MODE_PATHS or not _is_loopback_request(ctx):
        return Outcome.CONTINUE
    if ctx.method == "POST":
        _mode_post(ctx)
        return Outcome.HALT
    if ctx.method == "GET":
        _mode_get(ctx)
        return Outcome.HALT
    return Outcome.CONTINUE


def serve_html(ctx: RequestContext) -> Outcome:
    if ctx.method != "GET" or ctx.path_clean != "/holon" or not _is_loopback_request(ctx):
        return Outcome.CONTINUE
    dashboard_bytes = render_dashboard_html().encode("utf-8")
    ctx.flow.response = _make_http_response(
        ctx.flow, 200, dashboard_bytes, {"Content-Type": "text/html; charset=utf-8"}
    )
    return Outcome.HALT


def serve_dashboard(ctx: RequestContext) -> Outcome:
    if not _is_loopback_request(ctx):
        return Outcome.CONTINUE
    for handler in (serve_metrics, serve_mode, serve_html):
        if handler(ctx) is Outcome.HALT:
            return Outcome.HALT
    return Outcome.CONTINUE
