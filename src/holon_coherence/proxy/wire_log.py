"""Background asynchronous wire logging infrastructure."""

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

__all__ = [
    "WIRE_LOG_DIR",
    "_discard_pending_future",
    "_get_wire_log_executor",
    "_pending_wire_log_futures",
    "_wire_log_executor",
    "_wire_log_lock",
    "_write_transaction_sync",
    "dump_wire_transaction",
    "flush_wire_logs",
    "is_flow_passive",
    "is_passive_monitoring",
    "is_wire_logging_enabled",
    "log_telemetry",
    "shutdown_wire_logs",
]

logger = logging.getLogger(__name__)

WIRE_LOG_DIR = os.getenv("WIRE_LOG_DIR", DEFAULT_WIRE_LOG_DIR)


def is_wire_logging_enabled() -> bool:
    """Checks whether wire logging is enabled via environment configuration."""
    flag = os.getenv("ENABLE_WIRE_LOGGING", "1").lower().strip()
    return flag not in ("0", "false", "no", "off")


def is_passive_monitoring() -> bool:
    """Checks whether proxy operates in passive monitoring mode (logging only, no reduction/caching)."""
    flag = os.getenv("HOLON_PASSIVE_MONITORING", "0").lower().strip()
    if flag in ("1", "true", "yes", "on"):
        return True
    tr_flag = os.getenv("COHERENCE_TOKEN_REDUCTION", "1").lower().strip()
    return tr_flag in ("0", "false", "no", "off")


def is_flow_passive(flow: Any, default_passive: bool | None = None) -> bool:
    """Checks whether the flow should be handled in passive monitoring mode (baseline)."""
    try:
        if flow and hasattr(flow, "request") and hasattr(flow.request, "headers"):
            headers = flow.request.headers
            for key in ("x-holon-passive", "x-holon-mode", "X-Holon-Passive", "X-Holon-Mode"):
                val = headers.get(key)
                if val:
                    val_clean = val.strip().lower()
                    if val_clean in ("1", "true", "yes", "baseline", "passive"):
                        return True
                    if val_clean in ("0", "false", "no", "optimized", "active"):
                        return False
    except Exception:
        pass
    if default_passive is not None:
        return default_passive
    return is_passive_monitoring()


_wire_log_executor: concurrent.futures.ThreadPoolExecutor | None = None
_pending_wire_log_futures: set[concurrent.futures.Future] = set()
_wire_log_lock = threading.Lock()


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
        turn_id = record.get("turn_id", 0)
        flow_id = record.get("flow_id", "flow")
        safe_turn_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(turn_id))
        safe_flow_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(flow_id))
        filename = f"turn_{safe_turn_id}_{safe_flow_id}.json"
        filepath = os.path.join(wire_log_dir, filename)

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
            if os.path.exists(tmp_filepath):
                with contextlib.suppress(OSError):
                    os.unlink(tmp_filepath)
            raise

        jsonl_path = os.path.join(wire_log_dir, "transactions.jsonl")
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        j_fd = os.open(jsonl_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(j_fd, "a", encoding="utf-8") as f:
            f.write(line)
        with contextlib.suppress(OSError):
            os.chmod(jsonl_path, 0o600)
    except Exception as exc:
        logger.warning("Failed to persist wire log transaction: %s", exc)


def dump_wire_transaction(record: dict[str, Any], wire_log_dir: str | None = None) -> concurrent.futures.Future:
    """Asynchronously writes turn-scoped JSON dump and atomic JSONL entry."""
    target_dir = wire_log_dir or os.getenv("WIRE_LOG_DIR", WIRE_LOG_DIR)
    if not is_wire_logging_enabled() or not target_dir:
        dummy: concurrent.futures.Future = concurrent.futures.Future()
        dummy.set_result(None)
        return dummy

    future = _get_wire_log_executor().submit(_write_transaction_sync, record, target_dir)
    with _wire_log_lock:
        _pending_wire_log_futures.add(future)
    future.add_done_callback(_discard_pending_future)
    return future


def _discard_pending_future(future: concurrent.futures.Future) -> None:
    with _wire_log_lock:
        _pending_wire_log_futures.discard(future)


def flush_wire_logs(timeout: float = 5.0) -> None:
    """Blocks until all queued background wire log writes complete."""
    with _wire_log_lock:
        pending = list(_pending_wire_log_futures)
    if pending:
        concurrent.futures.wait(pending, timeout=timeout)


def shutdown_wire_logs(wait: bool = True, timeout: float = 5.0) -> None:
    """Blocks until pending wire log writes finish and cleanly shuts down the ThreadPoolExecutor."""
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
    """Logs telemetry message to mitmproxy console context if available, falling back to standard logger."""
    active_ctx = ctx
    mod = sys.modules.get("holon_coherence.mitm_addon")
    if mod is not None and hasattr(mod, "ctx"):
        active_ctx = mod.ctx
    if active_ctx and hasattr(active_ctx, "log") and hasattr(active_ctx.log, "info"):
        try:
            active_ctx.log.info(msg)
            return
        except Exception:
            # mitmproxy context is unavailable or inactive in this execution context
            pass

    logger.info(msg)
