"""Unit tests for metrics CLI command, table rendering, and wire log telemetry reporting."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from holon_coherence.cli import main
from holon_coherence.commands.endpoints import ExposedEndpoints
from holon_coherence.commands.metrics import _read_offline_metrics, handle, handle_metrics, register
from holon_coherence.mitm_addon import CumulativeMetrics


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
        register(subparsers)

        args = parser.parse_args(["metrics", "--json", "--port", "9090"])
        assert args.command == "metrics"
        assert args.json is True
        assert args.port == 9090
        assert args.handler == handle

    def test_handle_metrics_dispatch(self) -> None:
        args = argparse.Namespace(command="metrics", port=8080, json=True, offline=False, name=None)
        payload = {"tool_calls_pruned": 0}
        mock_resp = MagicMock(status=200)
        mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            res = handle(args)
            assert res == 0


class TestCLIMetricsCommand:
    """Tests for holon-coherence metrics command and status integration."""

    @pytest.fixture(autouse=True)
    def _no_docker_queries(self) -> Iterator[None]:
        """Endpoint rows query Docker for the container's ports; these tests run with no container."""
        with patch("holon_coherence.commands.endpoints.is_container_running", return_value=False):
            yield

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

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = mock_payload
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            ret = handle_metrics(port=8080)
        assert ret == 0
        out = capsys.readouterr().out
        assert "HOLON COHERENCE OPTIMIZATION METRICS" in out
        assert "Tool Calls Saved / Pruned    : 12" in out
        assert "Tokens Reduced               : 350" in out
        assert "Cache Hit Rate               : 40.0%" in out
        assert "Average TTFT                 : 120.50 ms" in out
        assert "http://127.0.0.1:8080/holon/" in out

    def test_handle_metrics_live_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        payload = {"tool_calls_pruned": 8, "tokens_reduced": 200, "cache_hit_rate": 0.25}
        mock_resp = MagicMock()
        mock_resp.status = 200
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
            {
                "turn_id": 2,
                "cache_action": "MISS",
                "delta": {"tool_outputs_omitted": 3, "chars_saved": 800},
                "response": {
                    "usage": {
                        "input_tokens": 200,
                        "output_tokens": 100,
                        "cache_read_input_tokens": 0,
                        "reasoning_tokens": None,
                    }
                },
                "timing": {"ttft_ms": 100.0, "total_ms": 1100.0},
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
        assert data["tool_calls_pruned"] == 5
        assert data["tokens_reduced"] == 300
        assert data["cache_hits"] == 1
        assert data["total_requests"] == 2
        assert data["avg_decode_throughput_tps"] == 100.0
        assert data["total_reasoning_tokens"] == 0

    def test_handle_metrics_offline_fallback_holon_logs(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("WIRE_LOG_DIR", raising=False)
        fake_home = tmp_path / "home"
        holon_logs = fake_home / ".holon" / "logs"
        holon_logs.mkdir(parents=True)
        jsonl = holon_logs / "transactions.jsonl"
        record = {
            "turn_id": 1,
            "cache_action": "MISS",
            "delta": {"tool_outputs_omitted": 1, "chars_saved": 40},
            "response": {
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_read_input_tokens": 20,
                    "cache_creation_input_tokens": 10,
                    "reasoning_tokens": 5,
                }
            },
            "timing": {"ttft_ms": 200.0, "total_ms": 1200.0},
        }
        with open(jsonl, "w", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

        with (
            patch("os.path.expanduser", side_effect=lambda p: str(holon_logs) if "~/.holon/logs" in p else p),
            patch("urllib.request.urlopen", side_effect=OSError("connection refused")),
        ):
            ret = handle_metrics(json_output=True)
        assert ret == 0
        data = json.loads(capsys.readouterr().out)
        assert data["source"] == "offline_wire_log"
        assert data["avg_prefill_throughput_tps"] == 500.0  # 100 / 0.2s
        assert data["avg_tail_prefill_tps"] == 400.0  # 80 / 0.2s
        assert data["avg_decode_throughput_tps"] == 50.0  # 50 / 1.0s
        assert data["total_cache_creation_tokens"] == 10
        assert data["total_reasoning_tokens"] == 5

    def test_handle_metrics_offline_fallback_default_wire_log_dir(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("WIRE_LOG_DIR", raising=False)
        wire_logs = tmp_path / ".holon" / "mitm_wire_logs"
        wire_logs.mkdir(parents=True)
        record = {
            "turn_id": 1,
            "cache_action": "MISS",
            "delta": {"tool_outputs_omitted": 1, "chars_saved": 40},
            "response": {"usage": {"input_tokens": 100, "output_tokens": 50}},
            "timing": {"ttft_ms": 200.0, "total_ms": 1200.0},
        }
        (wire_logs / "transactions.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")

        with (
            patch("os.path.expanduser", side_effect=lambda p: str(tmp_path / "absent") if "~/.holon/logs" in p else p),
            patch("urllib.request.urlopen", side_effect=OSError("connection refused")),
        ):
            ret = handle_metrics(json_output=True)
        assert ret == 0
        data = json.loads(capsys.readouterr().out)
        assert data["source"] == "offline_wire_log"
        assert data["avg_prefill_throughput_tps"] == 500.0  # 100 / 0.2s

    def test_handle_metrics_no_offline_logs_hint_names_default_wire_log_dir(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.chdir(tmp_path)
        empty_logs = tmp_path / "empty"
        empty_logs.mkdir()
        monkeypatch.setenv("WIRE_LOG_DIR", str(empty_logs))

        with (
            patch("os.path.expanduser", side_effect=lambda p: str(tmp_path / "absent") if "~/.holon/logs" in p else p),
            patch("urllib.request.urlopen", side_effect=OSError("connection refused")),
        ):
            ret = handle_metrics(port=8080)
        assert ret == 1
        err = capsys.readouterr().err
        assert "No offline transaction logs found in WIRE_LOG_DIR, .holon/mitm_wire_logs or ~/.holon/logs." in err

    def test_handle_metrics_prefill_and_kv_cache_terminal_output(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_payload = json.dumps(
            {
                "total_turns": 3,
                "total_requests": 5,
                "cache_hits": 2,
                "cache_misses": 3,
                "cache_hit_rate": 0.4,
                "provider_cache_hit_rate": 0.75,
                "tool_calls_pruned": 6,
                "tokens_reduced": 100,
                "chars_saved": 400,
                "avg_ttft_ms": 150.0,
                "avg_decode_throughput_tps": 60.0,
                "avg_prefill_throughput_tps": 650.0,
                "latest_prefill_tps": 700.0,
                "avg_tail_prefill_tps": 200.0,
                "total_input_tokens": 2000,
                "total_output_tokens": 500,
                "total_cache_read_tokens": 1500,
                "total_cache_creation_tokens": 250,
                "total_reasoning_tokens": 40,
            }
        ).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = mock_payload
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            ret = handle_metrics(port=8080)
        assert ret == 0
        out = capsys.readouterr().out
        assert "Prefill Throughput           : 650.00 tokens/sec" in out
        assert "Latest: 700.00 t/s" in out
        assert "Tail Prefill Throughput      : 200.00 tokens/sec" in out
        assert "Decode Throughput            : 60.00 tokens/sec" in out
        assert "Cache Hit Rate               : 40.0%" in out
        assert "75.0% KV hit" in out
        assert "Cache Write Tokens           : 250" in out
        assert "Reasoning Tokens             : 40" in out

    def test_metrics_cli_dispatch(self) -> None:
        with (
            patch("holon_coherence.commands.metrics.handle_metrics", return_value=0) as mock_handle,
            pytest.raises(SystemExit) as exc,
        ):
            main(["metrics", "--json", "--port", "9999", "--offline", "--name", "custom-proxy"])
        assert exc.value.code == 0
        assert mock_handle.call_count == 1
        args = mock_handle.call_args[0][0]
        assert args.json is True
        assert args.port == 9999
        assert args.offline is True
        assert args.name == "custom-proxy"


class TestOfflineTelemetryThroughput:
    """Offline wire-log throughput arithmetic must mirror the live proxy."""

    @staticmethod
    def _write_records(tmp_path: Path, records: list[dict[str, Any]]) -> str:
        jsonl = tmp_path / "transactions.jsonl"
        with open(jsonl, "w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")
        return str(tmp_path)

    def test_legacy_non_streaming_window_below_floor_is_not_sampled(self, tmp_path: Path) -> None:
        """A 1.5ms ``total - ttft`` window is socket parse time, not 1,000,000 tokens/sec."""
        log_dir = self._write_records(
            tmp_path,
            [
                {
                    "turn_id": 1,
                    "cache_action": "MISS",
                    "delta": {},
                    "response": {"usage": {"input_tokens": 1_200_000, "output_tokens": 1_500}},
                    "timing": {"ttft_ms": 500.0, "total_ms": 501.5},
                }
            ],
        )

        data = _read_offline_metrics(log_dir)

        assert data is not None
        assert data["decode_samples"] == 0
        assert data["avg_decode_throughput_tps"] == 0.0
        assert data["latest_decode_throughput_tps"] == 0.0
        # Prefill still uses the genuine TTFT: 1,200,000 tokens over 0.5s.
        assert data["avg_prefill_throughput_tps"] == 2_400_000.0
        assert data["avg_ttft_ms"] == 500.0

    def test_legacy_plausible_window_is_still_admitted(self, tmp_path: Path) -> None:
        """Pre-0097 logs keep contributing decode samples when the window is physically credible."""
        log_dir = self._write_records(
            tmp_path,
            [
                {
                    "turn_id": 1,
                    "cache_action": "MISS",
                    "delta": {},
                    "response": {"usage": {"input_tokens": 100, "output_tokens": 50}},
                    "timing": {"ttft_ms": 200.0, "total_ms": 1200.0},
                },
                {
                    "turn_id": 2,
                    "cache_action": "MISS",
                    "delta": {},
                    "response": {"usage": {"input_tokens": 100, "output_tokens": 1500}},
                    "timing": {"ttft_ms": 200.0, "total_ms": 201.0},
                },
            ],
        )

        data = _read_offline_metrics(log_dir)

        assert data is not None
        # Only the 1.0s window is admitted (50 tokens / 1.0s), so the 1,500,000 tok/s artefact never
        # enters the average.
        assert data["decode_samples"] == 1
        assert data["avg_decode_throughput_tps"] == 50.0

    def test_streaming_decode_rate_is_honoured_and_non_streaming_ignored(self, tmp_path: Path) -> None:
        """Post-0097 records carry an explicit ``streaming`` flag plus the admitted rate."""
        log_dir = self._write_records(
            tmp_path,
            [
                {
                    "turn_id": 1,
                    "cache_action": "MISS",
                    "delta": {},
                    "response": {"usage": {"input_tokens": 1000, "output_tokens": 100}},
                    "timing": {
                        "ttft_ms": 500.0,
                        "total_ms": 900.0,
                        "streaming": True,
                        "generation_ms": 400.0,
                        "prefill_tps": 2000.0,
                        "tail_prefill_tps": 2000.0,
                        "decode_tps": 250.0,
                    },
                },
                {
                    "turn_id": 2,
                    "cache_action": "MISS",
                    "delta": {},
                    "response": {"usage": {"input_tokens": 2000, "output_tokens": 200}},
                    "timing": {
                        "ttft_ms": 400.0,
                        "total_ms": 401.0,
                        "streaming": False,
                        "generation_ms": None,
                        "prefill_tps": 5000.0,
                        "tail_prefill_tps": 5000.0,
                        "decode_tps": None,
                    },
                },
            ],
        )

        data = _read_offline_metrics(log_dir)

        assert data is not None
        assert data["decode_samples"] == 1
        assert data["avg_decode_throughput_tps"] == 250.0
        assert data["latest_decode_throughput_tps"] == 250.0
        assert data["avg_prefill_throughput_tps"] == 3500.0
        assert data["latest_prefill_tps"] == 5000.0
        assert data["latest_ttft_ms"] == 400.0
        assert data["latest_total_time_ms"] == 401.0

    def test_unmeasured_prefill_rate_falls_back_to_recorded_ttft(self, tmp_path: Path) -> None:
        """Records with ``prefill_tps: null`` still derive prefill speed from a real TTFT."""
        log_dir = self._write_records(
            tmp_path,
            [
                {
                    "turn_id": 1,
                    "cache_action": "MISS",
                    "delta": {},
                    "response": {"usage": {"input_tokens": 900, "output_tokens": 0, "cache_read_input_tokens": 300}},
                    "timing": {"ttft_ms": 300.0, "total_ms": 300.0, "streaming": False, "prefill_tps": None},
                }
            ],
        )

        data = _read_offline_metrics(log_dir)

        assert data is not None
        assert data["avg_prefill_throughput_tps"] == 3000.0  # 900 / 0.3s
        assert data["avg_tail_prefill_tps"] == 2000.0  # 600 uncached / 0.3s

    def test_stored_zero_rate_stays_unmeasured_instead_of_re_derived(self, tmp_path: Path) -> None:
        """A stored ``0.0`` rate is *unmeasured* and must not be re-derived from the recorded TTFT."""
        log_dir = self._write_records(
            tmp_path,
            [
                {
                    "turn_id": 1,
                    "cache_action": "MISS",
                    "delta": {},
                    "response": {"usage": {"input_tokens": 900, "output_tokens": 0, "cache_read_input_tokens": 300}},
                    "timing": {
                        "ttft_ms": 300.0,
                        "total_ms": 300.0,
                        "streaming": False,
                        "prefill_tps": 0.0,
                        "tail_prefill_tps": 0.0,
                    },
                },
                {
                    "turn_id": 2,
                    "cache_action": "MISS",
                    "delta": {},
                    "response": {"usage": {"input_tokens": 1000, "output_tokens": 0, "cache_read_input_tokens": 0}},
                    "timing": {
                        "ttft_ms": 200.0,
                        "total_ms": 200.0,
                        "streaming": False,
                        "prefill_tps": 5000.0,
                        "tail_prefill_tps": 5000.0,
                    },
                },
            ],
        )

        data = _read_offline_metrics(log_dir)

        assert data is not None
        # The 0.0 record contributes its timing only, never a rate, so the average is the 5000 t/s
        # sample alone -- not (3000 derived + 5000) / 2 = 4000.
        assert data["avg_prefill_throughput_tps"] == 5000.0
        assert data["avg_tail_prefill_tps"] == 5000.0
        assert data["latest_prefill_tps"] == 5000.0
        assert data["avg_ttft_ms"] == 250.0  # (300 + 200) / 2

    def test_live_and_offline_metric_surfaces_agree(self, tmp_path: Path) -> None:
        """The in-memory proxy and the offline parser must publish identical numbers."""
        log_dir = self._write_records(
            tmp_path,
            [
                {
                    "turn_id": 1,
                    "cache_action": "MISS",
                    "delta": {"tool_outputs_omitted": 2, "chars_saved": 400},
                    "response": {
                        "usage": {
                            "input_tokens": 1000,
                            "output_tokens": 100,
                            "cache_read_input_tokens": 200,
                            "cache_creation_input_tokens": 50,
                            "reasoning_tokens": 10,
                        }
                    },
                    "timing": {
                        "ttft_ms": 500.0,
                        "total_ms": 900.0,
                        "streaming": True,
                        "generation_ms": 400.0,
                        "prefill_tps": 2000.0,
                        "tail_prefill_tps": 1600.0,
                        "decode_tps": 250.0,
                    },
                },
                {
                    "turn_id": 2,
                    "cache_action": "MISS",
                    "delta": {"tool_outputs_omitted": 1, "chars_saved": 200},
                    "response": {
                        "usage": {
                            "input_tokens": 2000,
                            "output_tokens": 200,
                            "cache_read_input_tokens": 1000,
                            "cache_creation_input_tokens": 0,
                            "reasoning_tokens": 0,
                        }
                    },
                    "timing": {
                        "ttft_ms": 400.0,
                        "total_ms": 401.0,
                        "streaming": False,
                        "generation_ms": 1.0,
                        "prefill_tps": 5000.0,
                        "tail_prefill_tps": 2500.0,
                        "decode_tps": None,
                    },
                },
            ],
        )

        offline = _read_offline_metrics(log_dir)

        live = CumulativeMetrics()
        live.record_request()
        live.record_request()
        live.record_cleaner(
            SimpleNamespace(
                tool_outputs_omitted=3,
                chars_saved=600,
                turns_summarized=0,
                cache_control_injected=0,
            )
        )
        live.record_response(
            input_tokens=1000,
            output_tokens=100,
            cache_read_tokens=200,
            cache_creation_tokens=50,
            reasoning_tokens=10,
            ttft=0.5,
            output_tps=250.0,
            prefill_tps=2000.0,
            tail_prefill_tps=1600.0,
            total_time=0.9,
        )
        live.record_response(
            input_tokens=2000,
            output_tokens=200,
            cache_read_tokens=1000,
            cache_creation_tokens=0,
            reasoning_tokens=0,
            ttft=0.4,
            output_tps=None,
            prefill_tps=5000.0,
            tail_prefill_tps=2500.0,
            total_time=0.401,
        )
        live_dict = live.to_dict()

        assert offline is not None
        shared_keys = [
            "total_requests",
            "total_turns",
            "cache_hits",
            "cache_misses",
            "cache_hit_rate",
            "provider_cache_hit_rate",
            "tool_calls_pruned",
            "tokens_reduced",
            "chars_saved",
            "avg_ttft_ms",
            "avg_decode_throughput_tps",
            "latest_decode_throughput_tps",
            "decode_samples",
            "avg_prefill_throughput_tps",
            "latest_prefill_tps",
            "avg_tail_prefill_tps",
            "latest_tail_prefill_tps",
            "latest_ttft_ms",
            "latest_total_time_ms",
            "total_input_tokens",
            "total_output_tokens",
            "total_cache_read_tokens",
            "total_cache_creation_tokens",
            "total_reasoning_tokens",
        ]
        for key in shared_keys:
            assert offline[key] == live_dict[key], f"{key}: offline={offline[key]} live={live_dict[key]}"
