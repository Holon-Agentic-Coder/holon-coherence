"""Terminal metrics display and CLI dispatcher for holon-coherence."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

from holon_coherence.commands._dispatch import get_cli
from holon_coherence.commands.docker_ops import (
    get_container_mapped_port,
    get_container_name,
)
from holon_coherence.commands.endpoints import (
    ExposedEndpoints,
    format_endpoint_rows,
    format_table_row,
    resolve_container_endpoints,
)
from holon_coherence.commands.start import DEFAULT_PROXY_PORT
from holon_coherence.metrics_math import (
    DEFAULT_WIRE_LOG_DIR,
    average,
    compute_decode_tps,
    compute_prefill_tps,
    compute_tail_prefill_tps,
    positive_rate,
    positive_seconds,
)


def _milliseconds_to_seconds(value: Any) -> float | None:
    """Convert a wire-log millisecond reading to seconds, passing ``None`` through untouched."""
    if value is None:
        return None
    try:
        return float(value) / 1000.0
    except (TypeError, ValueError):
        return None


def _stored_rate(stored: Any, derived: float | None) -> float | None:
    """Resolve a wire-log rate against the same rate re-derived from raw timings.

    A stored positive number wins. A stored ``0.0`` (or any other unusable number) is *unmeasured*
    under this project's rate contract, so it stays unmeasured instead of being silently replaced by
    a re-derivation. A missing or ``null`` value means the writer had no rate to store, so the
    derived value is used -- which is what lets legacy records still report prefill speed.
    """
    if stored is not None and not isinstance(stored, bool):
        return positive_rate(stored)
    return derived


def _read_offline_metrics(wire_log_dir: str) -> dict[str, Any] | None:  # noqa: C901, PLR0912, PLR0915
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
    total_cache_creation_tokens = 0
    total_reasoning_tokens = 0
    sum_ttft_ms = 0.0
    count_ttft = 0
    sum_decode_throughput_tps = 0.0
    count_decode = 0
    sum_prefill_throughput_tps = 0.0
    count_prefill = 0
    latest_prefill_tps = 0.0
    sum_tail_prefill_tps = 0.0
    count_tail_prefill = 0
    latest_tail_prefill_tps = 0.0
    latest_decode_tps = 0.0
    latest_ttft_ms = 0.0
    latest_total_time_ms = 0.0
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
                in_toks = 0
                out_toks = 0
                cache_read_toks = 0
                cache_create_toks = 0
                reason_toks = 0
                if isinstance(resp, dict):
                    usage = resp.get("usage", {})
                    if isinstance(usage, dict):
                        in_toks = usage.get("input_tokens") or 0
                        out_toks = usage.get("output_tokens") or 0
                        cache_read_toks = usage.get("cache_read_input_tokens") or 0
                        cache_create_toks = usage.get("cache_creation_input_tokens") or 0
                        reason_toks = usage.get("reasoning_tokens") or usage.get("thinking_tokens") or 0
                        total_input_tokens += in_toks
                        total_output_tokens += out_toks
                        total_cache_read_tokens += cache_read_toks
                        total_cache_creation_tokens += cache_create_toks
                        total_reasoning_tokens += reason_toks

                timing = record.get("timing", {})
                if not isinstance(timing, dict):
                    timing = {}

                ttft_sec = positive_seconds(_milliseconds_to_seconds(timing.get("ttft_ms")))
                total_sec = positive_seconds(_milliseconds_to_seconds(timing.get("total_ms")))
                if ttft_sec is not None:
                    sum_ttft_ms += ttft_sec * 1000.0
                    count_ttft += 1
                    latest_ttft_ms = ttft_sec * 1000.0
                if total_sec is not None:
                    latest_total_time_ms = total_sec * 1000.0

                # Prefill is prompt tokens over the measured TTFT. Records that include measured timings
                # carry the computed rate explicitly, so live and offline readings agree even when the
                # two disagree with a naive re-derivation from rounded millisecond values.
                prefill_tps = _stored_rate(timing.get("prefill_tps"), compute_prefill_tps(in_toks, ttft_sec))
                if prefill_tps is not None:
                    sum_prefill_throughput_tps += prefill_tps
                    count_prefill += 1
                    latest_prefill_tps = prefill_tps

                uncached_in = max(0, in_toks - cache_read_toks)
                tail_p_tps = _stored_rate(
                    timing.get("tail_prefill_tps"), compute_tail_prefill_tps(uncached_in, ttft_sec)
                )
                if tail_p_tps is not None:
                    sum_tail_prefill_tps += tail_p_tps
                    count_tail_prefill += 1
                    latest_tail_prefill_tps = tail_p_tps

                # Decode throughput only ever comes from a genuine streaming window. Post-0097
                # records carry `streaming` plus the admitted `decode_tps`; legacy records have no
                # flag, so they fall back to `total_ms - ttft_ms` which is admitted only when the
                # window is physically plausible (>= 50ms), which is exactly what excludes the
                # 1-2ms socket-parse windows that produced 34k-38k tok/s artefacts.
                if "decode_tps" in timing:
                    decode_tps = positive_rate(timing.get("decode_tps"))
                else:
                    legacy_window = (
                        positive_seconds(total_sec - ttft_sec)
                        if total_sec is not None and ttft_sec is not None
                        else None
                    )
                    decode_tps = compute_decode_tps(out_toks, legacy_window, streaming=True)
                if decode_tps is not None:
                    sum_decode_throughput_tps += decode_tps
                    count_decode += 1
                    latest_decode_tps = decode_tps

    except Exception:
        return None

    if total_requests == 0:
        return None

    cache_hit_rate = (cache_hits / total_requests) if total_requests > 0 else 0.0
    provider_cache_hit_rate = (total_cache_read_tokens / total_input_tokens) if total_input_tokens > 0 else 0.0
    avg_ttft_ms = average(sum_ttft_ms, count_ttft)
    avg_decode_throughput_tps = average(sum_decode_throughput_tps, count_decode)
    avg_prefill_throughput_tps = average(sum_prefill_throughput_tps, count_prefill)
    avg_tail_prefill_tps = average(sum_tail_prefill_tps, count_tail_prefill)
    tokens_reduced = chars_saved // 4

    return {
        "total_turns": len(seen_turn_ids) or total_requests,
        "total_requests": total_requests,
        "cache_hits": cache_hits,
        "cache_misses": max(0, total_requests - cache_hits),
        "cache_hit_rate": round(cache_hit_rate, 4),
        "provider_cache_hit_rate": round(provider_cache_hit_rate, 4),
        "tool_calls_pruned": tool_calls_pruned,
        "tokens_reduced": tokens_reduced,
        "chars_saved": chars_saved,
        "turns_summarized": turns_summarized,
        "cache_control_injected": cache_control_injected,
        "avg_ttft_ms": round(avg_ttft_ms, 2),
        "avg_decode_throughput_tps": round(avg_decode_throughput_tps, 2),
        "latest_decode_throughput_tps": round(latest_decode_tps, 2),
        "decode_samples": count_decode,
        "avg_prefill_throughput_tps": round(avg_prefill_throughput_tps, 2),
        "latest_prefill_tps": round(latest_prefill_tps, 2),
        "avg_tail_prefill_tps": round(avg_tail_prefill_tps, 2),
        "latest_tail_prefill_tps": round(latest_tail_prefill_tps, 2),
        "latest_ttft_ms": round(latest_ttft_ms, 2),
        "latest_total_time_ms": round(latest_total_time_ms, 2),
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "total_cache_read_tokens": total_cache_read_tokens,
        "total_cache_creation_tokens": total_cache_creation_tokens,
        "total_reasoning_tokens": total_reasoning_tokens,
        "source": "offline_wire_log",
    }


def handle_metrics(  # noqa: C901, PLR0912, PLR0915
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
    container = getattr(args, "name", None) if args is not None else None
    container = container or get_container_name()
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
            mapped = get_container_mapped_port(container, DEFAULT_PROXY_PORT)
            target_port = mapped if mapped is not None else DEFAULT_PROXY_PORT

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

    allow_offline = getattr(args, "offline", False) if args is not None else False
    if os.getenv("WIRE_LOG_DIR"):
        allow_offline = True

    # If the live proxy is down, do not silently display stale offline metrics in terminal mode
    if not is_live and not is_json and not allow_offline:
        print("================================================================")
        print("           HOLON COHERENCE OPTIMIZATION METRICS")
        print(f"  🔴 PROXY STATUS: DOWN / UNREACHABLE (Port: {target_port})")
        print("================================================================")
        print(f"  ⚠️  Could not connect to live proxy at {endpoint_url}")
        print("  The holon-coherence proxy container is not running.")
        print("  Start it with 'holon-coherence start' or run an agent.")
        print("  (To view historical metrics from wire logs, pass --offline)")
        print("  mitmweb inspector: not running")
        print("================================================================")
        return 1

    # 2. Fallback to offline wire logs if proxy is not reachable
    if metrics is None:
        candidate_dirs = []
        env_wire_log = os.getenv("WIRE_LOG_DIR")
        if env_wire_log:
            candidate_dirs.append(env_wire_log)
        candidate_dirs.append(DEFAULT_WIRE_LOG_DIR)
        candidate_dirs.append(os.path.expanduser("~/.holon/logs"))
        candidate_dirs = list(dict.fromkeys(candidate_dirs))

        for c_dir in candidate_dirs:
            metrics = _read_offline_metrics(c_dir)
            if metrics is not None:
                break

    # 3. Handle case where neither live proxy nor offline logs are available
    if metrics is None:
        if is_json:
            print(json.dumps({"error": "Proxy not reachable and no offline wire logs found", "port": target_port}))
        else:
            print(f"⚠️  Could not connect to proxy at {endpoint_url}", file=sys.stderr)
            print(
                f"   No offline transaction logs found in WIRE_LOG_DIR, {DEFAULT_WIRE_LOG_DIR} or ~/.holon/logs.",
                file=sys.stderr,
            )
            print(
                "   Start the proxy with 'holon-coherence start' or run an agent with 'holon-coherence claude'.",
                file=sys.stderr,
            )
        return 1

    # 4. JSON output (deliberately endpoint-free, so machine output never carries the inspector token)
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
    latest_decode_tps = metrics.get("latest_decode_throughput_tps", 0.0)
    decode_samples = metrics.get("decode_samples")
    avg_prefill_tps = metrics.get("avg_prefill_throughput_tps", 0.0)
    latest_prefill_tps = metrics.get("latest_prefill_tps", 0.0)
    avg_tail_prefill_tps = metrics.get("avg_tail_prefill_tps", 0.0)
    total_turns = metrics.get("total_turns", 0)
    total_requests = metrics.get("total_requests", 0)
    cache_hits = metrics.get("cache_hits", 0)
    cache_misses = metrics.get("cache_misses", 0)
    total_in = metrics.get("total_input_tokens", 0)
    total_out = metrics.get("total_output_tokens", 0)
    total_cache_read = metrics.get("total_cache_read_tokens", 0)
    total_cache_create = metrics.get("total_cache_creation_tokens", 0)
    total_reasoning = metrics.get("total_reasoning_tokens", 0)
    provider_cache_rate = metrics.get("provider_cache_hit_rate")
    if provider_cache_rate is None:
        provider_cache_rate = (total_cache_read / total_in) if total_in > 0 else 0.0
    provider_cache_pct = provider_cache_rate * 100.0

    resolve_endpoints = getattr(get_cli(), "resolve_container_endpoints", resolve_container_endpoints)
    endpoints = resolve_endpoints(container, fallback_proxy_port=target_port)
    if is_live:
        # The live proxy answered on target_port, so that is the address to report, even when an
        # explicit --port points somewhere other than the container's mapping.
        endpoints = ExposedEndpoints(proxy_port=target_port, web_port=endpoints.web_port, web_token=endpoints.web_token)

    print("=" * 64)
    print("              HOLON COHERENCE OPTIMIZATION METRICS")
    print(f"  Source: {source_label}  |  Port: {target_port}")
    print("=" * 64)
    print(format_table_row("Tool Calls Saved / Pruned", f"{tool_calls_pruned:,}"))
    print(format_table_row("Tokens Reduced", f"{tokens_reduced:,} (Chars Saved: {chars_saved:,})"))
    print(format_table_row("Cache Hit Rate", f"{hit_rate_pct:.1f}% ({cache_hits:,} hits / {total_requests:,} total)"))
    print(format_table_row("Average TTFT", f"{avg_ttft:.2f} ms"))
    prefill_val = f"{avg_prefill_tps:.2f} tokens/sec (Latest: {latest_prefill_tps:.2f} t/s)"
    print(format_table_row("Prefill Throughput", prefill_val))
    if avg_tail_prefill_tps > 0:
        print(format_table_row("Tail Prefill Throughput", f"{avg_tail_prefill_tps:.2f} tokens/sec"))
    decode_suffix = f" (latest: {latest_decode_tps:.2f} t/s)" if latest_decode_tps else ""
    if not decode_samples and avg_decode_tps == 0:
        decode_suffix += "  [no streaming samples yet]"
    print(format_table_row("Decode Throughput", f"{avg_decode_tps:.2f} tokens/sec{decode_suffix}"))
    print("-" * 64)
    print(format_table_row("Total Turns", f"{total_turns:,}"))
    req_val = f"{total_requests:,} ({cache_hits:,} cached, {cache_misses:,} upstream)"
    print(format_table_row("Total Requests", req_val))
    print(format_table_row("Total Input Tokens", f"{total_in:,}"))
    print(format_table_row("Total Output Tokens", f"{total_out:,}"))
    print(format_table_row("Cache Read Tokens", f"{total_cache_read:,} ({provider_cache_pct:.1f}% KV hit)"))
    if total_cache_create > 0:
        print(format_table_row("Cache Write Tokens", f"{total_cache_create:,}"))
    if total_reasoning > 0:
        print(format_table_row("Reasoning Tokens", f"{total_reasoning:,}"))
    print("-" * 64)
    for row in format_endpoint_rows(endpoints, container_name=container):
        print(row)
    print("=" * 64)
    return 0
