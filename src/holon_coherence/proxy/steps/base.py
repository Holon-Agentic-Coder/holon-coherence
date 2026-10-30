"""Pipeline primitives: per-flow contexts, step specs, error policies and the runner.

A pipeline is an ordered tuple of ``StepSpec``. ``run_steps`` is the only place that branches on
passive (baseline) monitoring, and ``run_guarded`` is the only place that applies a pipeline's error
policy, so individual steps stay single-purpose and free of mode or error plumbing.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal
from urllib.parse import urlparse

from holon_coherence.proxy.wire_log import is_flow_passive

__all__ = [
    "ErrorPolicy",
    "Outcome",
    "RequestContext",
    "ResponseContext",
    "StepSpec",
    "hit_rate",
    "logger",
    "run_guarded",
    "run_steps",
]

# Steps log under the addon's logger name so operators and log-capturing tests see identical records.
logger = logging.getLogger("holon_coherence.proxy.addon")


class Outcome(Enum):
    CONTINUE = "continue"
    HALT = "halt"


def hit_rate(addon: Any) -> float:
    """Local cache hit rate of the addon, 0.0 before the first request."""
    return addon.cache_hits / addon.total_requests if addon.total_requests > 0 else 0.0


@dataclass
class _FlowContext:
    addon: Any
    flow: Any
    url: str
    _passive: bool | None = field(default=None, init=False, repr=False)

    @property
    def passive(self) -> bool:
        """Whether the flow runs in passive (baseline) mode, evaluated once on first access."""
        if self._passive is None:
            self._passive = is_flow_passive(self.flow, default_passive=getattr(self.addon, "default_passive", None))
        return self._passive


@dataclass
class RequestContext(_FlowContext):
    path_clean: str = ""
    method: str = "GET"
    data: Any = None
    provider: str = "unknown"
    is_local: bool = False
    cached_resp: Any = None
    clean_res: Any = None

    @classmethod
    def from_flow(cls, addon: Any, flow: Any) -> RequestContext:
        url = getattr(flow.request, "pretty_url", "")
        raw_path = getattr(flow.request, "path", "") or urlparse(url if "://" in url else f"http://{url}").path
        path_clean = raw_path.split("?")[0].rstrip("/")
        method = (getattr(flow.request, "method", "") or "GET").upper()
        return cls(addon=addon, flow=flow, url=url, path_clean=path_clean, method=method)


@dataclass
class ResponseContext(_FlowContext):
    status_code: int = 200
    provider: str = "unknown"
    req_data: Any = None
    resp_data: Any = None
    is_sse: bool = False
    elapsed_ms: float = 0.0
    telemetry: Any = None

    @classmethod
    def from_flow(cls, addon: Any, flow: Any) -> ResponseContext | None:
        """Context for a provider response that still needs processing, else ``None``."""
        if getattr(flow, "request", None) is None or getattr(flow, "response", None) is None:
            return None
        url = getattr(flow.request, "pretty_url", "")
        status_code = getattr(flow.response, "status_code", 200)
        provider = getattr(flow, "provider", "unknown")
        if provider == "unknown" or getattr(flow, "is_cached", False):
            return None
        return cls(addon=addon, flow=flow, url=url, status_code=status_code, provider=provider)


StepMode = Literal["always", "active", "passive"]


@dataclass(frozen=True)
class StepSpec:
    """One named pipeline step; ``mode`` restricts it to active or passive flows."""

    name: str
    fn: Callable[[Any], Outcome]
    mode: StepMode = "always"


@dataclass(frozen=True)
class ErrorPolicy:
    """How ``run_guarded`` logs a failure.

    ``json_message`` (formatted with url and exception) handles ``json.JSONDecodeError``; when it is
    ``None`` the decode error is treated like any other exception. ``exception_message`` is formatted
    with the url or the exception, per ``exception_arg``, and logged at ``exception_level``.
    """

    json_message: str | None
    exception_message: str
    exception_level: Literal["exception", "debug"]
    exception_arg: Literal["url", "exc"] = "url"


def run_steps(steps: Iterable[StepSpec], ctx: Any) -> Outcome:
    """Run steps in order, skipping steps whose mode does not match the flow, until one halts."""
    for step in steps:
        if step.mode != "always" and ctx.passive != (step.mode == "passive"):
            continue
        if step.fn(ctx) is Outcome.HALT:
            return Outcome.HALT
    return Outcome.CONTINUE


def _log_failure(policy: ErrorPolicy, ctx: Any, exc: Exception) -> None:
    arg = ctx.url if policy.exception_arg == "url" else exc
    if policy.exception_level == "exception":
        logger.exception(policy.exception_message, arg)
    else:
        logger.debug(policy.exception_message, arg)


def run_guarded(steps: Iterable[StepSpec], ctx: Any, policy: ErrorPolicy) -> None:
    """Run steps under ``policy``: failures are logged and swallowed, never raised to mitmproxy."""
    try:
        run_steps(steps, ctx)
    except json.JSONDecodeError as exc:
        if policy.json_message is None:
            _log_failure(policy, ctx, exc)
        else:
            logger.debug(policy.json_message, ctx.url, exc)
    except Exception as exc:
        _log_failure(policy, ctx, exc)
