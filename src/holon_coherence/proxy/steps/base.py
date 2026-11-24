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

ADDON_LOGGER_NAME = "holon_coherence.proxy.addon"
logger = logging.getLogger(ADDON_LOGGER_NAME)


class Outcome(Enum):
    CONTINUE = "continue"
    HALT = "halt"


def hit_rate(addon: Any) -> float:
    return addon.cache_hits / addon.total_requests if addon.total_requests > 0 else 0.0


@dataclass
class _FlowContext:
    addon: Any
    flow: Any
    url: str
    _passive: bool | None = field(default=None, init=False, repr=False)

    @property
    def passive(self) -> bool:
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
    name: str
    fn: Callable[[Any], Outcome]
    mode: StepMode = "always"


@dataclass(frozen=True)
class ErrorPolicy:
    json_message: str | None
    exception_message: str
    exception_level: Literal["exception", "debug"]
    exception_arg: Literal["url", "exc"] = "url"


def run_steps(steps: Iterable[StepSpec], ctx: Any) -> Outcome:
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
    try:
        run_steps(steps, ctx)
    except json.JSONDecodeError as exc:
        if policy.json_message is None:
            _log_failure(policy, ctx, exc)
        else:
            logger.debug(policy.json_message, ctx.url, exc)
    except Exception as exc:
        _log_failure(policy, ctx, exc)
