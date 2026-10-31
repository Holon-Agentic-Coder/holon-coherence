"""Terminal metrics display and CLI dispatcher for holon-coherence."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

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
from holon_coherence.metrics.aggregation import (
    OfflineMetricsAccumulator,
    read_offline_metrics,
)
from holon_coherence.metrics_math import (
    DEFAULT_WIRE_LOG_DIR,
)

__all__ = [
    "OfflineMetricsAccumulator",
    "_read_offline_metrics",
    "handle",
    "handle_metrics",
    "read_offline_metrics",
    "register",
]


def _read_offline_metrics(wire_log_dir: str) -> dict[str, Any] | None:
    """Calculates cumulative metrics from persisted transactions.jsonl when proxy is offline."""
    return read_offline_metrics(wire_log_dir)


def _resolve_target_port(args: Any, port: int | None, container: str) -> int:
    """Resolve target proxy port from args, explicit argument, env, or container mapping."""
    target_port = getattr(args, "port", None) if args is not None else None
    if target_port is not None:
        return target_port
    if port is not None:
        return port
    env_port = os.getenv("HOLON_PROXY_PORT")
    if env_port:
        try:
            return int(env_port)
        except ValueError:
            return DEFAULT_PROXY_PORT
    mapped = get_container_mapped_port(container, DEFAULT_PROXY_PORT)
    return mapped if mapped is not None else DEFAULT_PROXY_PORT


def _query_live_proxy_metrics(port: int) -> dict[str, Any] | None:
    """Query live proxy endpoint for current metrics."""
    endpoint_url = f"http://127.0.0.1:{port}/holon/api/metrics"
    try:
        req = urllib.request.Request(endpoint_url, headers={"User-Agent": "holon-coherence-cli"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            if resp.status == 200:
                body = resp.read().decode("utf-8")
                data = json.loads(body)
                if isinstance(data, dict):
                    return data
    except Exception:
        return None
    return None


def _find_and_read_offline_metrics() -> dict[str, Any] | None:
    """Locate and aggregate offline wire logs across candidate directories."""
    candidate_dirs: list[str] = []
    env_wire_log = os.getenv("WIRE_LOG_DIR")
    if env_wire_log:
        candidate_dirs.append(env_wire_log)
    candidate_dirs.append(DEFAULT_WIRE_LOG_DIR)
    candidate_dirs.append(os.path.expanduser("~/.holon/logs"))
    candidate_dirs = list(dict.fromkeys(candidate_dirs))

    for c_dir in candidate_dirs:
        metrics = read_offline_metrics(c_dir)
        if metrics is not None:
            return metrics
    return None


def _render_unreachable_proxy_notice(port: int, endpoint_url: str) -> None:
    """Print error banner when live proxy is unreachable and offline mode is disallowed."""
    print("================================================================")
    print("           HOLON COHERENCE OPTIMIZATION METRICS")
    print(f"  🔴 PROXY STATUS: DOWN / UNREACHABLE (Port: {port})")
    print("================================================================")
    print(f"  ⚠️  Could not connect to live proxy at {endpoint_url}")
    print("  The holon-coherence proxy container is not running.")
    print("  Start it with 'holon-coherence start' or run an agent.")
    print("  (To view historical metrics from wire logs, pass --offline)")
    print("  mitmweb inspector: not running")
    print("================================================================")


def _render_missing_metrics_notice(is_json: bool, port: int, endpoint_url: str) -> None:
    """Print notice when neither live proxy nor offline logs are available."""
    if is_json:
        print(json.dumps({"error": "Proxy not reachable and no offline wire logs found", "port": port}))
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


def _render_overview_rows(metrics: dict[str, Any]) -> None:
    """Render terminal table rows for optimization overview and throughput."""
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
    total_requests = metrics.get("total_requests", 0)
    cache_hits = metrics.get("cache_hits", 0)

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


def _render_accounting_rows(metrics: dict[str, Any]) -> None:
    """Render terminal table rows for request and token accounting."""
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


def _render_metrics_terminal(
    metrics: dict[str, Any],
    is_live: bool,
    port: int,
    container: str,
    resolve_fn: Callable[..., ExposedEndpoints] | None,
) -> None:
    """Render full terminal layout with optimization, accounting, and endpoint blocks."""
    source_label = "Live Proxy (In-Memory)" if is_live else "Offline (Wire Log File)"
    resolve_endpoints = resolve_fn or resolve_container_endpoints
    endpoints = resolve_endpoints(container, fallback_proxy_port=port)
    if is_live:
        endpoints = ExposedEndpoints(proxy_port=port, web_port=endpoints.web_port, web_token=endpoints.web_token)

    print("=" * 64)
    print("              HOLON COHERENCE OPTIMIZATION METRICS")
    print(f"  Source: {source_label}  |  Port: {port}")
    print("=" * 64)
    _render_overview_rows(metrics)
    print("-" * 64)
    _render_accounting_rows(metrics)
    print("-" * 64)
    for row in format_endpoint_rows(endpoints, container_name=container):
        print(row)
    print("=" * 64)


def handle_metrics(
    args: Any = None,
    port: int | None = None,
    json_output: bool = False,
    live: bool = False,
    *,
    resolve_endpoints_fn: Callable[..., ExposedEndpoints] | None = None,
) -> int:
    """Fetch and display cumulative optimization metrics via terminal or JSON."""
    container = (getattr(args, "name", None) if args is not None else None) or get_container_name()
    target_port = _resolve_target_port(args, port, container)
    is_json = json_output or (getattr(args, "json", False) if args is not None else False)
    allow_offline = bool(getattr(args, "offline", False) if args is not None else False) or bool(
        os.getenv("WIRE_LOG_DIR")
    )

    endpoint_url = f"http://127.0.0.1:{target_port}/holon/api/metrics"
    metrics = _query_live_proxy_metrics(target_port)
    is_live = metrics is not None

    if not is_live and not is_json and not allow_offline:
        _render_unreachable_proxy_notice(target_port, endpoint_url)
        return 1

    if metrics is None:
        metrics = _find_and_read_offline_metrics()

    if metrics is None:
        _render_missing_metrics_notice(is_json, target_port, endpoint_url)
        return 1

    if is_json:
        print(json.dumps(metrics, indent=2))
        return 0

    _render_metrics_terminal(metrics, is_live, target_port, container, resolve_endpoints_fn)
    return 0


def handle(args: Any) -> int:
    """Handle metrics command."""
    return handle_metrics(args)


def register(subparsers: Any) -> argparse.ArgumentParser:
    """Register metrics subparser."""
    metrics_parser = subparsers.add_parser("metrics", help="Display cumulative optimization metrics")
    metrics_parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"Proxy listen port (default: {DEFAULT_PROXY_PORT} or HOLON_PROXY_PORT)",
    )
    metrics_parser.add_argument(
        "--name",
        default=None,
        help="Container name (defaults to HOLON_CONTAINER_NAME or holon-coherence-proxy)",
    )
    metrics_parser.add_argument(
        "--offline",
        action="store_true",
        help="Display offline telemetry metrics if live proxy is unreachable",
    )
    metrics_parser.add_argument("--json", action="store_true", help="Output metrics as raw JSON")
    metrics_parser.set_defaults(handler=handle, propagates_exit=True)
    return metrics_parser
