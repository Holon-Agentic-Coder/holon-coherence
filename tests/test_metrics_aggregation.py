from __future__ import annotations

import ast
import io
import json
import tokenize
from pathlib import Path
from types import SimpleNamespace

from holon_coherence.ab_testing.evaluation import (
    ABComparisonScorecard,
    AbEvaluation,
    AbRun,
)
from holon_coherence.metrics.aggregation import (
    OfflineMetricsAccumulator,
    _compute_metrics_summary,
    _milliseconds_to_seconds,
    _process_record_cache_and_deltas,
    _process_record_timing,
    _process_record_usage,
    _stored_rate,
    read_offline_metrics,
)
from holon_coherence.proxy.metrics import CumulativeMetrics

REPO_ROOT = Path(__file__).resolve().parents[1]

METRICS_AND_AB_SELF_DOC_FILES = (
    "src/holon_coherence/metrics/__init__.py",
    "src/holon_coherence/metrics/aggregation.py",
    "src/holon_coherence/metrics_math.py",
    "src/holon_coherence/ab_testing/__init__.py",
    "src/holon_coherence/ab_testing/evaluation.py",
    "tests/test_metrics_aggregation.py",
    "tests/test_ab_testing_domain.py",
    "tests/test_ab_testing.py",
)

ALLOWED_COMMENT_PREFIXES = (
    "# noqa",
    "# type: ignore",
    "# pragma: no cover",
    "# pyright:",
    "# mypy:",
    "#!",
    "# -*-",
    "# vim:",
    "# SPDX-License-Identifier:",
)


def _find_docstring_violations(source: str, rel_path: str) -> list[str]:
    tree = ast.parse(source, filename=rel_path)
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None:
                lineno = getattr(node, "lineno", 1)
                name = getattr(node, "name", "<module>")
                violations.append(f"{rel_path}:{lineno} ({name})")
    return violations


def _is_allowed_comment(comment_text: str) -> bool:
    stripped = comment_text.strip()
    return any(stripped.startswith(prefix) for prefix in ALLOWED_COMMENT_PREFIXES)


def _find_disallowed_comments(source: str, rel_path: str) -> list[str]:
    violations: list[str] = []
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    for tok_type, tok_str, (lineno, _), _, _ in tokens:
        if tok_type == tokenize.COMMENT and not _is_allowed_comment(tok_str):
            violations.append(f"{rel_path}:{lineno}: {tok_str}")
    return violations


def test_ab_testing_domain_aliases() -> None:
    assert AbRun is not None
    scorecard = AbEvaluation(total_turns=2, baseline_input_tokens=1000, optimized_input_tokens=800)
    assert isinstance(scorecard, ABComparisonScorecard)
    assert scorecard.format_console() == scorecard.render_table()
    data = scorecard.to_dict()
    assert data["summary"]["total_turns"] == 2


def test_milliseconds_to_seconds_and_stored_rate() -> None:
    assert _milliseconds_to_seconds(None) is None
    assert _milliseconds_to_seconds("invalid") is None
    assert _milliseconds_to_seconds(1500) == 1.5

    assert _stored_rate(45.5, 30.0) == 45.5
    assert _stored_rate(None, 30.0) == 30.0
    assert _stored_rate(0.0, 30.0) is None


def test_read_offline_metrics_nonexistent(tmp_path: Path) -> None:
    assert read_offline_metrics(str(tmp_path / "nonexistent")) is None


def test_read_offline_metrics_empty(tmp_path: Path) -> None:
    log_file = tmp_path / "transactions.jsonl"
    log_file.write_text("\n\n   \n", encoding="utf-8")
    assert read_offline_metrics(str(tmp_path)) is None


def test_read_offline_metrics_authentic_records(tmp_path: Path) -> None:
    records = [
        {
            "turn_id": "turn-1",
            "cache_action": "HIT",
            "delta": {
                "tool_outputs_omitted": 2,
                "chars_saved": 400,
                "turns_summarized": 1,
                "cache_control_injected": 1,
            },
            "response": {
                "usage": {
                    "input_tokens": 1000,
                    "output_tokens": 200,
                    "cache_read_input_tokens": 600,
                    "cache_creation_input_tokens": 100,
                    "reasoning_tokens": 50,
                }
            },
            "timing": {
                "ttft_ms": 250.0,
                "total_ms": 1250.0,
                "prefill_tps": 4000.0,
                "tail_prefill_tps": 1600.0,
                "decode_tps": 200.0,
            },
        },
        {
            "turn_id": "turn-2",
            "cache_action": "MISS",
            "delta": {
                "tool_outputs_omitted": 1,
                "chars_saved": 200,
                "turns_summarized": 0,
                "cache_control_injected": 0,
            },
            "response": {
                "usage": {
                    "input_tokens": 1500,
                    "output_tokens": 300,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                    "reasoning_tokens": 0,
                }
            },
            "timing": {
                "ttft_ms": 500.0,
                "total_ms": 2000.0,
                "decode_tps": 200.0,
            },
        },
    ]

    log_file = tmp_path / "transactions.jsonl"
    unparseable_jsonl_line = "{invalid json line\n"
    with log_file.open("w", encoding="utf-8") as f:
        f.write(unparseable_jsonl_line)
        for r in records:
            f.write(json.dumps(r) + "\n")

    summary = read_offline_metrics(str(tmp_path))
    assert summary is not None
    assert summary["total_requests"] == 2
    assert summary["total_turns"] == 2
    assert summary["cache_hits"] == 1
    assert summary["cache_misses"] == 1
    assert summary["cache_hit_rate"] == 0.5
    assert summary["tool_calls_pruned"] == 3
    assert summary["chars_saved"] == 600
    assert summary["tokens_reduced"] == 150
    assert summary["turns_summarized"] == 1
    assert summary["cache_control_injected"] == 1
    assert summary["total_input_tokens"] == 2500
    assert summary["total_output_tokens"] == 500
    assert summary["total_cache_read_tokens"] == 600
    assert summary["total_cache_creation_tokens"] == 100
    assert summary["total_reasoning_tokens"] == 50
    assert summary["provider_cache_hit_rate"] == 0.24
    assert summary["avg_ttft_ms"] == 375.0
    assert summary["avg_decode_throughput_tps"] == 200.0
    assert summary["source"] == "offline_wire_log"


def test_offline_metrics_accumulator_subroutines() -> None:
    state = OfflineMetricsAccumulator()
    rec = {
        "turn_id": "test-1",
        "cache_action": "HIT",
        "delta": {"tool_outputs_omitted": 4, "chars_saved": 800},
        "response": {"usage": {"input_tokens": 500, "output_tokens": 100}},
        "timing": {"ttft_ms": 100.0, "total_ms": 600.0},
    }

    _process_record_cache_and_deltas(rec, state)
    in_toks, out_toks, cache_read = _process_record_usage(rec, state)
    _process_record_timing(rec, in_toks, out_toks, cache_read, state)

    assert state.total_requests == 1
    assert state.cache_hits == 1
    assert state.tool_calls_pruned == 4
    assert state.chars_saved == 800
    assert state.total_input_tokens == 500
    assert state.total_output_tokens == 100

    summary = _compute_metrics_summary(state)
    assert summary["tokens_reduced"] == 200
    assert summary["avg_ttft_ms"] == 100.0


def test_offline_accumulator_matches_live_cumulative_metrics(tmp_path: Path) -> None:
    shared_keys = (
        "total_turns",
        "total_requests",
        "cache_hits",
        "cache_misses",
        "cache_hit_rate",
        "provider_cache_hit_rate",
        "tool_calls_pruned",
        "tokens_reduced",
        "chars_saved",
        "turns_summarized",
        "cache_control_injected",
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
    )
    records = [
        {
            "turn_id": "turn-a",
            "cache_action": "HIT",
            "delta": {
                "tool_outputs_omitted": 3,
                "chars_saved": 800,
                "turns_summarized": 1,
                "cache_control_injected": 1,
            },
            "response": {"usage": {}},
            "timing": {},
        },
        {
            "turn_id": "turn-b",
            "cache_action": "MISS",
            "delta": {
                "tool_outputs_omitted": 1,
                "chars_saved": 400,
                "turns_summarized": 0,
                "cache_control_injected": 1,
            },
            "response": {
                "usage": {
                    "input_tokens": 2000,
                    "output_tokens": 400,
                    "cache_read_input_tokens": 1000,
                    "cache_creation_input_tokens": 250,
                    "reasoning_tokens": 60,
                }
            },
            "timing": {
                "ttft_ms": 400.0,
                "total_ms": 2400.0,
                "prefill_tps": 5000.0,
                "tail_prefill_tps": 2500.0,
                "decode_tps": 200.0,
            },
        },
        {
            "turn_id": "turn-c",
            "cache_action": "MISS",
            "delta": {
                "tool_outputs_omitted": 0,
                "chars_saved": 0,
                "turns_summarized": 0,
                "cache_control_injected": 0,
            },
            "response": {
                "usage": {
                    "input_tokens": 500,
                    "output_tokens": 100,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                    "reasoning_tokens": 0,
                }
            },
            "timing": {
                "ttft_ms": 200.0,
                "total_ms": 700.0,
                "prefill_tps": 2500.0,
                "tail_prefill_tps": 2500.0,
                "decode_tps": None,
            },
        },
    ]

    log_file = tmp_path / "transactions.jsonl"
    log_file.write_text("\n".join(json.dumps(rec) for rec in records) + "\n", encoding="utf-8")

    live = CumulativeMetrics()
    for rec in records:
        live.record_request()
        live.record_cleaner(SimpleNamespace(**rec["delta"]))
        if rec["cache_action"] == "HIT":
            live.record_cache_hit()
            continue
        usage = rec["response"]["usage"]
        timing = rec["timing"]
        live.record_response(
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            cache_read_tokens=usage["cache_read_input_tokens"],
            cache_creation_tokens=usage["cache_creation_input_tokens"],
            reasoning_tokens=usage["reasoning_tokens"],
            ttft=timing["ttft_ms"] / 1000.0,
            output_tps=timing["decode_tps"],
            prefill_tps=timing["prefill_tps"],
            tail_prefill_tps=timing["tail_prefill_tps"],
            total_time=timing["total_ms"] / 1000.0,
        )

    offline = read_offline_metrics(str(tmp_path))
    assert offline is not None
    assert offline["source"] == "offline_wire_log"
    live_summary = live.to_dict()
    for key in shared_keys:
        assert offline[key] == live_summary[key]


def test_ast_and_tokenize_self_doc_classifiers() -> None:
    code_with_docstrings = '"""Module doc."""\n\ndef fn():\n    """Fn doc."""\n    return 1\n'
    doc_violations = _find_docstring_violations(code_with_docstrings, "sample.py")
    assert len(doc_violations) == 2

    code_without_docstrings = 'def fn():\n    return "# hash inside string literal"\n'
    assert _find_docstring_violations(code_without_docstrings, "sample.py") == []
    assert _find_disallowed_comments(code_without_docstrings, "sample.py") == []

    code_with_pragmas_and_prose = (
        "x = 1  # type: ignore[arg-type]\n"
        "y = 2  # noqa: F401\n"
        "z = 3  # pragma: no cover\n"
        "w = 4  # explanatory prose comment\n"
    )
    comment_violations = _find_disallowed_comments(code_with_pragmas_and_prose, "sample.py")
    assert len(comment_violations) == 1
    assert "explanatory prose comment" in comment_violations[0]


def test_metrics_and_ab_testing_files_are_self_documenting() -> None:
    docstring_violations: list[str] = []
    comment_violations: list[str] = []
    for rel_path in METRICS_AND_AB_SELF_DOC_FILES:
        file_path = REPO_ROOT / rel_path
        source = file_path.read_text(encoding="utf-8")
        docstring_violations.extend(_find_docstring_violations(source, rel_path))
        comment_violations.extend(_find_disallowed_comments(source, rel_path))

    assert not docstring_violations, f"Docstrings found in self-doc scope: {docstring_violations}"
    assert not comment_violations, f"Disallowed comments found in self-doc scope: {comment_violations}"
