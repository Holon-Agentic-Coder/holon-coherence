from __future__ import annotations

import concurrent.futures
import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from holon_coherence.proxy.wire_log import (
    WIRE_LOG_MAX_PENDING,
    _pending_wire_log_futures,
    _wire_log_lock,
    dump_wire_transaction,
    flush_wire_logs,
    get_dropped_wire_log_count,
    is_flow_passive,
    is_passive_monitoring,
    is_wire_logging_enabled,
    log_telemetry,
)


def test_is_wire_logging_enabled(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_WIRE_LOGGING", "1")
    assert is_wire_logging_enabled() is True
    monkeypatch.setenv("ENABLE_WIRE_LOGGING", "0")
    assert is_wire_logging_enabled() is False


def test_is_passive_monitoring(monkeypatch) -> None:
    monkeypatch.setenv("HOLON_PASSIVE_MONITORING", "1")
    assert is_passive_monitoring() is True
    monkeypatch.setenv("HOLON_PASSIVE_MONITORING", "0")
    monkeypatch.setenv("COHERENCE_TOKEN_REDUCTION", "1")
    assert is_passive_monitoring() is False


def test_is_flow_passive_header_override() -> None:
    flow = MagicMock()
    flow.request.headers = {"x-holon-passive": "1"}
    assert is_flow_passive(flow) is True

    flow.request.headers = {"x-holon-passive": "0"}
    assert is_flow_passive(flow) is False


def test_dump_wire_transaction_and_flush(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_WIRE_LOGGING", "1")
    wire_dir = str(tmp_path / "wire_logs")

    record = {
        "turn_id": 42,
        "flow_id": "test_flow_123",
        "agent_id": "agy",
        "content": "test payload",
    }

    dump_wire_transaction(record, wire_log_dir=wire_dir)
    flush_wire_logs(timeout=5.0)

    turn_file = Path(wire_dir) / "turn_42_test_flow_123.json"
    assert turn_file.exists()
    loaded = json.loads(turn_file.read_text(encoding="utf-8"))
    assert loaded["turn_id"] == 42
    assert loaded["flow_id"] == "test_flow_123"

    jsonl_file = Path(wire_dir) / "transactions.jsonl"
    assert jsonl_file.exists()
    lines = jsonl_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["turn_id"] == 42


def test_log_telemetry_stdout(capsys) -> None:
    log_telemetry("telemetry testing message")


def test_dump_wire_transaction_prunes_completed_futures_on_submission(tmp_path: Path, monkeypatch) -> None:
    get_dropped_wire_log_count(reset=True)
    monkeypatch.setenv("ENABLE_WIRE_LOGGING", "1")
    monkeypatch.setenv("WIRE_LOG_MAX_PENDING", "1")

    done_future: concurrent.futures.Future[None] = concurrent.futures.Future()
    done_future.set_result(None)
    with _wire_log_lock:
        _pending_wire_log_futures.add(done_future)

    try:
        dump_wire_transaction({"turn_id": 1, "flow_id": "prune"}, wire_log_dir=str(tmp_path))
        with _wire_log_lock:
            assert done_future not in _pending_wire_log_futures
        assert get_dropped_wire_log_count() == 0
        flush_wire_logs(timeout=5.0)
        assert (tmp_path / "turn_1_prune.json").exists()
    finally:
        with _wire_log_lock:
            _pending_wire_log_futures.discard(done_future)
        flush_wire_logs(timeout=5.0)
        get_dropped_wire_log_count(reset=True)


def test_dump_wire_transaction_bounds_pending_queue_and_counts_drops(tmp_path: Path, monkeypatch) -> None:
    get_dropped_wire_log_count(reset=True)
    monkeypatch.setenv("ENABLE_WIRE_LOGGING", "1")
    monkeypatch.setenv("WIRE_LOG_MAX_PENDING", "2")

    placeholders: list[concurrent.futures.Future[None]] = [
        concurrent.futures.Future(),
        concurrent.futures.Future(),
    ]
    with _wire_log_lock:
        _pending_wire_log_futures.update(placeholders)

    try:
        overflow_futures = [
            dump_wire_transaction({"turn_id": idx, "flow_id": "overflow"}, wire_log_dir=str(tmp_path))
            for idx in range(3)
        ]
        for future in overflow_futures:
            assert future.done() is True
            assert future.result(timeout=1.0) is None
        with _wire_log_lock:
            assert len(_pending_wire_log_futures) == 2
        assert get_dropped_wire_log_count() == 3
        assert get_dropped_wire_log_count(reset=True) == 3
        assert get_dropped_wire_log_count() == 0
    finally:
        with _wire_log_lock:
            _pending_wire_log_futures.difference_update(placeholders)
        get_dropped_wire_log_count(reset=True)


def test_wire_log_max_pending_invalid_env_falls_back_to_default(tmp_path: Path, monkeypatch) -> None:
    assert WIRE_LOG_MAX_PENDING == 256
    get_dropped_wire_log_count(reset=True)
    monkeypatch.setenv("ENABLE_WIRE_LOGGING", "1")

    try:
        for raw_value in ("invalid", "-5"):
            monkeypatch.setenv("WIRE_LOG_MAX_PENDING", raw_value)
            dump_wire_transaction({"turn_id": 1, "flow_id": f"fallback_{raw_value}"}, wire_log_dir=str(tmp_path))
            flush_wire_logs(timeout=5.0)
            assert get_dropped_wire_log_count() == 0
            assert (tmp_path / f"turn_1_fallback_{raw_value}.json").exists()
    finally:
        flush_wire_logs(timeout=5.0)
        get_dropped_wire_log_count(reset=True)


def test_is_flow_passive_logs_debug_on_header_error(caplog: pytest.LogCaptureFixture) -> None:
    flow = MagicMock()
    flow.request.headers.get.side_effect = TypeError("bad header lookup")
    with caplog.at_level(logging.DEBUG, logger="holon_coherence.proxy.wire_log"):
        assert is_flow_passive(flow, default_passive=True) is True
    assert any(r.levelno == logging.DEBUG and "bad header lookup" in r.getMessage() for r in caplog.records)

    caplog.clear()
    flow.request.headers.get.side_effect = AttributeError("missing header method")
    with caplog.at_level(logging.DEBUG, logger="holon_coherence.proxy.wire_log"):
        assert is_flow_passive(flow, default_passive=False) is False
    assert any(r.levelno == logging.DEBUG and "missing header method" in r.getMessage() for r in caplog.records)


def test_log_telemetry_logs_debug_and_falls_back_on_ctx_runtime_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_ctx = MagicMock()
    fake_ctx.log.info.side_effect = RuntimeError("ctx log unavailable")
    with (
        patch("holon_coherence.proxy.wire_log.ctx", fake_ctx),
        patch.dict("sys.modules", {"holon_coherence.mitm_addon": None}),
        caplog.at_level(logging.DEBUG, logger="holon_coherence.proxy.wire_log"),
    ):
        log_telemetry("telemetry fallback message")

    assert any(r.levelno == logging.DEBUG and "ctx log unavailable" in r.getMessage() for r in caplog.records)
    assert any(r.levelno == logging.INFO and "telemetry fallback message" in r.getMessage() for r in caplog.records)


def test_dump_wire_transaction_resolves_wire_log_dir_dynamically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ENABLE_WIRE_LOGGING", "1")

    dir_a = tmp_path / "dir_a"
    monkeypatch.setenv("WIRE_LOG_DIR", str(dir_a))
    dump_wire_transaction({"turn_id": 1, "flow_id": "dyn_a"})
    flush_wire_logs(timeout=5.0)
    assert (dir_a / "transactions.jsonl").exists()

    dir_b = tmp_path / "dir_b"
    monkeypatch.setenv("WIRE_LOG_DIR", str(dir_b))
    dump_wire_transaction({"turn_id": 2, "flow_id": "dyn_b"})
    flush_wire_logs(timeout=5.0)
    assert (dir_b / "transactions.jsonl").exists()

    monkeypatch.delenv("WIRE_LOG_DIR", raising=False)
    dump_wire_transaction({"turn_id": 3, "flow_id": "dyn_default"})
    flush_wire_logs(timeout=5.0)
    assert (tmp_path / ".holon" / "mitm_wire_logs" / "transactions.jsonl").exists()


def test_wire_log_flags_respond_dynamically_to_bool_variants(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_WIRE_LOGGING", "yes")
    assert is_wire_logging_enabled() is True
    monkeypatch.setenv("ENABLE_WIRE_LOGGING", "off")
    assert is_wire_logging_enabled() is False

    monkeypatch.setenv("HOLON_PASSIVE_MONITORING", "true")
    monkeypatch.setenv("COHERENCE_TOKEN_REDUCTION", "yes")
    assert is_passive_monitoring() is True

    monkeypatch.setenv("HOLON_PASSIVE_MONITORING", "false")
    monkeypatch.setenv("COHERENCE_TOKEN_REDUCTION", "off")
    assert is_passive_monitoring() is True

    monkeypatch.setenv("COHERENCE_TOKEN_REDUCTION", "yes")
    assert is_passive_monitoring() is False
