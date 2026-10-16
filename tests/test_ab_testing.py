"""Unit and integration tests for holon-coherence A/B testing suite (Bean 0098)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from holon_coherence.cli import main
from holon_coherence.commands.ab_test import (
    evaluate_offline_ab_run,
    evaluate_runs,
    load_trace_transactions,
    load_transactions_from_path,
)


@pytest.fixture
def sample_trace_records() -> list[dict]:
    """Sample authentic trace records representing multi-turn agent tool executions."""
    large_file_content = (
        "def compute_hash(data: str) -> str:\n"
        "    import hashlib\n"
        "    return hashlib.sha256(data.encode()).hexdigest()\n"
    ) * 30  # ~2.4KB content

    return [
        {
            "turn_id": "turn-1",
            "provider": "anthropic",
            "cache_action": "MISS",
            "raw_request": {
                "request": {
                    "messages": [
                        {"role": "user", "content": "Please view the file content."},
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": "call_1",
                                    "content": large_file_content,
                                }
                            ],
                        },
                        {"role": "assistant", "content": "I see the compute_hash function."},
                    ]
                }
            },
            "response": {
                "usage": {
                    "input_tokens": 1200,
                    "output_tokens": 25,
                }
            },
            "timing": {
                "ttft_ms": 1450.5,
            },
        },
        {
            "turn_id": "turn-2",
            "provider": "anthropic",
            "cache_action": "HIT",
            "raw_request": {
                "request": {
                    "messages": [
                        {"role": "user", "content": "Please view the file content."},
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": "call_1",
                                    "content": large_file_content,
                                }
                            ],
                        },
                        {"role": "assistant", "content": "I see the compute_hash function."},
                        {"role": "user", "content": "View it again for verification."},
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": "call_2",
                                    "content": large_file_content,
                                }
                            ],
                        },
                        {"role": "assistant", "content": "Verified."},
                        {"role": "user", "content": "Proceed with implementation."},
                        {"role": "assistant", "content": "Implementing requested changes."},
                    ]
                }
            },
            "response": {
                "usage": {
                    "input_tokens": 2400,
                    "output_tokens": 15,
                }
            },
            "timing": {
                "ttft_ms": 2300.2,
            },
        },
    ]


@pytest.fixture
def jsonl_trace_file(tmp_path: Path, sample_trace_records: list[dict]) -> Path:
    """Create a temporary .jsonl trace file with sample transactions."""
    trace_path = tmp_path / "transactions.jsonl"
    with open(trace_path, "w", encoding="utf-8") as f:
        for rec in sample_trace_records:
            f.write(json.dumps(rec) + "\n")
    return trace_path


@pytest.fixture
def json_array_trace_file(tmp_path: Path, sample_trace_records: list[dict]) -> Path:
    """Create a temporary .json array trace file with sample transactions."""
    trace_path = tmp_path / "transactions.json"
    with open(trace_path, "w", encoding="utf-8") as f:
        json.dump(sample_trace_records, f)
    return trace_path


class TestTraceLoading:
    """Tests for authentic trace loading across formats."""

    def test_load_jsonl_trace(self, jsonl_trace_file: Path) -> None:
        records = load_trace_transactions(str(jsonl_trace_file))
        assert len(records) == 2
        assert records[0]["turn_id"] == "turn-1"
        assert records[1]["turn_id"] == "turn-2"

    def test_load_json_array_trace(self, json_array_trace_file: Path) -> None:
        records = load_trace_transactions(str(json_array_trace_file))
        assert len(records) == 2
        assert records[0]["turn_id"] == "turn-1"

    def test_load_json_array_with_utf8_bom(self, tmp_path: Path, sample_trace_records: list[dict]) -> None:
        trace_path = tmp_path / "transactions_bom.json"
        with open(trace_path, "w", encoding="utf-8-sig") as f:
            json.dump(sample_trace_records, f)
        records = load_trace_transactions(str(trace_path))
        assert len(records) == 2
        assert records[0]["turn_id"] == "turn-1"

    def test_load_jsonl_with_blank_lines_and_comments(self, tmp_path: Path) -> None:
        trace_path = tmp_path / "mixed.jsonl"
        with open(trace_path, "w", encoding="utf-8") as f:
            f.write("\n")
            f.write(json.dumps({"turn_id": "t1", "raw_request": {"request": {"messages": []}}}) + "\n")
            f.write("   \n")
            f.write(json.dumps({"turn_id": "t2", "raw_request": {"request": {"messages": []}}}) + "\n")

        records = load_trace_transactions(str(trace_path))
        assert len(records) == 2

    def test_load_missing_file_raises(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.jsonl"
        with pytest.raises(FileNotFoundError, match="Trace file not found"):
            load_trace_transactions(str(missing))

    def test_load_empty_file_raises(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.jsonl"
        empty.write_text("")
        with pytest.raises(ValueError, match="No valid transaction records found"):
            load_trace_transactions(str(empty))


class TestOfflineABEvaluation:
    """Tests for differential A/B evaluation mechanics."""

    def test_evaluate_token_reduction_on_repetitive_tool_calls(self, sample_trace_records: list[dict]) -> None:
        scorecard = evaluate_offline_ab_run(
            transactions=sample_trace_records,
            rounds=1,
            fail_under_reduction=15.0,
        )

        assert scorecard.total_turns == 2
        assert scorecard.baseline_input_tokens == 3600
        assert scorecard.optimized_input_tokens < scorecard.baseline_input_tokens
        assert scorecard.tokens_reduced > 0
        assert scorecard.token_reduction_pct > 20.0
        assert scorecard.tool_calls_pruned >= 1
        assert scorecard.semantic_parity_verified is True
        assert scorecard.passed_threshold is True
        assert scorecard.baseline_ttft_ms is not None
        # Rule 10 Invariant: Zero synthetic TTFT in offline mode (no upstream API calls dispatched)
        assert scorecard.optimized_ttft_ms is None
        assert scorecard.ttft_delta_ms is None
        assert scorecard.cache_control_injected > 0
        assert scorecard.cache_hits == 1
        assert scorecard.cache_hit_rate == 50.0

    def test_evaluate_rounds_scaling(self, sample_trace_records: list[dict]) -> None:
        scorecard_1 = evaluate_offline_ab_run(sample_trace_records, rounds=1)
        scorecard_3 = evaluate_offline_ab_run(sample_trace_records, rounds=3)

        assert scorecard_3.total_turns == scorecard_1.total_turns * 3
        assert scorecard_3.baseline_input_tokens == scorecard_1.baseline_input_tokens * 3
        assert scorecard_3.optimized_input_tokens == scorecard_1.optimized_input_tokens * 3

    def test_fail_under_reduction_threshold(self, sample_trace_records: list[dict]) -> None:
        # Should pass when threshold is low (e.g. 5%)
        passing_scorecard = evaluate_offline_ab_run(
            sample_trace_records,
            fail_under_reduction=5.0,
        )
        assert passing_scorecard.passed_threshold is True

        # Should fail when threshold is unrealistically high (e.g. 95%)
        failing_scorecard = evaluate_offline_ab_run(
            sample_trace_records,
            fail_under_reduction=95.0,
        )
        assert failing_scorecard.passed_threshold is False

    def test_semantic_parity_failure_on_empty_messages(self) -> None:
        corrupted_record = [
            {
                "turn_id": "turn-bad",
                "provider": "anthropic",
                "raw_request": {"request": {"messages": [{"role": "user", "content": "Hello world"}]}},
            }
        ]

        class BrokenCleaner:
            def process_payload_with_stats(self, payload: dict, provider: str = "anthropic") -> Any:
                from holon_coherence.payload_cleaner import CleaningResult

                # Intentionally strips all messages to break semantic parity
                return CleaningResult(
                    payload={"messages": []},
                    tool_outputs_omitted=0,
                    turns_summarized=0,
                    cache_control_injected=0,
                    chars_saved=100,
                )

        scorecard = evaluate_offline_ab_run(
            transactions=corrupted_record,
            cleaner=BrokenCleaner(),  # type: ignore[arg-type]
        )
        assert scorecard.semantic_parity_verified is False

    def test_semantic_parity_failure_on_missing_messages_key(self) -> None:
        record = [
            {
                "turn_id": "turn-key-dropped",
                "provider": "anthropic",
                "raw_request": {"request": {"messages": [{"role": "user", "content": "Hello"}]}},
            }
        ]

        class MissingKeyCleaner:
            def process_payload_with_stats(self, payload: dict, provider: str = "anthropic") -> Any:
                from holon_coherence.payload_cleaner import CleaningResult

                # Drops messages key completely
                return CleaningResult(
                    payload={},
                    tool_outputs_omitted=0,
                    turns_summarized=0,
                    cache_control_injected=0,
                    chars_saved=50,
                )

        scorecard = evaluate_offline_ab_run(transactions=record, cleaner=MissingKeyCleaner())  # type: ignore[arg-type]
        assert scorecard.semantic_parity_verified is False

    def test_semantic_parity_failure_on_mutated_active_role(self) -> None:
        record = [
            {
                "turn_id": "turn-role-mutated",
                "provider": "anthropic",
                "raw_request": {
                    "request": {
                        "messages": [
                            {"role": "user", "content": "Task 1"},
                            {"role": "assistant", "content": "Response 1"},
                        ]
                    }
                },
            }
        ]

        class RoleMutatingCleaner:
            def process_payload_with_stats(self, payload: dict, provider: str = "anthropic") -> Any:
                from holon_coherence.payload_cleaner import CleaningResult

                return CleaningResult(
                    payload={
                        "messages": [
                            {"role": "user", "content": "Task 1"},
                            {"role": "user", "content": "Response 1"},  # Role mutated from assistant to user
                        ]
                    },
                    tool_outputs_omitted=0,
                    turns_summarized=0,
                    cache_control_injected=0,
                    chars_saved=0,
                )

        scorecard = evaluate_offline_ab_run(transactions=record, cleaner=RoleMutatingCleaner())  # type: ignore[arg-type]
        assert scorecard.semantic_parity_verified is False


class TestScorecardPresentation:
    """Tests for human-readable and machine-readable scorecard presentation."""

    def test_scorecard_render_table(self, sample_trace_records: list[dict]) -> None:
        scorecard = evaluate_offline_ab_run(
            sample_trace_records,
            fail_under_reduction=20.0,
        )
        table = scorecard.render_table()

        assert "HOLON COHERENCE A/B BENCHMARK SCORECARD" in table
        assert "Baseline (Control)" in table
        assert "Optimized" in table
        assert "Net Tokens Reduced:" in table
        assert "Prompt Cache Breakpoints:" in table
        assert "Baseline TTFT (Recorded):" in table
        assert "Semantic Parity Check:       ✅ PASSED" in table
        assert "CI Reduction Gate:           ✅ PASSED" in table

    def test_scorecard_to_dict_serialization(self, sample_trace_records: list[dict]) -> None:
        scorecard = evaluate_offline_ab_run(sample_trace_records)
        data = scorecard.to_dict()

        assert "summary" in data
        assert "turns" in data
        assert data["summary"]["total_turns"] == 2
        assert "token_reduction_pct" in data["summary"]
        assert "cache_control_injected" in data["summary"]
        assert len(data["turns"]) == 2
        assert data["turns"][0]["turn_id"] == "turn-1"
        assert data["turns"][0]["semantic_parity"] is True


class TestABTestCLI:
    """Integration tests for the holon-coherence ab-test CLI command."""

    def test_cli_ab_test_json_output(self, jsonl_trace_file: Path, capsys: pytest.CaptureFixture) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(["ab-test", "--trace-file", str(jsonl_trace_file), "--json"])

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "summary" in data
        assert data["summary"]["total_turns"] == 2
        assert data["summary"]["tokens_reduced"] > 0
        assert data["summary"]["cache_control_injected"] > 0

    def test_cli_ab_test_human_table_output(self, jsonl_trace_file: Path, capsys: pytest.CaptureFixture) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(["ab-test", "-f", str(jsonl_trace_file)])

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "HOLON COHERENCE A/B BENCHMARK SCORECARD" in captured.out
        assert "Semantic Parity Check" in captured.out

    def test_cli_ab_test_pass_threshold(self, jsonl_trace_file: Path, capsys: pytest.CaptureFixture) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(
                [
                    "ab-test",
                    "-f",
                    str(jsonl_trace_file),
                    "--fail-under-reduction",
                    "10.0",
                ]
            )

        assert exc_info.value.code == 0

    def test_cli_ab_test_fail_threshold(self, jsonl_trace_file: Path, capsys: pytest.CaptureFixture) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(
                [
                    "ab-test",
                    "-f",
                    str(jsonl_trace_file),
                    "--fail-under-reduction",
                    "99.0",
                ]
            )

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "A/B Test Failed: Reduction" in captured.err

    def test_cli_missing_trace_file(self, capsys: pytest.CaptureFixture) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(["ab-test", "-f", "/path/does/not/exist.jsonl"])

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Error loading trace transactions" in captured.err

    def test_cli_invalid_threshold_value(self, jsonl_trace_file: Path, capsys: pytest.CaptureFixture) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(["ab-test", "-f", str(jsonl_trace_file), "--fail-under-reduction", "invalid"])

        # argparse catches non-float before handler
        assert exc_info.value.code != 0

    def test_cli_no_args_shows_error(self, capsys: pytest.CaptureFixture) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(["ab-test"])

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "One of --command (-c), --trace-file (-f), or both --baseline and --optimized" in captured.err

    def test_cli_baseline_and_optimized_dirs(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        base_dir = tmp_path / "baseline_wire"
        opt_dir = tmp_path / "optimized_wire"
        base_dir.mkdir()
        opt_dir.mkdir()

        base_tx = {
            "turn_id": "turn-1",
            "provider": "anthropic",
            "mode": "baseline",
            "raw_request": {"request": {"messages": [{"role": "user", "content": "test payload"}]}},
            "response": {"status": 200, "usage": {"input_tokens": 1500}},
            "timing": {"ttft_ms": 1100.0, "decode_tps": 40.0},
        }
        opt_tx = {
            "turn_id": "turn-1",
            "provider": "anthropic",
            "mode": "optimized",
            "raw_request": {"request": {"messages": [{"role": "user", "content": "test payload"}]}},
            "cleaned_request": {"request": {"messages": [{"role": "user", "content": "test payload"}]}},
            "delta": {"tool_outputs_omitted": 1, "cache_control_injected": 2},
            "response": {"status": 200, "usage": {"input_tokens": 1000, "cache_read_input_tokens": 500}},
            "timing": {"ttft_ms": 750.0, "decode_tps": 52.0},
        }

        with open(base_dir / "transactions.jsonl", "w", encoding="utf-8") as f:
            f.write(json.dumps(base_tx) + "\n")
        with open(opt_dir / "transactions.jsonl", "w", encoding="utf-8") as f:
            f.write(json.dumps(opt_tx) + "\n")

        with pytest.raises(SystemExit) as exc_info:
            main(["ab-test", "--baseline", str(base_dir), "--optimized", str(opt_dir), "--json"])

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        summary = data["summary"]
        assert summary["total_turns"] == 1
        assert summary["tokens_reduced"] == 500
        assert summary["baseline_ttft_ms"] == 1100.0
        assert summary["optimized_ttft_ms"] == 750.0
        assert summary["ttft_delta_ms"] == 350.0
        assert summary["baseline_decode_tps"] == 40.0
        assert summary["optimized_decode_tps"] == 52.0
        assert summary["semantic_parity_verified"] is True

    def test_cli_mixed_trace_file(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        trace_file = tmp_path / "mixed_trace.jsonl"
        base_tx = {
            "turn_id": "turn-1",
            "provider": "anthropic",
            "mode": "baseline",
            "raw_request": {"messages": [{"role": "user", "content": "hello"}]},
            "response": {"status": 200, "usage": {"input_tokens": 800}},
            "timing": {"ttft_ms": 950.0},
        }
        opt_tx = {
            "turn_id": "turn-1",
            "provider": "anthropic",
            "mode": "optimized",
            "raw_request": {"messages": [{"role": "user", "content": "hello"}]},
            "cleaned_request": {"messages": [{"role": "user", "content": "hello"}]},
            "response": {"status": 200, "usage": {"input_tokens": 600}},
            "timing": {"ttft_ms": 650.0},
        }
        with open(trace_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(base_tx) + "\n")
            f.write(json.dumps(opt_tx) + "\n")

        with pytest.raises(SystemExit) as exc_info:
            main(["ab-test", "-f", str(trace_file)])

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "HOLON COHERENCE A/B BENCHMARK SCORECARD" in captured.out
        assert "Source: Real Intercepted Traffic (Mixed Trace)" in captured.out
        assert "Avg TTFT:                   Baseline: 950.0ms | Optimized: 650.0ms" in captured.out


class TestPathAndDirectoryLoading:
    """Tests for load_transactions_from_path supporting directories and files."""

    def test_load_from_directory_with_transactions_jsonl(self, tmp_path: Path) -> None:
        dir_path = tmp_path / "run_logs"
        dir_path.mkdir()
        jsonl = dir_path / "transactions.jsonl"
        with open(jsonl, "w", encoding="utf-8") as f:
            f.write(json.dumps({"turn_id": "t1"}) + "\n")
            f.write(json.dumps({"turn_id": "t2"}) + "\n")

        txs = load_transactions_from_path(str(dir_path))
        assert len(txs) == 2
        assert txs[0]["turn_id"] == "t1"
        assert txs[1]["turn_id"] == "t2"

    def test_load_from_directory_with_turn_json_files(self, tmp_path: Path) -> None:
        dir_path = tmp_path / "turn_logs"
        dir_path.mkdir()
        with open(dir_path / "turn_1.json", "w", encoding="utf-8") as f:
            json.dump({"turn_id": "turn-1"}, f)
        with open(dir_path / "turn_2.json", "w", encoding="utf-8") as f:
            json.dump({"turn_id": "turn-2"}, f)

        txs = load_transactions_from_path(str(dir_path))
        assert len(txs) == 2

    def test_load_from_empty_directory_raises(self, tmp_path: Path) -> None:
        empty_dir = tmp_path / "empty_dir"
        empty_dir.mkdir()
        with pytest.raises(ValueError, match="No valid transaction records found in directory"):
            load_transactions_from_path(str(empty_dir))

    def test_load_from_missing_path_raises(self) -> None:
        with pytest.raises(FileNotFoundError, match="Trace path not found"):
            load_transactions_from_path("/nonexistent/path/dir")


class TestRealTrafficRunsEvaluation:
    """Tests for evaluate_runs comparing authentic baseline and optimized runs."""

    def test_evaluate_runs_authentic_metrics(self) -> None:
        base_txs = [
            {
                "turn_id": "turn-1",
                "provider": "anthropic",
                "mode": "baseline",
                "raw_request": {"request": {"messages": [{"role": "user", "content": "hi"}]}},
                "response": {"status": 200, "usage": {"input_tokens": 2000}},
                "timing": {"ttft_ms": 1200.0, "decode_tps": 45.0},
            }
        ]
        opt_txs = [
            {
                "turn_id": "turn-1",
                "provider": "anthropic",
                "mode": "optimized",
                "raw_request": {"request": {"messages": [{"role": "user", "content": "hi"}]}},
                "cleaned_request": {"request": {"messages": [{"role": "user", "content": "hi"}]}},
                "delta": {"tool_outputs_omitted": 1, "cache_control_injected": 2},
                "cache_action": "HIT",
                "response": {"status": 200, "usage": {"input_tokens": 1500}},
                "timing": {"ttft_ms": 900.0, "decode_tps": 55.0},
            }
        ]

        scorecard = evaluate_runs(
            baseline_transactions=base_txs,
            optimized_transactions=opt_txs,
            fail_under_reduction=15.0,
        )

        assert scorecard.total_turns == 1
        assert scorecard.baseline_input_tokens == 2000
        assert scorecard.optimized_input_tokens == 1500
        assert scorecard.tokens_reduced == 500
        assert scorecard.token_reduction_pct == 25.0
        assert scorecard.baseline_ttft_ms == 1200.0
        assert scorecard.optimized_ttft_ms == 900.0
        assert scorecard.ttft_delta_ms == 300.0
        assert scorecard.baseline_decode_tps == 45.0
        assert scorecard.optimized_decode_tps == 55.0
        assert scorecard.cache_hits == 1
        assert scorecard.cache_hit_rate == 100.0
        assert scorecard.semantic_parity_verified is True
        assert scorecard.passed_threshold is True

    def test_evaluate_runs_zero_turns_raises(self) -> None:
        with pytest.raises(ValueError, match="Cannot evaluate A/B test with zero paired turns"):
            evaluate_runs([], [])

    def test_evaluate_runs_parity_failure_on_status_error(self) -> None:
        base_txs = [
            {
                "turn_id": "turn-err",
                "provider": "anthropic",
                "raw_request": {"request": {"messages": [{"role": "user", "content": "hi"}]}},
                "response": {"status": 500, "usage": {"input_tokens": 100}},
            }
        ]
        opt_txs = [
            {
                "turn_id": "turn-err",
                "provider": "anthropic",
                "raw_request": {"request": {"messages": [{"role": "user", "content": "hi"}]}},
                "response": {"status": 200, "usage": {"input_tokens": 80}},
            }
        ]
        scorecard = evaluate_runs(base_txs, opt_txs)
        assert scorecard.semantic_parity_verified is False
