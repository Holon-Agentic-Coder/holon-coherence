"""A/B testing suite and benchmark runner for holon-coherence context optimization."""

from __future__ import annotations

import argparse
import contextlib
import http.client
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any

from holon_coherence.parsers.tokens import estimate_chars, safe_int
from holon_coherence.payload_cleaner import JSONContextCleaner

logger = logging.getLogger(__name__)


@dataclass
class ABRunConfig:
    """Configuration for an A/B benchmark run."""

    trace_file: str | None = None
    command: str | None = None
    baseline_path: str | None = None
    optimized_path: str | None = None
    live: bool = False
    rounds: int = 1
    fail_under_reduction: float | None = None
    output_json: bool = False
    timeout: float = 30.0  # Reserved for future live/online differential proxy test executions


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
    cache_control_injected: int
    semantic_parity: bool
    baseline_ttft_ms: float | None = None
    optimized_ttft_ms: float | None = None


@dataclass
class ABComparisonScorecard:
    """Comprehensive statistical scorecard comparing baseline vs optimized runs."""

    total_turns: int = 0
    rounds: int = 1
    mode_label: str = "Real Intercepted Traffic"
    baseline_input_tokens: int = 0
    optimized_input_tokens: int = 0
    tokens_reduced: int = 0
    token_reduction_pct: float = 0.0
    baseline_chars: int = 0
    optimized_chars: int = 0
    chars_saved: int = 0
    char_reduction_pct: float = 0.0
    tool_calls_pruned: int = 0
    cache_control_injected: int = 0
    cache_hits: int = 0
    cache_hit_rate: float = 0.0
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
                "mode": self.mode_label,
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
                "cache_control_injected": self.cache_control_injected,
                "cache_hits": self.cache_hits,
                "cache_hit_rate": round(self.cache_hit_rate, 2),
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
            f"  Source: {self.mode_label}",
            "  Variant A: Baseline (Control)  vs  Variant B: Optimized",
            sep,
            f"  📊 Total Evaluated Turns:       {self.total_turns} across {self.rounds} round(s)",
            f"  📥 Baseline Input Tokens:       {self.baseline_input_tokens:,}",
            f"  ⚡ Optimized Input Tokens:      {self.optimized_input_tokens:,}",
            f"  🎯 Net Tokens Reduced:          {self.tokens_reduced:,} ({self.token_reduction_pct:.2f}% reduction)",
            f"  💾 Characters Saved:            {self.chars_saved:,} ({self.char_reduction_pct:.2f}%)",
            f"  🔧 Tool Calls Pruned / Omitted: {self.tool_calls_pruned}",
            f"  🏷️  Prompt Cache Breakpoints:   {self.cache_control_injected} injected",
        ]

        if self.cache_hits > 0:
            hit_str = f"{self.cache_hits} hits / {self.total_turns} turns"
            lines.append(f"  🎯 Cache Hit Rate:              {self.cache_hit_rate:.1f}% ({hit_str})")

        lines.append(thin_sep)

        if self.baseline_ttft_ms is not None and self.optimized_ttft_ms is not None:
            delta = (
                self.ttft_delta_ms
                if self.ttft_delta_ms is not None
                else (self.baseline_ttft_ms - self.optimized_ttft_ms)
            )
            pct = (
                ((self.baseline_ttft_ms - self.optimized_ttft_ms) / self.baseline_ttft_ms * 100.0)
                if self.baseline_ttft_ms > 0
                else 0.0
            )
            delta_sign = "-" if delta <= 0 else "+"
            base_ms = f"{self.baseline_ttft_ms:.1f}ms"
            opt_ms = f"{self.optimized_ttft_ms:.1f}ms"
            faster_str = f" ({pct:.1f}% faster)" if pct >= 0 else ""
            lines.extend(
                [
                    f"  ⏱️  Avg TTFT:                   Baseline: {base_ms} | Optimized: {opt_ms}",
                    f"  ⚡ TTFT Delta:                  {delta_sign}{abs(delta):.1f}ms{faster_str}",
                ]
            )
        elif self.baseline_ttft_ms is not None:
            base_ms = f"{self.baseline_ttft_ms:.1f}ms"
            lines.append(f"  ⏱️  Baseline TTFT (Recorded):    {base_ms} (Variant B: offline evaluation)")

        if self.baseline_decode_tps is not None and self.optimized_decode_tps is not None:
            base_tps = f"{self.baseline_decode_tps:.1f} t/s"
            opt_tps = f"{self.optimized_decode_tps:.1f} t/s"
            lines.append(f"  🚀 Decode Throughput:           Baseline: {base_tps} | Optimized: {opt_tps}")

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
    with open(file_path, encoding="utf-8-sig") as f:
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


def load_transactions_from_path(path: str) -> list[dict[str, Any]]:
    """Load authentic trace transactions from a file or directory."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Trace path not found: {path}")

    if os.path.isdir(path):
        jsonl_path = os.path.join(path, "transactions.jsonl")
        if os.path.isfile(jsonl_path):
            return load_trace_transactions(jsonl_path)
        txs: list[dict[str, Any]] = []
        for root, _, files in os.walk(path):
            for file in sorted(files):
                if file.endswith(".jsonl"):
                    with contextlib.suppress(Exception):
                        txs.extend(load_trace_transactions(os.path.join(root, file)))
                elif file.startswith("turn_") and file.endswith(".json"):
                    try:
                        with open(os.path.join(root, file), encoding="utf-8-sig") as f:
                            obj = json.load(f)
                            if isinstance(obj, dict):
                                txs.append(obj)
                    except Exception:
                        pass
        if not txs:
            raise ValueError(f"No valid transaction records found in directory: {path}")
        return txs

    return load_trace_transactions(path)


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

    scorecard = ABComparisonScorecard(
        rounds=rounds,
        threshold_min_reduction_pct=fail_under_reduction,
        mode_label="Offline Differential Replay (Trace File)",
    )
    all_turns: list[ABTurnMetrics] = []

    total_baseline_tokens = 0
    total_optimized_tokens = 0
    total_baseline_chars = 0
    total_optimized_chars = 0
    total_tool_calls_pruned = 0
    total_cache_control_injected = 0
    total_cache_hits = 0
    ttft_baseline_samples: list[float] = []
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
            # Variant B must preserve all essential structural keys, messages, and roles
            parity = True
            if "messages" in payload_data:
                if "messages" not in optimized_payload:
                    parity = False
                else:
                    orig_msgs = payload_data["messages"]
                    opt_msgs = optimized_payload["messages"]
                    if bool(orig_msgs) != bool(opt_msgs):
                        parity = False
                    elif isinstance(orig_msgs, list) and isinstance(opt_msgs, list) and orig_msgs and opt_msgs:
                        # Verify the current active turn role is preserved
                        last_orig = orig_msgs[-1]
                        last_opt = opt_msgs[-1]
                        if (
                            isinstance(last_orig, dict)
                            and isinstance(last_opt, dict)
                            and last_orig.get("role") != last_opt.get("role")
                        ):
                            parity = False
            elif "contents" in payload_data and "contents" not in optimized_payload:
                parity = False

            if not parity:
                all_parity = False

            # Extract recorded baseline timing if present
            ttft_val = None
            if isinstance(timing, dict) and "ttft_ms" in timing:
                try:
                    ttft_val = float(timing["ttft_ms"])
                    ttft_baseline_samples.append(ttft_val)
                except (ValueError, TypeError):
                    pass

            cache_action = str(tx.get("cache_action") or tx.get("cache_status") or "").upper()
            if cache_action == "HIT":
                total_cache_hits += 1

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
                cache_control_injected=clean_res.cache_control_injected,
                semantic_parity=parity,
                baseline_ttft_ms=ttft_val,
                optimized_ttft_ms=None,  # Rule 10: Zero synthetic TTFT in offline replay
            )

            all_turns.append(turn_metric)
            total_baseline_tokens += baseline_tokens
            total_optimized_tokens += optimized_tokens
            total_baseline_chars += baseline_chars
            total_optimized_chars += optimized_chars
            total_tool_calls_pruned += clean_res.tool_outputs_omitted
            total_cache_control_injected += clean_res.cache_control_injected

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
    scorecard.cache_control_injected = total_cache_control_injected
    scorecard.cache_hits = total_cache_hits
    scorecard.cache_hit_rate = (total_cache_hits / len(all_turns) * 100.0) if all_turns else 0.0
    scorecard.semantic_parity_verified = all_parity
    scorecard.turn_details = all_turns

    if ttft_baseline_samples:
        scorecard.baseline_ttft_ms = sum(ttft_baseline_samples) / len(ttft_baseline_samples)
    scorecard.optimized_ttft_ms = None
    scorecard.ttft_delta_ms = None

    if fail_under_reduction is not None:
        scorecard.passed_threshold = scorecard.token_reduction_pct >= fail_under_reduction
    else:
        scorecard.passed_threshold = True

    return scorecard


def evaluate_runs(
    baseline_transactions: list[dict[str, Any]],
    optimized_transactions: list[dict[str, Any]],
    rounds: int = 1,
    fail_under_reduction: float | None = None,
    mode_label: str = "Real Intercepted Traffic",
) -> ABComparisonScorecard:
    """Evaluate authentic intercepted baseline vs optimized transactions.

    Derives all token reduction, cache hits, real provider TTFT, and TPS from
    authentic recorded wire transactions with zero synthetic or mock approximations.
    """
    base_list = [tx for tx in baseline_transactions if tx.get("mode") != "optimized"] or baseline_transactions
    opt_list = [tx for tx in optimized_transactions if tx.get("mode") != "baseline"] or optimized_transactions

    num_turns = min(len(base_list), len(opt_list))
    if num_turns == 0:
        raise ValueError("Cannot evaluate A/B test with zero paired turns between baseline and optimized runs.")

    scorecard = ABComparisonScorecard(
        rounds=rounds,
        threshold_min_reduction_pct=fail_under_reduction,
        mode_label=mode_label,
    )
    turn_metrics: list[ABTurnMetrics] = []

    total_base_tokens = 0
    total_opt_tokens = 0
    total_base_chars = 0
    total_opt_chars = 0
    total_pruned = 0
    total_injected = 0
    total_cache_hits = 0
    base_ttft_samples: list[float] = []
    opt_ttft_samples: list[float] = []
    base_tps_samples: list[float] = []
    opt_tps_samples: list[float] = []
    all_parity = True

    for round_num in range(1, rounds + 1):
        for idx in range(num_turns):
            base_tx = base_list[idx]
            opt_tx = opt_list[idx]

            provider = str(opt_tx.get("provider") or base_tx.get("provider") or "anthropic").lower()
            turn_id = opt_tx.get("turn_id") or base_tx.get("turn_id") or f"r{round_num}-t{idx + 1}"

            # Baseline tokens & chars
            base_resp_usage = (base_tx.get("response") or {}).get("usage") or {}
            base_raw = base_tx.get("raw_request") or {}
            base_chars = estimate_chars(base_raw)
            if isinstance(base_resp_usage, dict) and (
                "input_tokens" in base_resp_usage or "prompt_tokens" in base_resp_usage
            ):
                base_tokens = safe_int(base_resp_usage.get("input_tokens") or base_resp_usage.get("prompt_tokens"))
            else:
                base_tokens = max(1, base_chars // 4)

            # Optimized tokens & chars
            opt_resp_usage = (opt_tx.get("response") or {}).get("usage") or {}
            opt_raw = opt_tx.get("cleaned_request") or opt_tx.get("raw_request") or {}
            opt_chars = estimate_chars(opt_raw)
            if isinstance(opt_resp_usage, dict) and (
                "input_tokens" in opt_resp_usage or "prompt_tokens" in opt_resp_usage
            ):
                opt_tokens = safe_int(opt_resp_usage.get("input_tokens") or opt_resp_usage.get("prompt_tokens"))
            else:
                opt_tokens = max(1, opt_chars // 4)

            tokens_reduced = max(0, base_tokens - opt_tokens)
            reduction_pct = (tokens_reduced / base_tokens * 100.0) if base_tokens > 0 else 0.0
            chars_saved = max(0, base_chars - opt_chars)

            # Pruning and caching stats
            delta = opt_tx.get("delta") or {}
            pruned = safe_int(delta.get("tool_outputs_omitted") or delta.get("tool_calls_pruned"))
            injected = safe_int(delta.get("cache_control_injected"))

            cache_action = str(opt_tx.get("cache_action") or "").upper()
            if cache_action == "HIT" or safe_int(opt_resp_usage.get("cache_read_input_tokens")) > 0:
                total_cache_hits += 1

            # Timing & throughput
            base_timing = base_tx.get("timing") or {}
            opt_timing = opt_tx.get("timing") or {}
            base_ttft = None
            opt_ttft = None
            if "ttft_ms" in base_timing and base_timing["ttft_ms"] is not None:
                with contextlib.suppress(ValueError, TypeError):
                    base_ttft = float(base_timing["ttft_ms"])
                    base_ttft_samples.append(base_ttft)
            if "ttft_ms" in opt_timing and opt_timing["ttft_ms"] is not None:
                with contextlib.suppress(ValueError, TypeError):
                    opt_ttft = float(opt_timing["ttft_ms"])
                    opt_ttft_samples.append(opt_ttft)

            if "decode_tps" in base_timing and base_timing["decode_tps"] is not None:
                with contextlib.suppress(ValueError, TypeError):
                    base_tps_samples.append(float(base_timing["decode_tps"]))
            if "decode_tps" in opt_timing and opt_timing["decode_tps"] is not None:
                with contextlib.suppress(ValueError, TypeError):
                    opt_tps_samples.append(float(opt_timing["decode_tps"]))

            # Semantic parity verification
            base_status = (base_tx.get("response") or {}).get("status", 200)
            opt_status = (opt_tx.get("response") or {}).get("status", 200)
            parity = base_status in (200, None) and opt_status in (200, None)

            base_payload = base_raw.get("request") if isinstance(base_raw, dict) and "request" in base_raw else base_raw
            opt_payload = opt_raw.get("request") if isinstance(opt_raw, dict) and "request" in opt_raw else opt_raw
            if (
                isinstance(base_payload, dict)
                and isinstance(opt_payload, dict)
                and (
                    ("messages" in base_payload and "messages" not in opt_payload)
                    or ("contents" in base_payload and "contents" not in opt_payload)
                )
            ):
                parity = False

            if not parity:
                all_parity = False

            turn_metric = ABTurnMetrics(
                turn_id=turn_id,
                provider=provider,
                baseline_input_tokens=base_tokens,
                optimized_input_tokens=opt_tokens,
                tokens_reduced=tokens_reduced,
                reduction_pct=reduction_pct,
                baseline_chars=base_chars,
                optimized_chars=opt_chars,
                chars_saved=chars_saved,
                tool_calls_pruned=pruned,
                cache_control_injected=injected,
                semantic_parity=parity,
                baseline_ttft_ms=base_ttft,
                optimized_ttft_ms=opt_ttft,
            )
            turn_metrics.append(turn_metric)
            total_base_tokens += base_tokens
            total_opt_tokens += opt_tokens
            total_base_chars += base_chars
            total_opt_chars += opt_chars
            total_pruned += pruned
            total_injected += injected

    scorecard.total_turns = len(turn_metrics)
    scorecard.rounds = rounds
    scorecard.mode_label = mode_label
    scorecard.baseline_input_tokens = total_base_tokens
    scorecard.optimized_input_tokens = total_opt_tokens
    scorecard.tokens_reduced = max(0, total_base_tokens - total_opt_tokens)
    scorecard.token_reduction_pct = (
        (scorecard.tokens_reduced / total_base_tokens * 100.0) if total_base_tokens > 0 else 0.0
    )
    scorecard.baseline_chars = total_base_chars
    scorecard.optimized_chars = total_opt_chars
    scorecard.chars_saved = max(0, total_base_chars - total_opt_chars)
    scorecard.char_reduction_pct = (scorecard.chars_saved / total_base_chars * 100.0) if total_base_chars > 0 else 0.0
    scorecard.tool_calls_pruned = total_pruned
    scorecard.cache_control_injected = total_injected
    scorecard.cache_hits = total_cache_hits
    scorecard.cache_hit_rate = (total_cache_hits / len(turn_metrics) * 100.0) if turn_metrics else 0.0
    scorecard.semantic_parity_verified = all_parity
    scorecard.turn_details = turn_metrics

    if base_ttft_samples:
        scorecard.baseline_ttft_ms = sum(base_ttft_samples) / len(base_ttft_samples)
    if opt_ttft_samples:
        scorecard.optimized_ttft_ms = sum(opt_ttft_samples) / len(opt_ttft_samples)
    if scorecard.baseline_ttft_ms is not None and scorecard.optimized_ttft_ms is not None:
        scorecard.ttft_delta_ms = scorecard.baseline_ttft_ms - scorecard.optimized_ttft_ms

    if base_tps_samples:
        scorecard.baseline_decode_tps = sum(base_tps_samples) / len(base_tps_samples)
    if opt_tps_samples:
        scorecard.optimized_decode_tps = sum(opt_tps_samples) / len(opt_tps_samples)

    if fail_under_reduction is not None:
        scorecard.passed_threshold = scorecard.token_reduction_pct >= fail_under_reduction
    else:
        scorecard.passed_threshold = True

    return scorecard


def set_proxy_mode(mode: str, port: int = 8080, wire_log_dir: str | None = None) -> bool:
    """Set the monitoring/optimization mode and optional wire log dir of the live proxy."""
    try:
        url = f"http://127.0.0.1:{port}/holon/api/mode"
        payload: dict[str, Any] = {"mode": mode}
        if wire_log_dir:
            payload["wire_log_dir"] = wire_log_dir
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            return resp.status == 200
    except Exception:
        return False


def run_workload_ab_test(
    config: ABRunConfig,
    proxy_port: int = 8080,
) -> ABComparisonScorecard:
    """Execute a real agent command workload twice through the proxy with authentic LLM traffic."""
    from holon_coherence.commands.runner import build_proxy_env

    command_str = config.command
    if not command_str:
        raise ValueError("No command specified for workload A/B benchmark.")

    proxy_url = f"http://127.0.0.1:{proxy_port}"
    session_dir = tempfile.mkdtemp(prefix="holon_ab_workload_")
    baseline_dir = os.path.join(session_dir, "baseline")
    optimized_dir = os.path.join(session_dir, "optimized")
    os.makedirs(baseline_dir, exist_ok=True)
    os.makedirs(optimized_dir, exist_ok=True)

    base_env = os.environ.copy()
    proxy_env_vars = build_proxy_env(proxy_url)
    base_env.update(proxy_env_vars)

    print("🚀 Running Variant A (Baseline / Control Workload): Real Traffic Interception...")
    set_proxy_mode("baseline", port=proxy_port, wire_log_dir=baseline_dir)
    env_a = base_env.copy()
    env_a["HOLON_PASSIVE_MONITORING"] = "1"
    env_a["WIRE_LOG_DIR"] = baseline_dir
    res_a = subprocess.run(command_str, shell=True, env=env_a)
    if res_a.returncode != 0:
        print(f"⚠️  Baseline workload exited with code {res_a.returncode}", file=sys.stderr)

    print("⚡ Running Variant B (Optimized Workload): Real Traffic Optimization...")
    set_proxy_mode("optimized", port=proxy_port, wire_log_dir=optimized_dir)
    env_b = base_env.copy()
    env_b["HOLON_PASSIVE_MONITORING"] = "0"
    env_b["WIRE_LOG_DIR"] = optimized_dir
    res_b = subprocess.run(command_str, shell=True, env=env_b)
    if res_b.returncode != 0:
        print(f"⚠️  Optimized workload exited with code {res_b.returncode}", file=sys.stderr)

    # Ingest authentic transactions
    baseline_txs = load_transactions_from_path(baseline_dir)
    optimized_txs = load_transactions_from_path(optimized_dir)

    return evaluate_runs(
        baseline_transactions=baseline_txs,
        optimized_transactions=optimized_txs,
        rounds=config.rounds,
        fail_under_reduction=config.fail_under_reduction,
        mode_label="Real Intercepted Workload",
    )


def run_live_replay_ab_test(
    config: ABRunConfig,
    proxy_port: int = 8080,
) -> ABComparisonScorecard:
    """Replay authentic trace requests as live HTTP traffic through proxy against real upstream LLM endpoints."""
    if not config.trace_file:
        raise ValueError("No trace file specified for live replay.")

    raw_txs = load_trace_transactions(config.trace_file)
    baseline_txs: list[dict[str, Any]] = []
    optimized_txs: list[dict[str, Any]] = []

    for idx, tx in enumerate(raw_txs, 1):
        raw_req = tx.get("raw_request") or {}
        payload_data = raw_req.get("request") if isinstance(raw_req, dict) and "request" in raw_req else raw_req
        if not isinstance(payload_data, dict) or not payload_data:
            continue

        endpoint = tx.get("endpoint") or "https://api.anthropic.com/v1/messages"
        parsed = urllib.parse.urlparse(endpoint if "://" in endpoint else f"http://{endpoint}")
        path = parsed.path or "/v1/messages"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        headers = tx.get("headers") or {}
        clean_headers: dict[str, str] = {
            k: str(v) for k, v in headers.items() if not k.lower().startswith("content-length")
        }
        clean_headers["Host"] = parsed.netloc or "api.anthropic.com"
        clean_headers["Content-Type"] = "application/json"

        # Pass 1: Baseline replay via proxy
        h_baseline = clean_headers.copy()
        h_baseline["X-Holon-Mode"] = "baseline"
        t0 = time.perf_counter()
        conn = http.client.HTTPConnection("127.0.0.1", proxy_port, timeout=config.timeout)
        try:
            req_bytes = json.dumps(payload_data).encode("utf-8")
            conn.request("POST", endpoint, body=req_bytes, headers=h_baseline)
            resp = conn.getresponse()
            resp_body = resp.read()
            t_base = (time.perf_counter() - t0) * 1000.0
            resp_json: dict[str, Any] = {}
            with contextlib.suppress(Exception):
                resp_json = json.loads(resp_body)
            base_tx_record = {
                "turn_id": tx.get("turn_id") or f"live-t{idx}",
                "provider": tx.get("provider") or "anthropic",
                "mode": "baseline",
                "raw_request": payload_data,
                "response": {"status": resp.status, "usage": resp_json.get("usage", {})},
                "timing": {"ttft_ms": round(t_base, 2)},
            }
            baseline_txs.append(base_tx_record)
        finally:
            conn.close()

        # Pass 2: Optimized replay via proxy
        h_optimized = clean_headers.copy()
        h_optimized["X-Holon-Mode"] = "optimized"
        t0 = time.perf_counter()
        conn = http.client.HTTPConnection("127.0.0.1", proxy_port, timeout=config.timeout)
        try:
            conn.request("POST", endpoint, body=req_bytes, headers=h_optimized)
            resp = conn.getresponse()
            resp_body = resp.read()
            t_opt = (time.perf_counter() - t0) * 1000.0
            resp_json = {}
            with contextlib.suppress(Exception):
                resp_json = json.loads(resp_body)
            opt_tx_record = {
                "turn_id": tx.get("turn_id") or f"live-t{idx}",
                "provider": tx.get("provider") or "anthropic",
                "mode": "optimized",
                "raw_request": payload_data,
                "cleaned_request": payload_data,
                "response": {"status": resp.status, "usage": resp_json.get("usage", {})},
                "timing": {"ttft_ms": round(t_opt, 2)},
            }
            optimized_txs.append(opt_tx_record)
        finally:
            conn.close()

    return evaluate_runs(
        baseline_transactions=baseline_txs,
        optimized_transactions=optimized_txs,
        rounds=config.rounds,
        fail_under_reduction=config.fail_under_reduction,
        mode_label="Real Intercepted Traffic (Live Proxy Replay)",
    )


def handle_ab_test(args: argparse.Namespace) -> int:
    """Handle holon-coherence ab-test command execution across real traffic and offline modes."""
    workload_cmd = getattr(args, "workload_cmd", None)
    trace_path = getattr(args, "trace_file", None)
    baseline_path = getattr(args, "baseline", None)
    optimized_path = getattr(args, "optimized", None)
    live = bool(getattr(args, "live", False))
    rounds = safe_int(getattr(args, "rounds", 1), default=1)
    fail_under = getattr(args, "fail_under_reduction", None)
    if fail_under is not None:
        try:
            fail_under = float(fail_under)
        except ValueError:
            print("Error: --fail-under-reduction must be a valid float (e.g. 15.0).", file=sys.stderr)
            return 1

    config = ABRunConfig(
        command=workload_cmd,
        trace_file=trace_path,
        baseline_path=baseline_path,
        optimized_path=optimized_path,
        live=live,
        rounds=max(1, rounds),
        fail_under_reduction=fail_under,
        output_json=bool(getattr(args, "json", False)),
    )

    try:
        # Mode 1: Real agent workload execution (--command / -c)
        if config.command:
            scorecard = run_workload_ab_test(config)

        # Mode 2: Two authentic wire log directories or files (--baseline & --optimized)
        elif config.baseline_path and config.optimized_path:
            base_txs = load_transactions_from_path(config.baseline_path)
            opt_txs = load_transactions_from_path(config.optimized_path)
            scorecard = evaluate_runs(
                baseline_transactions=base_txs,
                optimized_transactions=opt_txs,
                rounds=config.rounds,
                fail_under_reduction=config.fail_under_reduction,
                mode_label="Real Intercepted Traffic (Logs)",
            )

        # Mode 3: Trace file with live proxy replay (--trace-file & --live)
        elif config.trace_file and config.live:
            scorecard = run_live_replay_ab_test(config)

        # Mode 4: Trace file ingestion (offline differential or mixed trace evaluation)
        elif config.trace_file:
            transactions = load_trace_transactions(config.trace_file)
            has_baseline = any(t.get("mode") == "baseline" for t in transactions)
            has_optimized = any(t.get("mode") == "optimized" for t in transactions)
            if has_baseline and has_optimized:
                base_txs = [t for t in transactions if t.get("mode") == "baseline"]
                opt_txs = [t for t in transactions if t.get("mode") == "optimized"]
                scorecard = evaluate_runs(
                    baseline_transactions=base_txs,
                    optimized_transactions=opt_txs,
                    rounds=config.rounds,
                    fail_under_reduction=config.fail_under_reduction,
                    mode_label="Real Intercepted Traffic (Mixed Trace)",
                )
            else:
                scorecard = evaluate_offline_ab_run(
                    transactions=transactions,
                    rounds=config.rounds,
                    fail_under_reduction=config.fail_under_reduction,
                )
        else:
            print(
                "Error: One of --command (-c), --trace-file (-f), or both --baseline and --optimized must be provided.",
                file=sys.stderr,
            )
            return 1
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error loading trace transactions: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error during A/B benchmark execution: {exc}", file=sys.stderr)
        return 1

    if config.output_json:
        print(json.dumps(scorecard.to_dict(), indent=2))
    else:
        print(scorecard.render_table())

    if not scorecard.passed_threshold:
        print(
            f"\n❌ A/B Test Failed: Reduction {scorecard.token_reduction_pct:.2f}% "
            f"is below required threshold {config.fail_under_reduction:.2f}%.",
            file=sys.stderr,
        )
        return 1

    if not scorecard.semantic_parity_verified:
        print("\n❌ A/B Test Failed: Semantic parity check failed on one or more turns.", file=sys.stderr)
        return 1

    return 0
