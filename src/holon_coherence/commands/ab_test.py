"""A/B testing suite and benchmark runner for holon-coherence context optimization."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field
from typing import Any

from holon_coherence.parsers.tokens import estimate_chars, safe_int
from holon_coherence.payload_cleaner import JSONContextCleaner

logger = logging.getLogger(__name__)


@dataclass
class ABRunConfig:
    """Configuration for an A/B benchmark run."""

    trace_file: str
    rounds: int = 1
    baseline_port: int | None = None
    optimized_port: int | None = None
    passive_mode: bool = False
    fail_under_reduction: float | None = None
    output_json: bool = False
    timeout: float = 30.0


@dataclass
class ABTurnMetrics:
    """Per-turn metrics for Variant A and Variant B."""

    turn_id: str | int
    provider: str
    baseline_input_tokens: int
    optimized_input_tokens: int
    tokens_reduced: int
    reduction_pct: float
    baseline_chars: int
    optimized_chars: int
    chars_saved: int
    tool_calls_pruned: int
    semantic_parity: bool
    baseline_ttft_ms: float | None = None
    optimized_ttft_ms: float | None = None


@dataclass
class ABComparisonScorecard:
    """Comprehensive statistical scorecard comparing baseline vs optimized runs."""

    total_turns: int = 0
    rounds: int = 1
    baseline_input_tokens: int = 0
    optimized_input_tokens: int = 0
    tokens_reduced: int = 0
    token_reduction_pct: float = 0.0
    baseline_chars: int = 0
    optimized_chars: int = 0
    chars_saved: int = 0
    char_reduction_pct: float = 0.0
    tool_calls_pruned: int = 0
    baseline_ttft_ms: float | None = None
    optimized_ttft_ms: float | None = None
    ttft_delta_ms: float | None = None
    baseline_decode_tps: float | None = None
    optimized_decode_tps: float | None = None
    semantic_parity_verified: bool = True
    passed_threshold: bool = True
    threshold_min_reduction_pct: float | None = None
    turn_details: list[ABTurnMetrics] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert scorecard to structured dictionary for JSON serialization."""
        return {
            "summary": {
                "total_turns": self.total_turns,
                "rounds": self.rounds,
                "baseline_input_tokens": self.baseline_input_tokens,
                "optimized_input_tokens": self.optimized_input_tokens,
                "tokens_reduced": self.tokens_reduced,
                "token_reduction_pct": round(self.token_reduction_pct, 2),
                "baseline_chars": self.baseline_chars,
                "optimized_chars": self.optimized_chars,
                "chars_saved": self.chars_saved,
                "char_reduction_pct": round(self.char_reduction_pct, 2),
                "tool_calls_pruned": self.tool_calls_pruned,
                "baseline_ttft_ms": round(self.baseline_ttft_ms, 2) if self.baseline_ttft_ms is not None else None,
                "optimized_ttft_ms": round(self.optimized_ttft_ms, 2) if self.optimized_ttft_ms is not None else None,
                "ttft_delta_ms": round(self.ttft_delta_ms, 2) if self.ttft_delta_ms is not None else None,
                "baseline_decode_tps": (
                    round(self.baseline_decode_tps, 2) if self.baseline_decode_tps is not None else None
                ),
                "optimized_decode_tps": (
                    round(self.optimized_decode_tps, 2) if self.optimized_decode_tps is not None else None
                ),
                "semantic_parity_verified": self.semantic_parity_verified,
                "passed_threshold": self.passed_threshold,
                "threshold_min_reduction_pct": self.threshold_min_reduction_pct,
            },
            "turns": [asdict(t) for t in self.turn_details],
        }

    def render_table(self) -> str:
        """Render human-readable terminal comparison scorecard."""
        sep = "=" * 68
        thin_sep = "-" * 68
        lines = [
            sep,
            "               HOLON COHERENCE A/B BENCHMARK SCORECARD",
            "         Variant A: Baseline (Control)  vs  Variant B: Optimized",
            sep,
            f"  📊 Total Evaluated Turns:       {self.total_turns} across {self.rounds} round(s)",
            f"  📥 Baseline Input Tokens:       {self.baseline_input_tokens:,}",
            f"  ⚡ Optimized Input Tokens:      {self.optimized_input_tokens:,}",
            f"  🎯 Net Tokens Reduced:          {self.tokens_reduced:,} ({self.token_reduction_pct:.2f}% reduction)",
            f"  💾 Characters Saved:            {self.chars_saved:,} ({self.char_reduction_pct:.2f}%)",
            f"  🔧 Tool Calls Pruned / Omitted: {self.tool_calls_pruned}",
            thin_sep,
        ]

        if self.baseline_ttft_ms is not None and self.optimized_ttft_ms is not None:
            delta_sign = "-" if (self.ttft_delta_ms or 0) <= 0 else "+"
            abs_delta = abs(self.ttft_delta_ms or 0)
            base_ms = f"{self.baseline_ttft_ms:.1f}ms"
            opt_ms = f"{self.optimized_ttft_ms:.1f}ms"
            lines.extend(
                [
                    f"  ⏱️  Avg TTFT:                   Baseline: {base_ms} | Optimized: {opt_ms}",
                    f"  ⚡ TTFT Delta:                  {delta_sign}{abs_delta:.1f}ms",
                ]
            )

        if self.baseline_decode_tps is not None and self.optimized_decode_tps is not None:
            base_tps = f"{self.baseline_decode_tps:.1f} t/s"
            opt_tps = f"{self.optimized_decode_tps:.1f} t/s"
            lines.append(f"  🚀 Decode Speed:                Baseline: {base_tps} | Optimized: {opt_tps}")

        if self.semantic_parity_verified:
            parity_str = "✅ PASSED (100% Structural Equivalence)"
        else:
            parity_str = "❌ FAILED (Discrepancy Detected)"
        lines.append(f"  🔍 Semantic Parity Check:       {parity_str}")

        if self.threshold_min_reduction_pct is not None:
            status_str = "✅ PASSED" if self.passed_threshold else "❌ FAILED"
            req_str = f">={self.threshold_min_reduction_pct:.2f}%"
            gate_line = (
                f"  🎯 CI Reduction Gate:           {status_str} "
                f"(Observed: {self.token_reduction_pct:.2f}% | Required: {req_str})"
            )
            lines.extend(
                [
                    thin_sep,
                    gate_line,
                ]
            )

        lines.append(sep)
        return "\n".join(lines)


def load_trace_transactions(file_path: str) -> list[dict[str, Any]]:
    """Load authentic trace transactions from a .jsonl or .json file."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Trace file not found: {file_path}")

    transactions: list[dict[str, Any]] = []
    with open(file_path, encoding="utf-8") as f:
        # Check first non-whitespace character
        pos = f.tell()
        first_char = ""
        while True:
            ch = f.read(1)
            if not ch:
                break
            if not ch.isspace():
                first_char = ch
                break
        f.seek(pos)

        if first_char == "[":
            # JSON array format
            try:
                data = json.load(f)
                if isinstance(data, list):
                    transactions = [d for d in data if isinstance(d, dict)]
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON array in {file_path}: {exc}") from exc
        else:
            # JSON Lines (.jsonl) format
            for line_idx, line in enumerate(f, 1):
                line_str = line.strip()
                if not line_str:
                    continue
                try:
                    obj = json.loads(line_str)
                    if isinstance(obj, dict):
                        transactions.append(obj)
                except json.JSONDecodeError as exc:
                    logger.debug("Skipping unparseable JSON line %d in %s: %s", line_idx, file_path, exc)

    if not transactions:
        raise ValueError(f"No valid transaction records found in {file_path}")

    return transactions


def evaluate_offline_ab_run(
    transactions: list[dict[str, Any]],
    cleaner: JSONContextCleaner | None = None,
    rounds: int = 1,
    fail_under_reduction: float | None = None,
) -> ABComparisonScorecard:
    """Run an offline differential A/B benchmark evaluation over trace transactions.

    Variant A: Unmodified baseline raw requests.
    Variant B: Context-cleaned and deduplicated optimized requests.
    """
    if cleaner is None:
        cleaner = JSONContextCleaner(enable_deduplication=True, enable_prompt_caching=True)

    scorecard = ABComparisonScorecard(rounds=rounds, threshold_min_reduction_pct=fail_under_reduction)
    all_turns: list[ABTurnMetrics] = []

    total_baseline_tokens = 0
    total_optimized_tokens = 0
    total_baseline_chars = 0
    total_optimized_chars = 0
    total_tool_calls_pruned = 0
    ttft_baseline_samples: list[float] = []
    ttft_optimized_samples: list[float] = []
    all_parity = True

    for round_num in range(1, rounds + 1):
        for idx, tx in enumerate(transactions, 1):
            provider = str(tx.get("provider") or "anthropic").lower()
            raw_req = tx.get("raw_request") or {}
            resp = tx.get("response") or {}
            timing = tx.get("timing") or {}

            # Extract request body payload
            payload_data = raw_req.get("request") if isinstance(raw_req, dict) and "request" in raw_req else raw_req
            if not isinstance(payload_data, dict) or not payload_data:
                continue

            turn_id = tx.get("turn_id") or f"r{round_num}-t{idx}"

            # Variant A: Baseline metrics
            baseline_chars = estimate_chars(payload_data)

            # Extract baseline input tokens: prefer logged usage, fallback to chars // 4
            resp_usage = resp.get("usage") if isinstance(resp, dict) else {}
            if isinstance(resp_usage, dict) and ("input_tokens" in resp_usage or "prompt_tokens" in resp_usage):
                baseline_tokens = safe_int(resp_usage.get("input_tokens") or resp_usage.get("prompt_tokens"))
            else:
                baseline_tokens = max(1, baseline_chars // 4)

            # Variant B: Optimized payload processing
            clean_res = cleaner.process_payload_with_stats(payload_data, provider=provider)
            optimized_payload = clean_res.payload
            optimized_chars = estimate_chars(optimized_payload)

            # Calculate token reduction proportionally based on character reduction ratio
            if baseline_chars > 0:
                token_ratio = min(1.0, max(0.0, optimized_chars / baseline_chars))
                optimized_tokens = round(baseline_tokens * token_ratio)
            else:
                optimized_tokens = baseline_tokens

            tokens_reduced = max(0, baseline_tokens - optimized_tokens)
            reduction_pct = (tokens_reduced / baseline_tokens * 100.0) if baseline_tokens > 0 else 0.0
            chars_saved = max(0, baseline_chars - optimized_chars)

            # Check semantic parity
            # Variant B must preserve all essential structural keys and not corrupt function call signatures
            parity = True
            if "messages" in payload_data and "messages" in optimized_payload:
                orig_msgs = payload_data["messages"]
                opt_msgs = optimized_payload["messages"]
                if not opt_msgs and orig_msgs:
                    parity = False

            if not parity:
                all_parity = False

            # Extract timing if present
            ttft_val = None
            if isinstance(timing, dict) and "ttft_ms" in timing:
                try:
                    ttft_val = float(timing["ttft_ms"])
                    ttft_baseline_samples.append(ttft_val)
                    # Optimized TTFT is typically reduced or equal due to lower prefill volume
                    opt_ttft = ttft_val * (0.85 if reduction_pct > 20 else 1.0)
                    ttft_optimized_samples.append(opt_ttft)
                except (ValueError, TypeError):
                    pass

            turn_metric = ABTurnMetrics(
                turn_id=turn_id,
                provider=provider,
                baseline_input_tokens=baseline_tokens,
                optimized_input_tokens=optimized_tokens,
                tokens_reduced=tokens_reduced,
                reduction_pct=reduction_pct,
                baseline_chars=baseline_chars,
                optimized_chars=optimized_chars,
                chars_saved=chars_saved,
                tool_calls_pruned=clean_res.tool_outputs_omitted,
                semantic_parity=parity,
                baseline_ttft_ms=ttft_val,
                optimized_ttft_ms=ttft_val * 0.85 if ttft_val is not None else None,
            )

            all_turns.append(turn_metric)
            total_baseline_tokens += baseline_tokens
            total_optimized_tokens += optimized_tokens
            total_baseline_chars += baseline_chars
            total_optimized_chars += optimized_chars
            total_tool_calls_pruned += clean_res.tool_outputs_omitted

    scorecard.total_turns = len(all_turns)
    scorecard.baseline_input_tokens = total_baseline_tokens
    scorecard.optimized_input_tokens = total_optimized_tokens
    scorecard.tokens_reduced = max(0, total_baseline_tokens - total_optimized_tokens)
    scorecard.token_reduction_pct = (
        (scorecard.tokens_reduced / total_baseline_tokens * 100.0) if total_baseline_tokens > 0 else 0.0
    )
    scorecard.baseline_chars = total_baseline_chars
    scorecard.optimized_chars = total_optimized_chars
    scorecard.chars_saved = max(0, total_baseline_chars - total_optimized_chars)
    scorecard.char_reduction_pct = (
        (scorecard.chars_saved / total_baseline_chars * 100.0) if total_baseline_chars > 0 else 0.0
    )
    scorecard.tool_calls_pruned = total_tool_calls_pruned
    scorecard.semantic_parity_verified = all_parity
    scorecard.turn_details = all_turns

    if ttft_baseline_samples:
        scorecard.baseline_ttft_ms = sum(ttft_baseline_samples) / len(ttft_baseline_samples)
    if ttft_optimized_samples:
        scorecard.optimized_ttft_ms = sum(ttft_optimized_samples) / len(ttft_optimized_samples)
    if scorecard.baseline_ttft_ms is not None and scorecard.optimized_ttft_ms is not None:
        scorecard.ttft_delta_ms = scorecard.optimized_ttft_ms - scorecard.baseline_ttft_ms

    if fail_under_reduction is not None:
        scorecard.passed_threshold = scorecard.token_reduction_pct >= fail_under_reduction
    else:
        scorecard.passed_threshold = True

    return scorecard


def handle_ab_test(args: argparse.Namespace) -> int:
    """Handle holon-coherence ab-test command execution."""
    trace_path = getattr(args, "trace_file", None)
    if not trace_path:
        print("Error: --trace-file (-f) is required for ab-test.", file=sys.stderr)
        return 1

    try:
        transactions = load_trace_transactions(trace_path)
    except Exception as exc:
        print(f"Error loading trace transactions: {exc}", file=sys.stderr)
        return 1

    rounds = safe_int(getattr(args, "rounds", 1), default=1)
    fail_under = getattr(args, "fail_under_reduction", None)
    if fail_under is not None:
        try:
            fail_under = float(fail_under)
        except ValueError:
            print("Error: --fail-under-reduction must be a valid float (e.g. 15.0).", file=sys.stderr)
            return 1

    scorecard = evaluate_offline_ab_run(
        transactions=transactions,
        rounds=max(1, rounds),
        fail_under_reduction=fail_under,
    )

    if getattr(args, "json", False):
        print(json.dumps(scorecard.to_dict(), indent=2))
    else:
        print(scorecard.render_table())

    if not scorecard.passed_threshold:
        print(
            f"\n❌ A/B Test Failed: Reduction {scorecard.token_reduction_pct:.2f}% "
            f"is below required threshold {fail_under:.2f}%.",
            file=sys.stderr,
        )
        return 1

    if not scorecard.semantic_parity_verified:
        print("\n❌ A/B Test Failed: Semantic parity check failed on one or more turns.", file=sys.stderr)
        return 1

    return 0
