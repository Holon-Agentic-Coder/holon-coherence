from __future__ import annotations

import atexit
import concurrent.futures
import contextlib
import json
import logging
import os
import re
import sys
import threading
import uuid
from typing import Any

try:
    from mitmproxy import ctx
except ImportError:
    ctx = None

from holon_coherence.metrics_math import DEFAULT_WIRE_LOG_DIR
from holon_coherence.settings import DEFAULT_WIRE_LOG_MAX_PENDING, CoherenceSettings

__all__ = [
    "WIRE_LOG_DIR",
    "WIRE_LOG_MAX_PENDING",
    "_discard_pending_future",
    "_get_wire_log_executor",
    "_pending_wire_log_futures",
    "_wire_log_executor",
    "_wire_log_lock",
    "_write_transaction_sync",
    "dump_wire_transaction",
    "flush_wire_logs",
    "get_dropped_wire_log_count",
    "is_flow_passive",
    "is_passive_monitoring",
    "is_wire_logging_enabled",
    "log_telemetry",
    "shutdown_wire_logs",
]

logger = logging.getLogger(__name__)

WIRE_LOG_DIR = DEFAULT_WIRE_LOG_DIR
WIRE_LOG_MAX_PENDING = DEFAULT_WIRE_LOG_MAX_PENDING


def is_wire_logging_enabled() -> bool:
    return CoherenceSettings.from_env().enable_wire_logging


def is_passive_monitoring() -> bool:
    settings = CoherenceSettings.from_env()
    return settings.passive_monitoring or not settings.token_reduction


def is_flow_passive(flow: Any, default_passive: bool | None = None) -> bool:
    try:
        headers = getattr(getattr(flow, "request", None), "headers", None)
        if headers is not None:
            for key in ("x-holon-passive", "x-holon-mode", "X-Holon-Passive", "X-Holon-Mode"):
                val = headers.get(key)
                if val:
                    val_clean = val.strip().lower()
                    if val_clean in ("1", "true", "yes", "baseline", "passive"):
                        return True
                    if val_clean in ("0", "false", "no", "optimized", "active"):
                        return False
    except (AttributeError, TypeError, ValueError) as exc:
        logger.debug("Failed to inspect passive flow headers: %s", exc)
    return default_passive if default_passive is not None else is_passive_monitoring()


_wire_log_executor: concurrent.futures.ThreadPoolExecutor | None = None
_pending_wire_log_futures: set[concurrent.futures.Future] = set()
_wire_log_lock = threading.RLock()
_dropped_wire_log_count = 0


def _completed_future() -> concurrent.futures.Future:
    future: concurrent.futures.Future = concurrent.futures.Future()
    future.set_result(None)
    return future


def _wire_log_max_pending() -> int:
    return CoherenceSettings.from_env().wire_log_max_pending


def get_dropped_wire_log_count(reset: bool = False) -> int:
    global _dropped_wire_log_count
    with _wire_log_lock:
        count = _dropped_wire_log_count
        if reset:
            _dropped_wire_log_count = 0
        return count


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
        safe_turn_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(record.get("turn_id", 0)))
        safe_flow_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(record.get("flow_id", "flow")))
        filepath = os.path.join(wire_log_dir, f"turn_{safe_turn_id}_{safe_flow_id}.json")
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
            with contextlib.suppress(OSError):
                os.unlink(tmp_filepath)
            raise
        jsonl_path = os.path.join(wire_log_dir, "transactions.jsonl")
        j_fd = os.open(jsonl_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(j_fd, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        with contextlib.suppress(OSError):
            os.chmod(jsonl_path, 0o600)
    except Exception as exc:
        logger.warning("Failed to persist wire log transaction: %s", exc)


def dump_wire_transaction(record: dict[str, Any], wire_log_dir: str | None = None) -> concurrent.futures.Future:
    global _dropped_wire_log_count
    target_dir = wire_log_dir or CoherenceSettings.from_env().wire_log_dir_override or DEFAULT_WIRE_LOG_DIR
    if not is_wire_logging_enabled() or not target_dir:
        return _completed_future()

    with _wire_log_lock:
        _pending_wire_log_futures.difference_update([f for f in _pending_wire_log_futures if f.done()])
        if len(_pending_wire_log_futures) >= _wire_log_max_pending():
            _dropped_wire_log_count += 1
            return _completed_future()
        future = _get_wire_log_executor().submit(_write_transaction_sync, record, target_dir)
        _pending_wire_log_futures.add(future)
    future.add_done_callback(_discard_pending_future)
    return future


def _discard_pending_future(future: concurrent.futures.Future) -> None:
    with _wire_log_lock:
        _pending_wire_log_futures.discard(future)


def flush_wire_logs(timeout: float = 5.0) -> None:
    with _wire_log_lock:
        pending = list(_pending_wire_log_futures)
    if pending:
        concurrent.futures.wait(pending, timeout=timeout)


def shutdown_wire_logs(wait: bool = True, timeout: float = 5.0) -> None:
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


def log_telemetry(msg: str) -> None:
    active_ctx = ctx
    mod = sys.modules.get("holon_coherence.mitm_addon")
    if mod is not None and hasattr(mod, "ctx"):
        active_ctx = mod.ctx
    if active_ctx and hasattr(active_ctx, "log") and hasattr(active_ctx.log, "info"):
        try:
            active_ctx.log.info(msg)
            return
        except (AttributeError, RuntimeError, TypeError, OSError) as exc:
            logger.debug("mitmproxy ctx.log.info failed, falling back to stdlib logger: %s", exc)
    logger.info(msg)
