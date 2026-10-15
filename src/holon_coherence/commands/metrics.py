"""Terminal metrics display and CLI dispatcher for holon-coherence (Bean 0043)."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

from holon_coherence.commands.start import DEFAULT_PROXY_PORT

WIRE_LOG_DIR = os.getenv("WIRE_LOG_DIR", "todo/mitm_wire_logs")


def _read_offline_metrics(wire_log_dir: str) -> dict[str, Any] | None:
    """Calculates cumulative metrics from persisted transactions.jsonl when proxy is offline."""
    jsonl_path = os.path.join(wire_log_dir, "transactions.jsonl")
    if not os.path.exists(jsonl_path):
        return None

    total_requests = 0
    cache_hits = 0
    tool_calls_pruned = 0
    chars_saved = 0
    turns_summarized = 0
    cache_control_injected = 0
    total_input_tokens = 0
    total_output_tokens = 0
    total_cache_read_tokens = 0
    sum_ttft_ms = 0.0
    count_ttft = 0
    sum_decode_throughput_tps = 0.0
    count_decode = 0
    seen_turn_ids: set[str | int] = set()

    try:
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except Exception:
                    continue

                total_requests += 1
                turn_id = record.get("turn_id")
                if turn_id is not None:
                    seen_turn_ids.add(turn_id)

                if record.get("cache_action") == "HIT":
                    cache_hits += 1

                delta = record.get("delta", {})
                if isinstance(delta, dict):
                    tool_calls_pruned += delta.get("tool_outputs_omitted", 0)
                    chars_saved += delta.get("chars_saved", 0)
                    turns_summarized += delta.get("turns_summarized", 0)
                    cache_control_injected += delta.get("cache_control_injected", 0)

                resp = record.get("response", {})
                if isinstance(resp, dict):
                    usage = resp.get("usage", {})
                    if isinstance(usage, dict):
                        total_input_tokens += usage.get("input_tokens", 0)
                        total_output_tokens += usage.get("output_tokens", 0)
                        total_cache_read_tokens += usage.get("cache_read_input_tokens", 0)

                timing = record.get("timing", {})
                if isinstance(timing, dict):
                    ttft = timing.get("ttft_ms")
                    if ttft is not None and ttft > 0:
                        sum_ttft_ms += float(ttft)
                        count_ttft += 1

    except Exception:
        return None

    if total_requests == 0:
        return None

    cache_hit_rate = (cache_hits / total_requests) if total_requests > 0 else 0.0
    avg_ttft_ms = (sum_ttft_ms / count_ttft) if count_ttft > 0 else 0.0
    avg_decode_throughput_tps = (sum_decode_throughput_tps / count_decode) if count_decode > 0 else 0.0
    tokens_reduced = chars_saved // 4

    return {
        "total_turns": len(seen_turn_ids) or total_requests,
        "total_requests": total_requests,
        "cache_hits": cache_hits,
        "cache_misses": max(0, total_requests - cache_hits),
        "cache_hit_rate": round(cache_hit_rate, 4),
        "tool_calls_pruned": tool_calls_pruned,
        "tokens_reduced": tokens_reduced,
        "chars_saved": chars_saved,
        "turns_summarized": turns_summarized,
        "cache_control_injected": cache_control_injected,
        "avg_ttft_ms": round(avg_ttft_ms, 2),
        "avg_decode_throughput_tps": round(avg_decode_throughput_tps, 2),
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "total_cache_read_tokens": total_cache_read_tokens,
        "source": "offline_wire_log",
    }


def handle_metrics(
    args: Any = None,
    port: int | None = None,
    json_output: bool = False,
    live: bool = False,
) -> int:
    """Fetch and display cumulative optimization metrics via terminal or JSON.

    Args:
        args: Parsed argparse namespace or None.
        port: Explicit proxy port override.
        json_output: True to emit raw JSON instead of formatted text.
        live: True if live querying.

    Returns:
        int: Process exit code (0 on success, 1 on failure).
    """
    target_port = getattr(args, "port", None) if args is not None else None
    if target_port is None:
        target_port = port
    if target_port is None:
        env_port = os.getenv("HOLON_PROXY_PORT")
        if env_port:
            try:
                target_port = int(env_port)
            except ValueError:
                target_port = DEFAULT_PROXY_PORT
        else:
            target_port = DEFAULT_PROXY_PORT

    is_json = getattr(args, "json", False) if args is not None else False
    if json_output:
        is_json = True

    metrics: dict[str, Any] | None = None
    is_live = False

    # 1. Attempt query to live proxy metrics endpoint
    endpoint_url = f"http://127.0.0.1:{target_port}/holon/api/metrics"
    try:
        req = urllib.request.Request(endpoint_url, headers={"User-Agent": "holon-coherence-cli"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            if resp.status == 200:
                body = resp.read().decode("utf-8")
                metrics = json.loads(body)
                is_live = True
    except Exception:
        metrics = None

    # 2. Fallback to offline wire logs if proxy is not reachable
    if metrics is None:
        target_dir = os.getenv("WIRE_LOG_DIR", WIRE_LOG_DIR)
        metrics = _read_offline_metrics(target_dir)

    # 3. Handle case where neither live proxy nor offline logs are available
    if metrics is None:
        if is_json:
            print(json.dumps({"error": "Proxy not reachable and no offline wire logs found", "port": target_port}))
        else:
            print(f"⚠️  Could not connect to proxy at {endpoint_url}", file=sys.stderr)
            print("   No offline transaction logs found in WIRE_LOG_DIR.", file=sys.stderr)
            print(
                "   Start the proxy with 'holon-coherence start' or run an agent with 'holon-coherence claude'.",
                file=sys.stderr,
            )
        return 1

    # 4. JSON output
    if is_json:
        print(json.dumps(metrics, indent=2))
        return 0

    # 5. Formatted terminal output
    source_label = "Live Proxy (In-Memory)" if is_live else "Offline (Wire Log File)"
    hit_rate_pct = metrics.get("cache_hit_rate", 0.0) * 100.0
    tool_calls_pruned = metrics.get("tool_calls_pruned", 0)
    tokens_reduced = metrics.get("tokens_reduced", 0)
    chars_saved = metrics.get("chars_saved", 0)
    avg_ttft = metrics.get("avg_ttft_ms", 0.0)
    avg_decode_tps = metrics.get("avg_decode_throughput_tps", 0.0)
    total_turns = metrics.get("total_turns", 0)
    total_requests = metrics.get("total_requests", 0)
    cache_hits = metrics.get("cache_hits", 0)
    cache_misses = metrics.get("cache_misses", 0)
    total_in = metrics.get("total_input_tokens", 0)
    total_out = metrics.get("total_output_tokens", 0)
    total_cache_read = metrics.get("total_cache_read_tokens", 0)

    print("=" * 64)
    print("           HOLON COHERENCE OPTIMIZATION METRICS")
    print(f"  Source: {source_label}  |  Port: {target_port}")
    print("=" * 64)
    print(f"  🔧 Tool Calls Saved / Pruned:  {tool_calls_pruned:,}")
    print(f"  ⚡ Tokens Reduced:              {tokens_reduced:,} (Chars Saved: {chars_saved:,})")
    print(f"  🎯 Cache Hit Rate:              {hit_rate_pct:.1f}% ({cache_hits:,} hits / {total_requests:,} total)")
    print(f"  ⏱️  Average TTFT:               {avg_ttft:.2f} ms")
    print(f"  🚀 Decode Throughput:          {avg_decode_tps:.2f} tokens/sec")
    print("-" * 64)
    print(f"  📊 Total Turns:                {total_turns:,}")
    print(f"  🔄 Total Requests:             {total_requests:,} ({cache_hits:,} cached, {cache_misses:,} upstream)")
    print(f"  📥 Total Input Tokens:         {total_in:,}")
    print(f"  📤 Total Output Tokens:        {total_out:,}")
    print(f"  💾 Cache Read Tokens:          {total_cache_read:,}")
    print("=" * 64)
    print(f"🌐 Live Web Dashboard: http://127.0.0.1:{target_port}/holon/")
    print("=" * 64)
    return 0
