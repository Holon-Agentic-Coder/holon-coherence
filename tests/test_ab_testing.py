"""Unit and integration tests for holon-coherence A/B testing suite (Bean 0098)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from holon_coherence.cli import main
from holon_coherence.commands.ab_test import (
    evaluate_offline_ab_run,
    load_trace_transactions,
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
        assert scorecard.optimized_ttft_ms is not None
        assert scorecard.ttft_delta_ms is not None and scorecard.ttft_delta_ms < 0

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

    def test_semantic_parity_failure_detection(self) -> None:
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
        assert "Semantic Parity Check:       ✅ PASSED" in table
        assert "CI Reduction Gate:           ✅ PASSED" in table

    def test_scorecard_to_dict_serialization(self, sample_trace_records: list[dict]) -> None:
        scorecard = evaluate_offline_ab_run(sample_trace_records)
        data = scorecard.to_dict()

        assert "summary" in data
        assert "turns" in data
        assert data["summary"]["total_turns"] == 2
        assert "token_reduction_pct" in data["summary"]
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
