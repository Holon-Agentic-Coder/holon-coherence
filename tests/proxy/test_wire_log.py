"""Unit tests for background wire log persistence."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from holon_coherence.proxy.wire_log import (
    dump_wire_transaction,
    flush_wire_logs,
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
