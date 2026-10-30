"""Self-contained HTML/CSS/JavaScript dashboard for proxy telemetry."""

from __future__ import annotations

__all__ = ["render_dashboard_html"]


def render_dashboard_html() -> str:
    """Renders the self-contained HTML/CSS/JS dashboard for /holon/."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Holon Coherence — Live Optimization Dashboard</title>
  <style>
    :root {
      --bg: #0b0f17;
      --card-bg: #151d2a;
      --card-border: #243044;
      --text-main: #f1f5f9;
      --text-muted: #94a3b8;
      --accent-emerald: #10b981;
      --accent-blue: #3b82f6;
      --accent-indigo: #6366f1;
      --accent-amber: #f59e0b;
      --danger: #ef4444;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg);
      color: var(--text-main);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      padding: 24px;
      line-height: 1.5;
    }
    .container {
      max-width: 1100px;
      margin: 0 auto;
    }
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 24px;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--card-border);
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    .brand h1 {
      font-size: 1.5rem;
      font-weight: 700;
      letter-spacing: -0.02em;
    }
    .badge {
      font-size: 0.75rem;
      padding: 4px 10px;
      border-radius: 9999px;
      background: rgba(16, 185, 129, 0.15);
      color: var(--accent-emerald);
      border: 1px solid rgba(16, 185, 129, 0.3);
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .badge.disconnected {
      background: rgba(239, 68, 68, 0.15);
      color: var(--danger);
      border-color: rgba(239, 68, 68, 0.3);
    }
    .pulse-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: currentColor;
    }
    .controls {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    button {
      background: #1e293b;
      color: var(--text-main);
      border: 1px solid var(--card-border);
      padding: 8px 14px;
      border-radius: 6px;
      font-size: 0.85rem;
      cursor: pointer;
      font-weight: 500;
      transition: background 0.15s, border-color 0.15s;
    }
    button:hover {
      background: #334155;
      border-color: #475569;
    }
    button.primary {
      background: #2563eb;
      border-color: #3b82f6;
    }
    button.primary:hover {
      background: #1d4ed8;
    }
    .metrics-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 18px;
      margin-bottom: 24px;
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 20px;
      display: flex;
      flex-direction: column;
      position: relative;
      overflow: hidden;
    }
    .card-title {
      font-size: 0.85rem;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 8px;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .card-val {
      font-size: 2.2rem;
      font-weight: 700;
      letter-spacing: -0.03em;
      margin-bottom: 4px;
    }
    .card-val.emerald { color: var(--accent-emerald); }
    .card-val.blue { color: var(--accent-blue); }
    .card-val.indigo { color: var(--accent-indigo); }
    .card-val.amber { color: var(--accent-amber); }
    .card-desc {
      font-size: 0.8rem;
      color: var(--text-muted);
      margin-top: auto;
    }
    .details-table-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 24px;
    }
    .details-table-card h2 {
      font-size: 1.1rem;
      font-weight: 600;
      margin-bottom: 16px;
      border-bottom: 1px solid var(--card-border);
      padding-bottom: 12px;
    }
    .details-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 16px;
    }
    .detail-item {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    .detail-label {
      font-size: 0.8rem;
      color: var(--text-muted);
    }
    .detail-value {
      font-size: 1.15rem;
      font-weight: 600;
    }
    footer {
      margin-top: 24px;
      text-align: center;
      font-size: 0.75rem;
      color: var(--text-muted);
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="brand">
        <h1>Holon Coherence</h1>
        <span id="status-badge" class="badge">
          <span class="pulse-dot"></span>
          <span id="status-text">Connected</span>
        </span>
      </div>
      <div class="controls">
        <span id="last-updated" style="font-size: 0.8rem; color: var(--text-muted);">Updating...</span>
        <button id="toggle-refresh" onclick="toggleAutoRefresh()">Pause</button>
        <button class="primary" onclick="fetchMetrics()">Refresh Now</button>
      </div>
    </header>

    <div class="metrics-grid">
      <div class="card">
        <div class="card-title">🔧 Tool Calls Pruned</div>
        <div id="tool-calls-pruned" class="card-val emerald">0</div>
        <div class="card-desc">Redundant tool outputs omitted from context</div>
      </div>
      <div class="card">
        <div class="card-title">⚡ Tokens Reduced</div>
        <div id="tokens-reduced" class="card-val blue">0</div>
        <div class="card-desc">Estimated prompt tokens saved via compression</div>
      </div>
      <div class="card">
        <div class="card-title">🎯 Cache Hit Rate</div>
        <div id="cache-hit-rate" class="card-val indigo">0.0%</div>
        <div class="card-desc"><span id="cache-hits">0</span> hits / <span id="total-requests">0</span> requests</div>
      </div>
      <div class="card">
        <div class="card-title">⏱️ Latency & Throughput</div>
        <div id="avg-ttft" class="card-val amber">0.0 ms</div>
        <div class="card-desc">
          Prefill: <span id="prefill-tps">0.0</span> t/s (latest: <span id="latest-prefill-tps">0.0</span>) |
          Decode: <span id="decode-tps">0.0</span> t/s (latest: <span id="latest-decode-tps">0.0</span>)
        </div>
      </div>
    </div>

    <div class="details-table-card">
      <h2>Cumulative Telemetry Summary</h2>
      <div class="details-grid">
        <div class="detail-item">
          <span class="detail-label">Total Conversation Turns</span>
          <span id="total-turns" class="detail-value">0</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Upstream Cache Misses</span>
          <span id="cache-misses" class="detail-value">0</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Prefill Throughput (Avg)</span>
          <span id="avg-prefill-val" class="detail-value">0.0 tok/s</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Tail Prefill Throughput</span>
          <span id="tail-prefill-val" class="detail-value">0.0 tok/s</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Decode Samples (streaming only)</span>
          <span id="decode-samples" class="detail-value">0</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Total Input Tokens</span>
          <span id="total-input-tokens" class="detail-value">0</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Total Output Tokens</span>
          <span id="total-output-tokens" class="detail-value">0</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Cache Read Tokens</span>
          <span id="total-cache-read-tokens" class="detail-value">0</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Provider KV Cache Hit Rate</span>
          <span id="provider-cache-hit-rate" class="detail-value">0.0%</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Provider Cache Creation Tokens</span>
          <span id="cache-creation-tokens" class="detail-value">0</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Reasoning Tokens</span>
          <span id="reasoning-tokens" class="detail-value">0</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Raw Characters Saved</span>
          <span id="chars-saved" class="detail-value">0</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Turns Summarized</span>
          <span id="turns-summarized" class="detail-value">0</span>
        </div>
        <div class="detail-item">
          <span class="detail-label">Cache Control Breakpoints</span>
          <span id="cache-control-injected" class="detail-value">0</span>
        </div>
      </div>
    </div>

    <footer>
      Holon Coherence Optimization Gateway &bull; Live In-Memory Telemetry &bull; Polling /holon/api/metrics
    </footer>
  </div>

  <script>
    let isAutoRefreshing = true;
    let refreshInterval = null;

    function formatNumber(num) {
      if (num === null || num === undefined) return "0";
      return Number(num).toLocaleString();
    }

    async function fetchMetrics() {
      try {
        const resp = await fetch("/holon/api/metrics", { cache: "no-store" });
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        const data = await resp.json();

        document.getElementById("tool-calls-pruned").textContent = formatNumber(data.tool_calls_pruned);
        document.getElementById("tokens-reduced").textContent = formatNumber(data.tokens_reduced);
        document.getElementById("cache-hit-rate").textContent = ((data.cache_hit_rate || 0) * 100).toFixed(1) + "%";
        document.getElementById("cache-hits").textContent = formatNumber(data.cache_hits);
        document.getElementById("total-requests").textContent = formatNumber(data.total_requests);

        const hasTtft = data.avg_ttft_ms !== null && data.avg_ttft_ms !== undefined;
        const avgTtft = hasTtft ? data.avg_ttft_ms.toFixed(1) : "0.0";
        document.getElementById("avg-ttft").textContent = avgTtft + " ms";
        document.getElementById("decode-tps").textContent = (data.avg_decode_throughput_tps || 0).toFixed(1);
        document.getElementById("latest-decode-tps").textContent = (data.latest_decode_throughput_tps || 0).toFixed(1);
        document.getElementById("decode-samples").textContent = formatNumber(data.decode_samples);

        const prefillTps = (data.avg_prefill_throughput_tps || 0).toFixed(1);
        const latestPrefill = (data.latest_prefill_tps || 0).toFixed(1);
        const tailPrefill = (data.avg_tail_prefill_tps || 0).toFixed(1);
        document.getElementById("prefill-tps").textContent = prefillTps;
        document.getElementById("latest-prefill-tps").textContent = latestPrefill;
        document.getElementById("avg-prefill-val").textContent = prefillTps + " tok/s";
        document.getElementById("tail-prefill-val").textContent = tailPrefill + " tok/s";
        const kvHitPct = ((data.provider_cache_hit_rate || 0) * 100).toFixed(1);
        document.getElementById("provider-cache-hit-rate").textContent = kvHitPct + "%";
        document.getElementById("cache-creation-tokens").textContent = formatNumber(data.total_cache_creation_tokens);
        document.getElementById("reasoning-tokens").textContent = formatNumber(data.total_reasoning_tokens);

        document.getElementById("total-turns").textContent = formatNumber(data.total_turns);
        document.getElementById("cache-misses").textContent = formatNumber(data.cache_misses);
        document.getElementById("total-input-tokens").textContent = formatNumber(data.total_input_tokens);
        document.getElementById("total-output-tokens").textContent = formatNumber(data.total_output_tokens);
        document.getElementById("total-cache-read-tokens").textContent = formatNumber(data.total_cache_read_tokens);
        document.getElementById("chars-saved").textContent = formatNumber(data.chars_saved);
        document.getElementById("turns-summarized").textContent = formatNumber(data.turns_summarized);
        document.getElementById("cache-control-injected").textContent = formatNumber(data.cache_control_injected);

        document.getElementById("status-badge").className = "badge";
        document.getElementById("status-text").textContent = "Connected";
        document.getElementById("last-updated").textContent = "Updated " + new Date().toLocaleTimeString();
      } catch (err) {
        document.getElementById("status-badge").className = "badge disconnected";
        document.getElementById("status-text").textContent = "Disconnected";
        document.getElementById("last-updated").textContent = "Update failed: " + err.message;
      }
    }

    function toggleAutoRefresh() {
      isAutoRefreshing = !isAutoRefreshing;
      const btn = document.getElementById("toggle-refresh");
      if (isAutoRefreshing) {
        btn.textContent = "Pause";
        startPolling();
      } else {
        btn.textContent = "Resume";
        stopPolling();
      }
    }

    function startPolling() {
      if (refreshInterval) clearInterval(refreshInterval);
      fetchMetrics();
      refreshInterval = setInterval(fetchMetrics, 2000);
    }

    function stopPolling() {
      if (refreshInterval) {
        clearInterval(refreshInterval);
        refreshInterval = null;
      }
    }

    startPolling();
  </script>
</body>
</html>
"""
