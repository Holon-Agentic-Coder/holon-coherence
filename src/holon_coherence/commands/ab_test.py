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
from typing import Any

from holon_coherence.ab_testing.evaluation import (
    ABComparisonScorecard,
    AbEvaluation,
    AbRun,
    ABRunConfig,
    ABTurnMetrics,
    evaluate_offline_ab_run,
    evaluate_runs,
    load_trace_transactions,
    load_transactions_from_path,
)
from holon_coherence.parsers.tokens import safe_int

logger = logging.getLogger(__name__)

__all__ = [
    "ABComparisonScorecard",
    "ABRunConfig",
    "ABTurnMetrics",
    "AbEvaluation",
    "AbRun",
    "evaluate_offline_ab_run",
    "evaluate_runs",
    "handle",
    "handle_ab_test",
    "load_trace_transactions",
    "load_transactions_from_path",
    "register",
    "run_live_replay_ab_test",
    "run_workload_ab_test",
    "set_proxy_mode",
]


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


def _prepare_live_replay_request(tx: dict[str, Any]) -> dict[str, Any] | None:
    """Extract payload, endpoint, and HTTP headers for live replay."""
    raw_req = tx.get("raw_request") or {}
    payload = raw_req.get("request") if isinstance(raw_req, dict) and "request" in raw_req else raw_req
    if not isinstance(payload, dict) or not payload:
        return None

    endpoint = tx.get("endpoint") or "https://api.anthropic.com/v1/messages"
    parsed = urllib.parse.urlparse(endpoint if "://" in endpoint else f"http://{endpoint}")
    headers = tx.get("headers") or {}
    clean_headers: dict[str, str] = {
        k: str(v) for k, v in headers.items() if not k.lower().startswith("content-length")
    }
    clean_headers["Host"] = parsed.netloc or "api.anthropic.com"
    clean_headers["Content-Type"] = "application/json"
    return {"payload": payload, "endpoint": endpoint, "headers": clean_headers}


def _dispatch_proxy_http_turn(
    req_info: dict[str, Any],
    mode: str,
    proxy_port: int,
    timeout: float,
) -> tuple[int, dict[str, Any], float]:
    """Execute a single HTTP request through proxy and measure latency."""
    headers = dict(req_info["headers"])
    headers["X-Holon-Mode"] = mode
    req_bytes = json.dumps(req_info["payload"]).encode("utf-8")
    t0 = time.perf_counter()
    conn = http.client.HTTPConnection("127.0.0.1", proxy_port, timeout=timeout)
    try:
        conn.request("POST", req_info["endpoint"], body=req_bytes, headers=headers)
        resp = conn.getresponse()
        resp_body = resp.read()
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        resp_json: dict[str, Any] = {}
        with contextlib.suppress(Exception):
            resp_json = json.loads(resp_body)
        return resp.status, resp_json.get("usage", {}), elapsed_ms
    finally:
        conn.close()


def _execute_live_turn(
    tx: dict[str, Any],
    idx: int,
    proxy_port: int,
    timeout: float,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Run baseline and optimized passes for a single trace transaction."""
    req_info = _prepare_live_replay_request(tx)
    if req_info is None:
        return None, None

    turn_id = tx.get("turn_id") or f"live-t{idx}"
    provider = tx.get("provider") or "anthropic"

    base_status, base_usage, t_base = _dispatch_proxy_http_turn(req_info, "baseline", proxy_port, timeout)
    base_tx = {
        "turn_id": turn_id,
        "provider": provider,
        "mode": "baseline",
        "raw_request": req_info["payload"],
        "response": {"status": base_status, "usage": base_usage},
        "timing": {"ttft_ms": round(t_base, 2)},
    }

    opt_status, opt_usage, t_opt = _dispatch_proxy_http_turn(req_info, "optimized", proxy_port, timeout)
    opt_tx = {
        "turn_id": turn_id,
        "provider": provider,
        "mode": "optimized",
        "raw_request": req_info["payload"],
        "cleaned_request": req_info["payload"],
        "response": {"status": opt_status, "usage": opt_usage},
        "timing": {"ttft_ms": round(t_opt, 2)},
    }
    return base_tx, opt_tx


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
        base_tx, opt_tx = _execute_live_turn(tx, idx, proxy_port, config.timeout)
        if base_tx is not None and opt_tx is not None:
            baseline_txs.append(base_tx)
            optimized_txs.append(opt_tx)

    return evaluate_runs(
        baseline_transactions=baseline_txs,
        optimized_transactions=optimized_txs,
        rounds=config.rounds,
        fail_under_reduction=config.fail_under_reduction,
        mode_label="Real Intercepted Traffic (Live Proxy Replay)",
    )


def _parse_ab_run_config(args: argparse.Namespace) -> ABRunConfig | None:
    """Extract ABRunConfig from argparse arguments."""
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
            return None

    return ABRunConfig(
        command=workload_cmd,
        trace_file=trace_path,
        baseline_path=baseline_path,
        optimized_path=optimized_path,
        live=live,
        rounds=max(1, rounds),
        fail_under_reduction=fail_under,
        output_json=bool(getattr(args, "json", False)),
    )


def _dispatch_trace_file_ab_test(config: ABRunConfig) -> ABComparisonScorecard:
    """Dispatch evaluation of a trace file in mixed or offline mode."""
    if not config.trace_file:
        raise ValueError("No trace file specified.")

    transactions = load_trace_transactions(config.trace_file)
    has_baseline = any(t.get("mode") == "baseline" for t in transactions)
    has_optimized = any(t.get("mode") == "optimized" for t in transactions)
    if has_baseline and has_optimized:
        base_txs = [t for t in transactions if t.get("mode") == "baseline"]
        opt_txs = [t for t in transactions if t.get("mode") == "optimized"]
        return evaluate_runs(
            baseline_transactions=base_txs,
            optimized_transactions=opt_txs,
            rounds=config.rounds,
            fail_under_reduction=config.fail_under_reduction,
            mode_label="Real Intercepted Traffic (Mixed Trace)",
        )
    return evaluate_offline_ab_run(
        transactions=transactions,
        rounds=config.rounds,
        fail_under_reduction=config.fail_under_reduction,
    )


def _dispatch_ab_test(config: ABRunConfig) -> ABComparisonScorecard:
    """Route benchmark execution according to configured mode."""
    if config.command:
        return run_workload_ab_test(config)

    if config.baseline_path and config.optimized_path:
        base_txs = load_transactions_from_path(config.baseline_path)
        opt_txs = load_transactions_from_path(config.optimized_path)
        return evaluate_runs(
            baseline_transactions=base_txs,
            optimized_transactions=opt_txs,
            rounds=config.rounds,
            fail_under_reduction=config.fail_under_reduction,
            mode_label="Real Intercepted Traffic (Logs)",
        )

    if config.trace_file and config.live:
        return run_live_replay_ab_test(config)

    if config.trace_file:
        return _dispatch_trace_file_ab_test(config)

    raise ValueError("One of --command (-c), --trace-file (-f), or both --baseline and --optimized must be provided.")


def _render_and_gate_ab_test(scorecard: ABComparisonScorecard, config: ABRunConfig) -> int:
    """Render scorecard to stdout and enforce gating constraints."""
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


def handle_ab_test(args: argparse.Namespace) -> int:
    """Handle holon-coherence ab-test command execution across real traffic and offline modes."""
    config = _parse_ab_run_config(args)
    if config is None:
        return 1

    try:
        scorecard = _dispatch_ab_test(config)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error loading trace transactions: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error during A/B benchmark execution: {exc}", file=sys.stderr)
        return 1

    return _render_and_gate_ab_test(scorecard, config)


def handle(args: Any) -> int:
    """Handle ab-test command."""
    return handle_ab_test(args)


def register(subparsers: Any) -> argparse.ArgumentParser:
    """Register ab-test subparser."""
    ab_parser = subparsers.add_parser(
        "ab-test",
        help="Run real-traffic A/B benchmark comparing baseline vs optimized runs",
    )
    ab_parser.add_argument(
        "--command",
        "-c",
        dest="workload_cmd",
        default=None,
        help="Command/agent workload to execute twice through proxy with real LLM traffic",
    )
    ab_parser.add_argument(
        "--trace-file",
        "-f",
        default=None,
        help="Path to authentic trace transactions (.jsonl or .json) file",
    )
    ab_parser.add_argument(
        "--live",
        action="store_true",
        help="Replay trace requests as live HTTP traffic through proxy against real upstream LLM endpoints",
    )
    ab_parser.add_argument(
        "--baseline",
        default=None,
        help="Path to authentic baseline wire log file or directory (Variant A)",
    )
    ab_parser.add_argument(
        "--optimized",
        default=None,
        help="Path to authentic optimized wire log file or directory (Variant B)",
    )
    ab_parser.add_argument(
        "--rounds",
        "-n",
        type=int,
        default=1,
        help="Number of evaluation rounds to run (default: 1)",
    )
    ab_parser.add_argument(
        "--fail-under-reduction",
        type=float,
        default=None,
        help="Enforce minimum token reduction percentage gate (e.g. 15.0 for 15%%)",
    )
    ab_parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON comparison scorecard",
    )
    ab_parser.set_defaults(handler=handle, propagates_exit=True)
    return ab_parser
