"""Unit tests for metrics CLI command, table rendering, and wire log telemetry reporting."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from holon_coherence.commands.endpoints import ExposedEndpoints
from holon_coherence.commands.metrics import _read_offline_metrics, handle, handle_metrics, register


class TestMetricsCLICommandSuite:
    """Tests for metrics fetching and display in live and offline modes."""

    def test_handle_metrics_live_formatted(self, capsys: pytest.CaptureFixture[str]) -> None:
        mock_payload = json.dumps(
            {
                "total_turns": 5,
                "total_requests": 10,
                "cache_hits": 4,
                "cache_misses": 6,
                "cache_hit_rate": 0.4,
                "tool_calls_pruned": 12,
                "tokens_reduced": 350,
                "chars_saved": 1400,
                "avg_ttft_ms": 120.5,
                "avg_decode_throughput_tps": 45.2,
                "total_input_tokens": 1500,
                "total_output_tokens": 800,
                "total_cache_read_tokens": 600,
            }
        ).encode("utf-8")

        mock_resp = MagicMock(status=200)
        mock_resp.read.return_value = mock_payload
        mock_resp.__enter__.return_value = mock_resp

        with (
            patch("urllib.request.urlopen", return_value=mock_resp),
            patch(
                "holon_coherence.commands.metrics.resolve_container_endpoints",
                return_value=ExposedEndpoints(proxy_port=8080, web_port=None, web_token=None),
            ),
        ):
            ret = handle_metrics(port=8080)
        assert ret == 0
        out = capsys.readouterr().out
        assert "HOLON COHERENCE OPTIMIZATION METRICS" in out
        assert "Tool Calls Saved / Pruned    : 12" in out
        assert "Tokens Reduced               : 350" in out
        assert "Cache Hit Rate               : 40.0%" in out

    def test_handle_metrics_live_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        payload = {"tool_calls_pruned": 8, "tokens_reduced": 200, "cache_hit_rate": 0.25}
        mock_resp = MagicMock(status=200)
        mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            ret = handle_metrics(port=8080, json_output=True)
        assert ret == 0
        data = json.loads(capsys.readouterr().out)
        assert data["tool_calls_pruned"] == 8
        assert data["tokens_reduced"] == 200

    def test_handle_metrics_offline_wire_log(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        jsonl = tmp_path / "transactions.jsonl"
        records = [
            {
                "turn_id": 1,
                "cache_action": "HIT",
                "delta": {"tool_outputs_omitted": 2, "chars_saved": 400},
                "response": {"usage": {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 100}},
                "timing": {"ttft_ms": 10.0},
            },
        ]
        with open(jsonl, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        monkeypatch.setenv("WIRE_LOG_DIR", str(tmp_path))
        with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
            ret = handle_metrics(json_output=True)
        assert ret == 0
        data = json.loads(capsys.readouterr().out)
        assert data["source"] == "offline_wire_log"
        assert data["tool_calls_pruned"] == 2


class TestMetricsRegistrationAndDispatch:
    """Tests for metrics subparser registration and command handling."""

    def test_register_and_defaults(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        metrics_parser = register(subparsers)

        args = parser.parse_args(["metrics", "--json", "--port", "9090"])
        assert args.command == "metrics"
        assert args.json is True
        assert args.port == 9090
        assert getattr(args, "handler") == handle

    def test_handle_metrics_dispatch(self) -> None:
        args = argparse.Namespace(command="metrics", port=8080, json=True, offline=False, name=None)
        payload = {"tool_calls_pruned": 0}
        mock_resp = MagicMock(status=200)
        mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            res = handle(args)
            assert res == 0
