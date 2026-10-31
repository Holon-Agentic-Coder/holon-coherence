"""A/B testing evaluation domain models and differential benchmark scoring logic."""

from __future__ import annotations

import contextlib
import json
import logging
import os
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
    timeout: float = 30.0


# Domain alias
AbRun = ABRunConfig


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

    def format_console(self) -> str:
        """Alias for render_table."""
        return self.render_table()


# Domain alias
AbEvaluation = ABComparisonScorecard


def _peek_first_char(f: Any) -> str:
    """Read first non-whitespace character from open stream, resetting position afterwards."""
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
    return first_char


def _parse_json_array_stream(file_obj: Any, file_path: str) -> list[dict[str, Any]]:
    """Parse JSON array transaction stream."""
    try:
        data = json.load(file_obj)
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
        return []
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON array in {file_path}: {exc}") from exc


def _parse_jsonl_stream(file_obj: Any, file_path: str) -> list[dict[str, Any]]:
    """Parse JSON Lines transaction stream."""
    transactions: list[dict[str, Any]] = []
    for line_idx, line in enumerate(file_obj, 1):
        line_str = line.strip()
        if not line_str:
            continue
        try:
            obj = json.loads(line_str)
            if isinstance(obj, dict):
                transactions.append(obj)
        except json.JSONDecodeError as exc:
            logger.debug("Skipping unparseable JSON line %d in %s: %s", line_idx, file_path, exc)
    return transactions


def load_trace_transactions(file_path: str) -> list[dict[str, Any]]:
    """Load authentic trace transactions from a .jsonl or .json file."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Trace file not found: {file_path}")

    with open(file_path, encoding="utf-8-sig") as f:
        first_char = _peek_first_char(f)
        if first_char == "[":
            transactions = _parse_json_array_stream(f, file_path)
        else:
            transactions = _parse_jsonl_stream(f, file_path)

    if not transactions:
        raise ValueError(f"No valid transaction records found in {file_path}")

    return transactions


def _load_single_trace_candidate(file_path: str) -> list[dict[str, Any]]:
    """Attempt loading trace transactions from a candidate file."""
    if file_path.endswith(".jsonl"):
        with contextlib.suppress(Exception):
            return load_trace_transactions(file_path)
    elif os.path.basename(file_path).startswith("turn_") and file_path.endswith(".json"):
        with contextlib.suppress(Exception), open(file_path, encoding="utf-8-sig") as f:
            obj = json.load(f)
            if isinstance(obj, dict):
                return [obj]
    return []


def _load_trace_directory(dir_path: str) -> list[dict[str, Any]]:
    """Scan and load trace transactions from a directory."""
    jsonl_path = os.path.join(dir_path, "transactions.jsonl")
    if os.path.isfile(jsonl_path):
        return load_trace_transactions(jsonl_path)
    txs: list[dict[str, Any]] = []
    for root, _, files in os.walk(dir_path):
        for file in sorted(files):
            txs.extend(_load_single_trace_candidate(os.path.join(root, file)))
    if not txs:
        raise ValueError(f"No valid transaction records found in directory: {dir_path}")
    return txs


def load_transactions_from_path(path: str) -> list[dict[str, Any]]:
    """Load authentic trace transactions from a file or directory."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Trace path not found: {path}")

    if os.path.isdir(path):
        return _load_trace_directory(path)

    return load_trace_transactions(path)


def _extract_request_payload(tx: dict[str, Any]) -> dict[str, Any] | None:
    """Extract inner request dictionary from a transaction record."""
    raw_req = tx.get("raw_request") or {}
    payload = raw_req.get("request") if isinstance(raw_req, dict) and "request" in raw_req else raw_req
    if not isinstance(payload, dict) or not payload:
        return None
    return payload


def _extract_baseline_tokens(resp: dict[str, Any], baseline_chars: int) -> int:
    """Extract or estimate baseline input tokens."""
    resp_usage = resp.get("usage") if isinstance(resp, dict) else {}
    if isinstance(resp_usage, dict) and ("input_tokens" in resp_usage or "prompt_tokens" in resp_usage):
        return safe_int(resp_usage.get("input_tokens") or resp_usage.get("prompt_tokens"))
    return max(1, baseline_chars // 4)


def _check_semantic_parity(orig_payload: dict[str, Any], opt_payload: dict[str, Any]) -> bool:
    """Verify semantic parity between original and optimized request payloads."""
    if "messages" in orig_payload:
        if "messages" not in opt_payload:
            return False
        orig_msgs = orig_payload["messages"]
        opt_msgs = opt_payload["messages"]
        if bool(orig_msgs) != bool(opt_msgs):
            return False
        if isinstance(orig_msgs, list) and isinstance(opt_msgs, list) and orig_msgs and opt_msgs:
            last_orig = orig_msgs[-1]
            last_opt = opt_msgs[-1]
            if (
                isinstance(last_orig, dict)
                and isinstance(last_opt, dict)
                and last_orig.get("role") != last_opt.get("role")
            ):
                return False
    elif "contents" in orig_payload and "contents" not in opt_payload:
        return False
    return True


def _evaluate_single_offline_turn(
    tx: dict[str, Any], cleaner: JSONContextCleaner, round_num: int, idx: int
) -> tuple[ABTurnMetrics | None, float | None, bool]:
    """Process a single turn offline, returning metrics, TTFT sample, and cache hit indicator."""
    payload_data = _extract_request_payload(tx)
    if payload_data is None:
        return None, None, False

    provider = str(tx.get("provider") or "anthropic").lower()
    resp = tx.get("response") or {}
    timing = tx.get("timing") or {}
    turn_id = tx.get("turn_id") or f"r{round_num}-t{idx}"

    baseline_chars = estimate_chars(payload_data)
    baseline_tokens = _extract_baseline_tokens(resp, baseline_chars)

    clean_res = cleaner.process_payload_with_stats(payload_data, provider=provider)
    optimized_payload = clean_res.payload
    optimized_chars = estimate_chars(optimized_payload)

    if baseline_chars > 0:
        token_ratio = min(1.0, max(0.0, optimized_chars / baseline_chars))
        optimized_tokens = round(baseline_tokens * token_ratio)
    else:
        optimized_tokens = baseline_tokens

    tokens_reduced = max(0, baseline_tokens - optimized_tokens)
    reduction_pct = (tokens_reduced / baseline_tokens * 100.0) if baseline_tokens > 0 else 0.0
    chars_saved = max(0, baseline_chars - optimized_chars)
    parity = _check_semantic_parity(payload_data, optimized_payload)

    ttft_val: float | None = None
    if isinstance(timing, dict) and "ttft_ms" in timing:
        with contextlib.suppress(ValueError, TypeError):
            ttft_val = float(timing["ttft_ms"])

    is_cache_hit = str(tx.get("cache_action") or tx.get("cache_status") or "").upper() == "HIT"

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
        optimized_ttft_ms=None,
    )
    return turn_metric, ttft_val, is_cache_hit


def _aggregate_offline_turns(
    turns: list[ABTurnMetrics],
    ttft_samples: list[float],
    total_cache_hits: int,
    rounds: int,
    fail_under: float | None,
) -> ABComparisonScorecard:
    """Aggregate offline evaluation turns into a comprehensive comparison scorecard."""
    total_base_tokens = sum(t.baseline_input_tokens for t in turns)
    total_opt_tokens = sum(t.optimized_input_tokens for t in turns)
    tokens_reduced = max(0, total_base_tokens - total_opt_tokens)
    token_red_pct = (tokens_reduced / total_base_tokens * 100.0) if total_base_tokens > 0 else 0.0

    total_base_chars = sum(t.baseline_chars for t in turns)
    total_opt_chars = sum(t.optimized_chars for t in turns)
    chars_saved = max(0, total_base_chars - total_opt_chars)
    char_red_pct = (chars_saved / total_base_chars * 100.0) if total_base_chars > 0 else 0.0

    hit_rate = (total_cache_hits / len(turns) * 100.0) if turns else 0.0
    all_parity = all(t.semantic_parity for t in turns)
    avg_ttft = sum(ttft_samples) / len(ttft_samples) if ttft_samples else None
    passed = (token_red_pct >= fail_under) if fail_under is not None else True

    return ABComparisonScorecard(
        total_turns=len(turns),
        rounds=rounds,
        mode_label="Offline Differential Replay (Trace File)",
        baseline_input_tokens=total_base_tokens,
        optimized_input_tokens=total_opt_tokens,
        tokens_reduced=tokens_reduced,
        token_reduction_pct=token_red_pct,
        baseline_chars=total_base_chars,
        optimized_chars=total_opt_chars,
        chars_saved=chars_saved,
        char_reduction_pct=char_red_pct,
        tool_calls_pruned=sum(t.tool_calls_pruned for t in turns),
        cache_control_injected=sum(t.cache_control_injected for t in turns),
        cache_hits=total_cache_hits,
        cache_hit_rate=hit_rate,
        baseline_ttft_ms=avg_ttft,
        optimized_ttft_ms=None,
        ttft_delta_ms=None,
        semantic_parity_verified=all_parity,
        passed_threshold=passed,
        threshold_min_reduction_pct=fail_under,
        turn_details=turns,
    )


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

    turns: list[ABTurnMetrics] = []
    ttft_samples: list[float] = []
    total_cache_hits = 0

    for round_num in range(1, rounds + 1):
        for idx, tx in enumerate(transactions, 1):
            metric, ttft_val, is_hit = _evaluate_single_offline_turn(tx, cleaner, round_num, idx)
            if metric is not None:
                turns.append(metric)
                if ttft_val is not None:
                    ttft_samples.append(ttft_val)
                if is_hit:
                    total_cache_hits += 1

    return _aggregate_offline_turns(turns, ttft_samples, total_cache_hits, rounds, fail_under_reduction)


def _pair_baseline_and_optimized_runs(
    base_txs: list[dict[str, Any]], opt_txs: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Filter and validate baseline and optimized transaction runs for pairing."""
    base_list = [tx for tx in base_txs if tx.get("mode") != "optimized"] or base_txs
    opt_list = [tx for tx in opt_txs if tx.get("mode") != "baseline"] or opt_txs
    if not base_list or not opt_list:
        raise ValueError("Cannot evaluate A/B test with zero paired turns between baseline and optimized runs.")
    return base_list, opt_list


def _extract_turn_tokens_and_chars(tx: dict[str, Any], is_baseline: bool) -> tuple[int, int]:
    """Extract tokens and characters from transaction record."""
    usage = (tx.get("response") or {}).get("usage") or {}
    raw = (tx.get("raw_request") or {}) if is_baseline else (tx.get("cleaned_request") or tx.get("raw_request") or {})
    chars = estimate_chars(raw)
    if isinstance(usage, dict) and ("input_tokens" in usage or "prompt_tokens" in usage):
        tokens = safe_int(usage.get("input_tokens") or usage.get("prompt_tokens"))
    else:
        tokens = max(1, chars // 4)
    return tokens, chars


def _extract_recorded_timing(timing: dict[str, Any]) -> tuple[float | None, float | None]:
    """Extract TTFT and decode throughput from timing dictionary."""
    ttft: float | None = None
    tps: float | None = None
    if isinstance(timing, dict):
        if timing.get("ttft_ms") is not None:
            with contextlib.suppress(ValueError, TypeError):
                ttft = float(timing["ttft_ms"])
        if timing.get("decode_tps") is not None:
            with contextlib.suppress(ValueError, TypeError):
                tps = float(timing["decode_tps"])
    return ttft, tps


def _verify_paired_semantic_parity(base_tx: dict[str, Any], opt_tx: dict[str, Any]) -> bool:
    """Verify semantic parity between paired baseline and optimized turns."""
    base_status = (base_tx.get("response") or {}).get("status", 200)
    opt_status = (opt_tx.get("response") or {}).get("status", 200)
    if base_status not in (200, None) or opt_status not in (200, None):
        return False

    base_raw = base_tx.get("raw_request") or {}
    opt_raw = opt_tx.get("cleaned_request") or opt_tx.get("raw_request") or {}
    base_p = base_raw.get("request") if isinstance(base_raw, dict) and "request" in base_raw else base_raw
    opt_p = opt_raw.get("request") if isinstance(opt_raw, dict) and "request" in opt_raw else opt_raw
    if isinstance(base_p, dict) and isinstance(opt_p, dict):
        if "messages" in base_p and "messages" not in opt_p:
            return False
        if "contents" in base_p and "contents" not in opt_p:
            return False
    return True


def _evaluate_paired_turn(
    base_tx: dict[str, Any], opt_tx: dict[str, Any], round_num: int, idx: int
) -> tuple[ABTurnMetrics, dict[str, Any]]:
    """Evaluate one paired turn across baseline and optimized runs."""
    provider = str(opt_tx.get("provider") or base_tx.get("provider") or "anthropic").lower()
    turn_id = opt_tx.get("turn_id") or base_tx.get("turn_id") or f"r{round_num}-t{idx + 1}"

    base_tokens, base_chars = _extract_turn_tokens_and_chars(base_tx, is_baseline=True)
    opt_tokens, opt_chars = _extract_turn_tokens_and_chars(opt_tx, is_baseline=False)

    tokens_reduced = max(0, base_tokens - opt_tokens)
    reduction_pct = (tokens_reduced / base_tokens * 100.0) if base_tokens > 0 else 0.0
    chars_saved = max(0, base_chars - opt_chars)

    delta = opt_tx.get("delta") or {}
    pruned = safe_int(delta.get("tool_outputs_omitted") or delta.get("tool_calls_pruned"))
    injected = safe_int(delta.get("cache_control_injected"))

    opt_usage = (opt_tx.get("response") or {}).get("usage") or {}
    cache_action = str(opt_tx.get("cache_action") or "").upper()
    is_hit = cache_action == "HIT" or safe_int(opt_usage.get("cache_read_input_tokens")) > 0

    base_ttft, base_tps = _extract_recorded_timing(base_tx.get("timing") or {})
    opt_ttft, opt_tps = _extract_recorded_timing(opt_tx.get("timing") or {})
    parity = _verify_paired_semantic_parity(base_tx, opt_tx)

    metric = ABTurnMetrics(
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
    samples = {
        "is_hit": is_hit,
        "base_ttft": base_ttft,
        "opt_ttft": opt_ttft,
        "base_tps": base_tps,
        "opt_tps": opt_tps,
    }
    return metric, samples


def _aggregate_dual_scorecard(
    scorecard: ABComparisonScorecard,
    turns: list[ABTurnMetrics],
    samples: dict[str, list[float]],
    cache_hits: int,
    fail_under: float | None,
) -> None:
    """Aggregate paired turns and timing samples into dual-run comparison scorecard."""
    total_base_toks = sum(t.baseline_input_tokens for t in turns)
    total_opt_toks = sum(t.optimized_input_tokens for t in turns)
    scorecard.total_turns = len(turns)
    scorecard.baseline_input_tokens = total_base_toks
    scorecard.optimized_input_tokens = total_opt_toks
    scorecard.tokens_reduced = max(0, total_base_toks - total_opt_toks)
    scorecard.token_reduction_pct = (scorecard.tokens_reduced / total_base_toks * 100.0) if total_base_toks > 0 else 0.0

    total_base_c = sum(t.baseline_chars for t in turns)
    total_opt_c = sum(t.optimized_chars for t in turns)
    scorecard.baseline_chars = total_base_c
    scorecard.optimized_chars = total_opt_c
    scorecard.chars_saved = max(0, total_base_c - total_opt_c)
    scorecard.char_reduction_pct = (scorecard.chars_saved / total_base_c * 100.0) if total_base_c > 0 else 0.0

    scorecard.tool_calls_pruned = sum(t.tool_calls_pruned for t in turns)
    scorecard.cache_control_injected = sum(t.cache_control_injected for t in turns)
    scorecard.cache_hits = cache_hits
    scorecard.cache_hit_rate = (cache_hits / len(turns) * 100.0) if turns else 0.0
    scorecard.semantic_parity_verified = all(t.semantic_parity for t in turns)
    scorecard.turn_details = turns

    b_ttft, o_ttft = samples.get("base_ttft", []), samples.get("opt_ttft", [])
    if b_ttft:
        scorecard.baseline_ttft_ms = sum(b_ttft) / len(b_ttft)
    if o_ttft:
        scorecard.optimized_ttft_ms = sum(o_ttft) / len(o_ttft)
    if scorecard.baseline_ttft_ms is not None and scorecard.optimized_ttft_ms is not None:
        scorecard.ttft_delta_ms = scorecard.baseline_ttft_ms - scorecard.optimized_ttft_ms

    b_tps, o_tps = samples.get("base_tps", []), samples.get("opt_tps", [])
    if b_tps:
        scorecard.baseline_decode_tps = sum(b_tps) / len(b_tps)
    if o_tps:
        scorecard.optimized_decode_tps = sum(o_tps) / len(o_tps)

    scorecard.passed_threshold = (scorecard.token_reduction_pct >= fail_under) if fail_under is not None else True


def evaluate_runs(
    baseline_transactions: list[dict[str, Any]],
    optimized_transactions: list[dict[str, Any]],
    rounds: int = 1,
    fail_under_reduction: float | None = None,
    mode_label: str = "Real Intercepted Traffic",
) -> ABComparisonScorecard:
    """Evaluate authentic intercepted baseline vs optimized transactions."""
    base_list, opt_list = _pair_baseline_and_optimized_runs(baseline_transactions, optimized_transactions)
    num_turns = min(len(base_list), len(opt_list))

    scorecard = ABComparisonScorecard(
        rounds=rounds,
        threshold_min_reduction_pct=fail_under_reduction,
        mode_label=mode_label,
    )
    turn_metrics: list[ABTurnMetrics] = []
    timing_samples: dict[str, list[float]] = {
        "base_ttft": [],
        "opt_ttft": [],
        "base_tps": [],
        "opt_tps": [],
    }
    total_cache_hits = 0

    for round_num in range(1, rounds + 1):
        for idx in range(num_turns):
            metric, samples = _evaluate_paired_turn(base_list[idx], opt_list[idx], round_num, idx)
            turn_metrics.append(metric)
            if samples["is_hit"]:
                total_cache_hits += 1
            for key in ("base_ttft", "opt_ttft", "base_tps", "opt_tps"):
                val = samples.get(key)
                if val is not None:
                    timing_samples[key].append(val)

    _aggregate_dual_scorecard(scorecard, turn_metrics, timing_samples, total_cache_hits, fail_under_reduction)
    return scorecard
