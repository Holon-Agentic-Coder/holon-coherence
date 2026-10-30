"""Late-bound test seams shared by the addon and its pipeline steps.

Tests monkeypatch symbols on the ``holon_coherence.mitm_addon`` facade, so every lookup here resolves
through that module at call time and only falls back to the real implementation when the facade has
not been imported.
"""

from __future__ import annotations

import sys
from typing import Any

try:
    from mitmproxy import ctx, http
except ImportError:
    ctx = None
    http = None

from holon_coherence.host_local import in_container, resolve_gateway_address
from holon_coherence.proxy.routing import is_local_target
from holon_coherence.proxy.wire_log import log_telemetry

__all__ = [
    "_get_ctx",
    "_get_in_container",
    "_get_is_local_target",
    "_get_log_telemetry",
    "_get_resolve_gateway_address",
    "resolve_response_cls",
]

_FACADE_MODULE = "holon_coherence.mitm_addon"
_ADDON_MODULE = "holon_coherence.proxy.addon"


def _get_in_container() -> Any:
    mod = sys.modules.get(_FACADE_MODULE)
    if mod is not None and hasattr(mod, "in_container"):
        return mod.in_container
    return in_container


def _get_resolve_gateway_address() -> Any:
    mod = sys.modules.get(_FACADE_MODULE)
    if mod is not None and hasattr(mod, "resolve_gateway_address"):
        return mod.resolve_gateway_address
    return resolve_gateway_address


def _get_log_telemetry() -> Any:
    mod = sys.modules.get(_FACADE_MODULE)
    if mod is not None and hasattr(mod, "log_telemetry"):
        return mod.log_telemetry
    return log_telemetry


def _get_ctx() -> Any:
    mod = sys.modules.get(_FACADE_MODULE)
    if mod is not None and hasattr(mod, "ctx"):
        return mod.ctx
    return ctx


def _get_is_local_target() -> Any:
    mod = sys.modules.get(_FACADE_MODULE)
    if mod is not None and hasattr(mod, "is_local_target"):
        return mod.is_local_target
    return is_local_target


def resolve_response_cls(flow: Any) -> Any:
    """Response class used for cache hits: live mitmproxy first, then the flow's, then the addon module's."""
    addon_mod = sys.modules.get(_ADDON_MODULE)
    addon_globals = vars(addon_mod) if addon_mod is not None else {}
    return getattr(http, "Response", None) or getattr(flow, "Response", None) or addon_globals.get("Response")
