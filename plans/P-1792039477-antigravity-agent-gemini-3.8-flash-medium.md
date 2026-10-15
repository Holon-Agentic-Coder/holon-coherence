I have launched `pytest -m "not integration_test"` in the workspace to verify the baseline test suite status and will review the results once complete.

# Plan for I-1792039462-coherence-web-metrics-and-local-llm-runners

- **Plan ID:** P-1792039477-antigravity-agent-gemini-3.8-flash-medium}
- **Parent Intent ID:** NONE
- **Agent:** antigravity-agent (version: 1.1.22)
- **Created At:** 2026-10-15T04:44:37.607Z

## Planner Autonomy Summary

- **Intent handling:** ACCEPT_AS_IS
- **Reframed intent (if applicable):** NONE
- **Exploration stance:** exploit with targeted empirical verification of cumulative telemetry metrics aggregation, embedded HTML/JSON dashboard serving via MITM flow interception, CLI metrics reporting, agent environment variable synthesis for local inference endpoints (Claude Code and AGY), Go loopback proxy bypass circumvention, and protocol adapters (strict Anthropic header/body normalizer and bidirectional Gemini v1beta to OpenAI bridge).
- **Safety priority level:** standard
- **Priority Justification:** This plan executes a cohesive batch delivery across Beans 0043 and 0051 in `holon-coherence`: exposing real-time token and tool optimization metrics via a live web dashboard and CLI command, while empowering AGY and Claude Code to execute seamlessly against host-local LLM servers (e.g. Ollama, vLLM, LM Studio, vMLX). The changes introduce protocol normalization and bridging within the proxy addon layer while strictly preserving un-mutated cloud traffic paths when no local endpoint is configured. All existing command contracts, security sandboxing (`0600` permissions), and baseline tests are maintained with zero regressions.

## Exploration

- **Proportion of steps that are exploratory:** 0.00
- **Justification:** The technical requirements across Beans 0043 and 0051 are fully specified, concrete, and unambiguous. Endpoint intercept paths (`/holon/api/metrics`, `/_holon/metrics`, `/holon/`), aggregated statistics dataclasses, CLI commands (`metrics`, `status`), CLI flags (`--model`, `--local-llm-base`, `--local-llm-endpoint`), Claude environment configuration (`ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, fallback suppression), AGY gateway configuration (`AGY_GATEWAY_URL` with non-loopback alias routing), Anthropic normalizer stripping rules, and Gemini-to-OpenAI bidirectional schema mappings are strictly defined. Execution focuses on deterministic implementation, protocol transformation, and hermetic unit testing.

## Overall Plan Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.95  |
| entropy_pred        | 0.5   |
| impact_pred         | 95.0  |
| cost_pred           | 5.1   |
| learning_value_pred | 4.0   |
| ev_pred             | 87.00 |

### Strategy Rationale

The overall plan metrics are computed directly from individual step evaluations and the config-driven Expected Value formula:

- **p_success_pred**: 0.95. Governed by the bidirectional Gemini-to-OpenAI protocol bridge bottleneck (Step 6: 0.95), where complex multi-turn message structures, inline function definitions, tool calls, and streaming SSE chunk translations must be verified against diverse LLM schemas.
- **entropy_pred**: 0.5. Represents the maximum single-step risk profile (Step 6: 0.5). The cumulative predicted entropy across all seven steps is 2.0 (`0.3 + 0.2 + 0.2 + 0.3 + 0.4 + 0.5 + 0.1 = 2.0`), comfortably below the allocated entropy budget of 15.0.
- **impact_pred**: 95.0. Successfully delivers Beans 0043 and 0051 in a single unified release: unlocks real-time operational visibility into context optimization (tool call pruning, token reduction, TTFT, throughput, cache hit rate) via both an interactive browser dashboard and terminal CLI, and enables AGY and Claude Code to execute hermetically against arbitrary local inference backends without external cloud dependencies.
- **cost_pred**: 5.1. Computed as the direct sum of step execution costs (`0.7 + 0.6 + 0.6 + 0.8 + 0.9 + 1.0 + 0.5 = 5.1`).
- **learning_value_pred**: 4.0. Establishes reusable, high-fidelity bidirectional protocol translation patterns (Gemini v1beta <-> OpenAI ChatCompletions), robust agent proxy routing circumventing Go loopback exemptions, and zero-dependency in-process dashboard rendering inside mitmproxy.
- **ev_pred**: 87.00. Derived using the physics-driven Expected Value formula: `EV = P(success) * Impact + mu * LearningValue - lambda * Delta_S_intent - Cost`. With system constants `lambda = 0.3` and `mu = 0.5` loaded from `holon-config/metrics/ev_config.json`:
  `EV = 0.95 * 95.0 + 0.5 * 4.0 - 0.3 * 0.5 - 5.1 = 90.25 + 2.0 - 0.15 - 5.1 = 87.00`.

## Safety & Constraint Alignment

- **Key world ruleset constraints that affect this plan:**
  - `holon-config/world/ruleset.md` §1 (Runtime & Environment Specification): Target Python `==3.13.*`, package execution managed strictly via `uv run` in the workspace root `.venv`.
  - `holon-config/world/ruleset.md` §2 (Coding Conventions & Standards): PEP 8 adherence, explicit static typing with standard library `typing`, docstring retention, and zero Ruff linting/formatting errors.
  - `holon-config/world/ruleset.md` §3 (Testing Constraints): Hermetic test isolation via `uv run pytest`, zero unstaged regressions across all baseline tests (`tests/test_cli.py`, `tests/test_mitm_addon_sse.py`, `tests/test_host_local.py`, etc.), and comprehensive unit tests for all added commands, endpoints, and protocol transformations.
  - `holon-config/world/constraints.md` §1 (Git Flow & Branch Disciplines): Isolated branches following Holon naming conventions (`I-.../P-.../E-.../_`), clean commit boundaries, no direct remote push to `main`.
  - `holon-config/world/constraints.md` §2 (Sandbox Containment): Operations strictly restricted to the workspace root; subprocess isolation without persistent shell environment mutations.
  - `holon-config/world/constraints.md` §3 (Ledger Immutability): Zero modifications to historical ledger records in `holon-knowledge/ledger/*.jsonl`.
  - `holon-config/world/constraints.md` §4 (Behavioral Invariants): Zero synthetic/mock data for benchmarking (Rule 1), universal credentials `HOLON_AGENT_KEY` (Rule 4), and strict repository separation (Rule 5).
- **Potential violations or edge cases:**
  - Breaking existing proxy interception or streaming SSE flows for cloud models (Anthropic Claude, OpenAI, Google Gemini) when introducing adapter logic.
  - Go runtime's net/http standard library silently bypassing `HTTP_PROXY` for `localhost` and `127.0.0.1` addresses when launching AGY against local endpoints.
  - Race conditions or threading lock contention when mutating cumulative optimization metrics counters across concurrent proxy flow threads.
  - Injected `cache_control` blocks or Anthropic-specific beta headers causing 400 Bad Request responses when forwarded to local inference engines (Ollama, LM Studio, vLLM).
  - Malformed or incomplete JSON streaming chunks during bidirectional Gemini v1beta <-> OpenAI SSE translation.
- **Mitigations built into the plan:**
  - Thread-safe thread-lock protected statistics collector for cumulative metrics in `mitm_addon.py`.
  - Conditional adapter execution: protocol normalizer and Gemini bridge are active only when requests target declared host-local endpoints or when explicit provider translation is negotiated. Unmatched or cloud traffic retains exact existing interception semantics.
  - Circumvent Go loopback proxy exemption for AGY by synthesizing non-loopback DNS/IP aliases (e.g., `127.0.0.1.nip.io` or container host gateway address) and setting `AGY_GATEWAY_URL`.
  - Anthropic local normalizer strictly prunes unsupported vendor fields (`thinking`, `output_config`, `context_management`, `cache_control`) and vendor `anthropic-beta` headers before forwarding to local endpoints.
  - Comprehensive unit tests covering all edge cases (streaming chunk reassembly, tool call argument schema mapping, usage calculation, error handling) in `tests/test_mitm_addon.py` and `tests/test_cli.py`.
- **Residual risk accepted (and why):**
  - Advanced provider-specific tool call formatting quirks across varying local model architectures (e.g. Qwen vs Llama vs Mistral tool call JSON dialects) may require future minor prompt tuning; standard OpenAI function calling schema format will serve as the canonical translation target.
- **Allocated Entropy Budget:** 15.0
- **Predicted Plan Entropy:** 2.0
- **Budget Compliance:** The cumulative predicted plan entropy of 2.0 remains well within the allocated budget limit of 15.0.

## Plan Description & Strategy

This implementation is divided into 7 sequential steps:

1. **Step 1: In-Memory Cumulative Optimization Metrics Collector & Interception Endpoints (`/holon/api/metrics`, `/holon/`) in `mitm_addon.py` (Bean 0043)**: Implement thread-safe metrics aggregator tracking cumulative tool calls pruned, tokens reduced, cache hit rate, TTFT, decode throughput, and total turns processed, and intercept `GET /holon/api/metrics` and `GET /_holon/metrics` returning live JSON telemetry.
2. **Step 2: Interactive Real-Time Web Dashboard at `/holon/` with Live Statistical Cards (Bean 0043)**: Implement self-contained, responsive HTML/CSS/JS dashboard served at `GET /holon/` and `GET /holon` displaying statistical metric cards (Tool Calls Saved, Tokens Reduced, Cache Hit Rate, Latency & Speedup) with configurable auto-refresh polling `/holon/api/metrics`.
3. **Step 3: Terminal Metrics CLI Command (`holon-coherence metrics`) & `status` Integration (Bean 0043)**: Add `metrics` subcommand to `cli.py` and modular command dispatcher `src/holon_coherence/commands/metrics.py` (fetching live data from active proxy or persisted transactions), and enrich `holon-coherence status` to print live cumulative metrics summary.
4. **Step 4: CLI Runner Flags & Environment Wiring for Local LLM Endpoints (`--model`, `--local-llm-endpoint`, Claude & AGY Envs) (Bean 0051)**: Extend `extract_runner_flags`, `build_agent_env`, and `run_agent` in `cli.py` and `src/holon_coherence/commands/agents.py` to parse `--model` and `--local-llm-endpoint` (aliased to `--local-llm-base`), configure Claude Code environment (`ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, model mapping, fallback suppression), and configure AGY environment (`AGY_GATEWAY_URL`, non-loopback alias, catalog resolution).
5. **Step 5: Strict Anthropic Protocol Normalizer with Incremental SSE Streaming Pass-Through in `mitm_addon.py` (Bean 0051)**: Implement Anthropic normalizer in `mitm_addon.py` that strips `thinking`, `output_config`, `context_management`, and `anthropic-beta` headers, suppresses injected `cache_control` when targeting local endpoints, and preserves incremental SSE streaming.
6. **Step 6: Bidirectional Gemini v1beta to OpenAI / Anthropic Bridge with Tool Call Translation in `mitm_addon.py` (Bean 0051)**: Implement protocol bridge in `mitm_addon.py` translating Gemini v1beta `generateContent` and `streamGenerateContent` requests into OpenAI `/v1/chat/completions` (or Anthropic `/v1/messages`), translating tool declarations, handling function call/response structures, translating usage tokens, and mapping streaming SSE chunks back into Gemini candidate structures.
7. **Step 7: Documentation Updates (`README.md`, `AGENTS.md`) and Comprehensive Hermetic Verification (Beans 0043 & 0051)**: Author comprehensive unit tests in `tests/test_mitm_addon.py`, `tests/test_cli.py`, and `tests/test_host_local.py`, update `README.md` and `AGENTS.md`, and verify full test suite pass and clean Ruff linting.

---

## Step 1: In-Memory Cumulative Optimization Metrics Collector & Interception Endpoints (`/holon/api/metrics`, `/holon/`) in `mitm_addon.py` (Bean 0043)

- **Sub‑intent recommendation:** NO
- **Reasoning:** Core telemetry state tracking and internal API endpoint interception within `src/holon_coherence/mitm_addon.py`.
- **Step Type:** IMPLEMENT
- **Exploration level:** EXPLOIT

### Intent & Git Integration

- **Step Intent:** Introduce thread-safe cumulative metrics aggregation within `mitm_addon.py` to track optimization statistics across all intercepted LLM transactions (total tool calls saved/pruned, total tokens reduced, global cache hit rate, average TTFT, decode throughput, total turns processed) and intercept `GET /holon/api/metrics` and `GET /_holon/metrics` to return real-time JSON statistics.
- **Git branch:** `I-1792039462-coherence-web-metrics-and-local-llm-runners/P-1792039477-antigravity-agent-gemini-3.8-flash-medium/E-cumulative-metrics-api/_`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- In `src/holon_coherence/mitm_addon.py`:
  - Define `CumulativeMetrics` dataclass or helper class with thread safety (`threading.Lock`):
    - Track `total_turns: int`
    - Track `total_requests: int`
    - Track `cache_hits: int`
    - Track `tool_calls_pruned: int` (accumulated from cleaner result `tool_outputs_omitted`)
    - Track `tokens_reduced: int` (estimated from characters saved or token reduction calculations)
    - Track `chars_saved: int`
    - Track `turns_summarized: int`
    - Track `cache_control_injected: int`
    - Track `sum_ttft_ms: float` and `count_ttft: int` to compute `avg_ttft_ms`
    - Track `sum_decode_throughput_tps: float` and `count_decode: int` to compute `avg_decode_throughput_tps`
    - Track `total_input_tokens: int`, `total_output_tokens: int`, `total_cache_read_tokens: int`
    - Provide a `to_dict()` snapshot method computing derived rates:
      - `cache_hit_rate`: `cache_hits / total_requests` if `total_requests > 0` else 0.0
      - `avg_ttft_ms`: `sum_ttft_ms / count_ttft` if `count_ttft > 0` else 0.0
      - `avg_decode_throughput_tps`: `sum_decode_throughput_tps / count_decode` if `count_decode > 0` else 0.0
      - `estimated_tokens_saved`: calculated directly or estimated via `chars_saved // 4`
  - In `MitmproxyAddon`:
    - Initialize an instance of `CumulativeMetrics`.
    - Update cumulative metrics in `request` whenever a cleaner result is produced or cache hit occurs.
    - Update cumulative metrics in `response` on response completion (adding token counts, TTFT, decode throughput, and turn completion).
    - In `request(flow)`:
      - Check if the request path matches `GET /holon/api/metrics` or `GET /_holon/metrics` (or when host is proxy host and path matches).
      - If matched, short-circuit flow by returning HTTP 200 with `Content-Type: application/json` containing `metrics.to_dict()` payload, bypass upstream forwarding, and return immediately.
  - Ensure compatibility with standalone proxy execution and mock testing without requiring live mitmproxy network sockets.

### Dependencies & Criticality

- **Depends on:** NONE
- **Is Bottleneck:** NO

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §2 (Static typing, docstrings, thread safety) and `constraints.md` §4 (Zero synthetic data; all metrics must derive from real transactions).
- **Potential failure modes for this step:** Thread race conditions mutating metric counters across concurrent flows, or endpoint intercept matching unintended external paths.
- **Guardrails and early‑abort checks:** Use threading locks around metrics mutations; restrict path matching specifically to `/holon/api/metrics` and `/_holon/metrics` with GET method.

### Success & Discard Criteria

- **Success:** Cumulative metrics accurately accumulate values across turns and cache hits; `GET /holon/api/metrics` and `GET /_holon/metrics` return status 200 with the live JSON statistics snapshot.
- **Discard:** Discard if endpoint interception introduces measurable latency to LLM proxy flows or fails to report accurate token reduction counts.

### Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.98  |
| entropy_pred        | 0.3   |
| impact_pred         | 88.0  |
| cost_pred           | 0.7   |
| learning_value_pred | 2.5   |
| ev_pred             | 86.70 |

### Step Metrics Rationale

- High `p_success_pred` (0.98) and low entropy (0.3) as metrics tracking hooks cleanly into existing `cleaner_result` and `flow.response` callbacks.
- Derivation: `EV = 0.98 * 88.0 + 0.5 * 2.5 - 0.3 * 0.3 - 0.7 = 86.24 + 1.25 - 0.09 - 0.7 = 86.70`.

---

## Step 2: Interactive Real-Time Web Dashboard at `/holon/` with Live Statistical Cards (Bean 0043)

- **Sub‑intent recommendation:** NO
- **Reasoning:** In-process embedded HTML/JS dashboard serving inside `src/holon_coherence/mitm_addon.py`.
- **Step Type:** IMPLEMENT
- **Exploration level:** EXPLOIT

### Intent & Git Integration

- **Step Intent:** Serve a visual web dashboard at `GET /holon/` (and `GET /holon`) featuring real-time statistical cards (Tool Calls Saved, Tokens Reduced, Cache Hit Rate, Latency & Speedup) with auto-refresh capability polling `/holon/api/metrics`.
- **Git branch:** `I-1792039462-coherence-web-metrics-and-local-llm-runners/P-1792039477-antigravity-agent-gemini-3.8-flash-medium/E-web-dashboard-ui/_`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- In `src/holon_coherence/mitm_addon.py`:
  - Define an embedded HTML/CSS/JavaScript template string for the dashboard:
    - Responsive layout styled with clean modern dark-mode aesthetic consistent with Holon UI standards.
    - Card 1: **Tool Calls Saved / Pruned** (displaying total tool calls omitted from context).
    - Card 2: **Tokens Reduced** (displaying total prompt and context tokens saved, and estimated bandwidth savings).
    - Card 3: **Global Cache Hit Rate** (displaying percentage of requests served from local cache, hits vs misses).
    - Card 4: **Latency & Speedup** (displaying average TTFT in ms and average decode throughput in tokens/sec).
    - Status & summary bar: total turns processed, active provider breakdown, and auto-refresh indicator.
    - Embedded lightweight JavaScript:
      - Automatically polls `/holon/api/metrics` every 2 seconds via `fetch()`.
      - Smoothly updates DOM card elements without page reload.
      - Includes pause/resume toggle for auto-refresh and manual "Refresh Now" button.
      - Gracefully handles connection drops or proxy restarts.
  - In `MitmproxyAddon.request`:
    - Intercept `GET /holon/` and `GET /holon` (or redirect `/holon` to `/holon/`).
    - Respond with HTTP 200, `Content-Type: text/html; charset=utf-8`, and the dashboard template payload.
    - Bypass upstream forwarding.
  - Ensure dashboard serves cleanly when accessed directly through the proxy or via the mitmweb port.

### Dependencies & Criticality

- **Depends on:** Step 1
- **Is Bottleneck:** NO

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §2 (No external un-vendored CDN dependencies; all CSS/JS must be strictly self-contained inline without network fetches).
- **Potential failure modes for this step:** External asset loading failing in offline/hermetic environments.
- **Guardrails and early‑abort checks:** Ensure 100% inline CSS and vanilla JavaScript without external font or script dependencies.

### Success & Discard Criteria

- **Success:** Navigating to `http://<proxy-host>:<port>/holon/` renders the visual dashboard, cards display live metrics, and JavaScript polls `/holon/api/metrics` dynamically updating values.
- **Discard:** Discard if dashboard requires external CDN access or fails to load in isolated sandboxes.

### Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.99  |
| entropy_pred        | 0.2   |
| impact_pred         | 85.0  |
| cost_pred           | 0.6   |
| learning_value_pred | 2.0   |
| ev_pred             | 84.49 |

### Step Metrics Rationale

- Very high `p_success_pred` (0.99) and low entropy (0.2) as the UI is self-contained inline HTML/JS rendered on intercepted HTTP requests.
- Derivation: `EV = 0.99 * 85.0 + 0.5 * 2.0 - 0.3 * 0.2 - 0.6 = 84.15 + 1.0 - 0.06 - 0.6 = 84.49`.

---

## Step 3: Terminal Metrics CLI Command (`holon-coherence metrics`) & `status` Integration (Bean 0043)

- **Sub‑intent recommendation:** NO
- **Reasoning:** Adding CLI metrics reporting and enriching status command in `src/holon_coherence/commands/` and `cli.py`.
- **Step Type:** IMPLEMENT
- **Exploration level:** EXPLOIT

### Intent & Git Integration

- **Step Intent:** Implement `holon-coherence metrics` CLI command to display formatted terminal optimization metrics, and integrate the live metrics display into the existing `holon-coherence status` command.
- **Git branch:** `I-1792039462-coherence-web-metrics-and-local-llm-runners/P-1792039477-antigravity-agent-gemini-3.8-flash-medium/E-cli-metrics-command/_`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- Create `src/holon_coherence/commands/metrics.py`:
  - Implement `handle_metrics(port: int | None = None, json_output: bool = False, live: bool = False) -> int`:
    - Determine active proxy port (CLI argument, `HOLON_PROXY_PORT`, or default 8080).
    - Attempt to query `http://127.0.0.1:<port>/holon/api/metrics` via standard library `urllib.request`.
    - If proxy is not running or unreachable, fallback gracefully to reading cumulative metrics from recent transactions in `WIRE_LOG_DIR/transactions.jsonl` if available, or print informative diagnostic message.
    - If `--json` flag is provided, output raw formatted JSON.
    - Otherwise, render formatted terminal table / card box:
      - Tool Calls Saved / Pruned
      - Tokens Reduced (Prompt & Context)
      - Global Cache Hit Rate & Hits/Misses
      - Average TTFT (ms) & Average Decode Throughput (tokens/sec)
      - Total Turns & Requests Processed
    - Return exit code 0 on success.
- In `src/holon_coherence/commands/docker_ops.py` (and `handle_status`):
  - Enrich `handle_status`:
    - When the proxy container is running, make a quick timeout-protected query to `/holon/api/metrics`.
    - If metrics are available, append a concise "Optimization Metrics Summary" section to the status output:
      - Displays Tool Calls Saved, Tokens Reduced, Cache Hit Rate, and Throughput.
      - Displays web dashboard URL link: `🌐 Live Dashboard: http://127.0.0.1:<web_port>/holon/`.
- In `src/holon_coherence/commands/__init__.py` and `cli.py`:
  - Register `metrics` subcommand in `argparse` parser supporting optional `--port` and `--json` arguments.
  - Re-export `handle_metrics` in `src/holon_coherence/cli.py` for backward compatibility with external imports and test suites.

### Dependencies & Criticality

- **Depends on:** Step 1
- **Is Bottleneck:** NO

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §2 & §3 (Clean exception handling, no hanging connections, static typing).
- **Potential failure modes for this step:** Command hanging if proxy is unresponsive or socket is blocked.
- **Guardrails and early‑abort checks:** Use short timeouts (e.g. 1.5 seconds) on `urllib.request.urlopen` when querying `/holon/api/metrics` from the CLI.

### Success & Discard Criteria

- **Success:** Running `holon-coherence metrics` outputs cleanly formatted terminal metrics or JSON; `holon-coherence status` shows the metrics summary and dashboard link.
- **Discard:** Discard if metrics CLI command crashes when the proxy is offline or blocks terminal execution.

### Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.98  |
| entropy_pred        | 0.2   |
| impact_pred         | 86.0  |
| cost_pred           | 0.6   |
| learning_value_pred | 2.0   |
| ev_pred             | 84.62 |

### Step Metrics Rationale

- High `p_success_pred` (0.98) and low entropy (0.2) as CLI command handling and formatting are straightforward standard library operations.
- Derivation: `EV = 0.98 * 86.0 + 0.5 * 2.0 - 0.3 * 0.2 - 0.6 = 84.28 + 1.0 - 0.06 - 0.6 = 84.62`.

---

## Step 4: CLI Runner Flags & Environment Wiring for Local LLM Endpoints (`--model`, `--local-llm-endpoint`, Claude & AGY Envs) (Bean 0051)

- **Sub‑intent recommendation:** NO
- **Reasoning:** Updating CLI argument extraction, environment builders, and agent dispatchers in `commands/agents.py`, `commands/runner.py`, and `cli.py`.
- **Step Type:** IMPLEMENT
- **Exploration level:** EXPLOIT

### Intent & Git Integration

- **Step Intent:** Add first-class endpoint and model selection to `cli.py` and `commands/agents.py` supporting `--model` and `--local-llm-base` / `--local-llm-endpoint`, configure Claude Code environment variables, configure AGY environment variables (setting `AGY_GATEWAY_URL` and non-loopback alias to circumvent Go's loopback proxy exemption), and wire catalog alias resolution.
- **Git branch:** `I-1792039462-coherence-web-metrics-and-local-llm-runners/P-1792039477-antigravity-agent-gemini-3.8-flash-medium/E-local-llm-runner-flags/_`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- In `src/holon_coherence/commands/agents.py`:
  - Update `RunnerFlags` namedtuple to include `model: str | None = None` and ensure `local_llm_base` captures either `--local-llm-base` or `--local-llm-endpoint`.
  - Update `extract_runner_flags`:
    - Parse `--model` and `--model=<val>`, storing value in `model`.
    - Parse `--local-llm-endpoint` and `--local-llm-endpoint=<val>`, treating it identically to `--local-llm-base`.
    - Retain agent argument ordering and correctly handle `--` separator.
  - Update `build_agent_env`:
    - Accept `model: str | None = None` and `local_llm_base: str | None = None` parameters (with default `None` for backward compatibility).
    - When `local_llm_base` is present (targeting host-local or custom LLM):
      - For Claude Code (`claude`):
        - Set `ANTHROPIC_BASE_URL` to route through the proxy: `http://127.0.0.1:<port>` (or `http://127.0.0.1:<port>/v1`).
        - Set `ANTHROPIC_AUTH_TOKEN` (defaulting to `holon_key` or `"sk-ant-local"` if unset).
        - If `model` is specified, set `ANTHROPIC_MODEL` (or model mapping flags).
        - Suppress fallback: set `ANTHROPIC_DISABLE_TELEMETRY=1`, `CLAUDE_SUPPRESS_FALLBACK=1`, and ensure no cloud failover occurs.
      - For AGY (`agy` / `antigravity`):
        - Explicitly set `AGY_GATEWAY_URL` (specifically NOT `GOOGLE_GEMINI_BASE_URL`, adhering strictly to Bean 0051 specification).
        - Address Go loopback proxy exemption: Go's `net/http` standard library bypasses `HTTP_PROXY` for `localhost` and `127.0.0.1`. Circumvent this by pointing `AGY_GATEWAY_URL` to a non-loopback spelling/alias (e.g. `http://127.0.0.1.nip.io:<port>` or host gateway alias configured in `host_local.py`).
        - Catalog alias resolution: if `model` is specified, resolve alias to local model catalog entry and export appropriate environment configuration.
      - For other agents (`codex`, `opencode`, `pi`):
        - Set corresponding base URLs (`OPENAI_BASE_URL`, `OPENCODE_BASE_URL`, etc.) targeting the proxy port.
  - Update `run_agent`:
    - Thread `flags.model` and `flags.local_llm_base` into `build_agent_env`.
    - Ensure container startup registers the local LLM route via `ensure_proxy_running(..., host_local_spec=route.container_env_value)`.
- In `src/holon_coherence/cli.py`:
  - Re-export updated `RunnerFlags`, `extract_runner_flags`, `build_agent_env`, and `run_agent`.
  - Update CLI `--help` messages to document `--model` and `--local-llm-endpoint`.

### Dependencies & Criticality

- **Depends on:** NONE
- **Is Bottleneck:** YES (central runner flag extraction and environment synthesis for all agents)

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §2 (Static typing, docstrings) and `constraints.md` §4 (Universal credentials `HOLON_AGENT_KEY`).
- **Potential failure modes for this step:** Go runtime ignoring proxy settings due to loopback addresses, or breaking cloud agent runs when local endpoint flags are absent.
- **Guardrails and early‑abort checks:** Cloud execution paths must remain 100% unaltered when `--local-llm-base` / `--local-llm-endpoint` are not specified.

### Success & Discard Criteria

- **Success:** `extract_runner_flags` correctly parses `--model` and `--local-llm-endpoint`; `build_agent_env` configures `ANTHROPIC_BASE_URL` and `ANTHROPIC_AUTH_TOKEN` for Claude, and `AGY_GATEWAY_URL` with non-loopback alias for AGY; cloud runs retain exact existing behavior.
- **Discard:** Discard if default cloud agent launches fail or if Go proxy bypass prevents AGY from reaching the proxy.

### Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.97  |
| entropy_pred        | 0.3   |
| impact_pred         | 90.0  |
| cost_pred           | 0.8   |
| learning_value_pred | 3.0   |
| ev_pred             | 87.91 |

### Step Metrics Rationale

- `p_success_pred` (0.97) and `entropy_pred` (0.3) reflect the need to carefully coordinate flag extraction and environment variables across multiple agent types while maintaining backward compatibility.
- Derivation: `EV = 0.97 * 90.0 + 0.5 * 3.0 - 0.3 * 0.3 - 0.8 = 87.30 + 1.5 - 0.09 - 0.8 = 87.91`.

---

## Step 5: Strict Anthropic Protocol Normalizer with Incremental SSE Streaming Pass-Through in `mitm_addon.py` (Bean 0051)

- **Sub‑intent recommendation:** NO
- **Reasoning:** Protocol adaptation for Anthropic requests targeting non-cloud LLM engines within `src/holon_coherence/mitm_addon.py`.
- **Step Type:** IMPLEMENT
- **Exploration level:** EXPLOIT

### Intent & Git Integration

- **Step Intent:** Implement a strict Anthropic protocol normalizer in `mitm_addon.py` that strips unsupported vendor constructs (`thinking`, `output_config`, `context_management`), strips vendor `anthropic-beta` headers, suppresses injected `cache_control` when targeting local endpoints, and supports incremental SSE streaming pass-through.
- **Git branch:** `I-1792039462-coherence-web-metrics-and-local-llm-runners/P-1792039477-antigravity-agent-gemini-3.8-flash-medium/E-anthropic-normalizer/_`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- In `src/holon_coherence/mitm_addon.py`:
  - Implement `normalize_anthropic_request(flow: Any, data: dict[str, Any], is_local_target: bool) -> tuple[dict[str, Any], bool]`:
    - If targeting non-cloud servers (determined by host-local target check or local endpoint configuration):
      - Strip `thinking` field from top-level body.
      - Strip `output_config` field from top-level body.
      - Strip `context_management` field from top-level body.
      - Recursively traverse messages and system prompts:
        - Strip `cache_control` blocks from text/tool content parts (e.g. `{"type": "ephemeral"}`).
      - In request headers:
        - Remove or sanitize vendor `anthropic-beta` header (e.g. `prompt-caching-2024-07-31`, `thinking-2024-11-04`, `context-management-2025-01-01`).
    - Suppress context cleaner's `cache_control` injection when targeting non-cloud servers to prevent downstream parsing errors.
  - In `request(flow)`:
    - Integrate `normalize_anthropic_request` into request interception flow prior to sending to local upstream.
  - In `responseheaders` and `response`:
    - Ensure SSE streaming pipeline (`sse_stream_wrapper`, `response.stream`) cleanly passes through incremental chunks without buffering or truncating Anthropic event types (`message_start`, `content_block_start`, `content_block_delta`, `message_delta`, `message_stop`).
    - Verify token count extraction handles both standard and normalized Anthropic response structures.
  - Ensure cloud requests to `api.anthropic.com` are untouched, preserving full thinking and prompt caching capabilities.

### Dependencies & Criticality

- **Depends on:** Step 4
- **Is Bottleneck:** NO

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §2 (Static typing, docstrings) and §3 (Hermetic unit test validation).
- **Potential failure modes for this step:** Accidental stripping of fields for official Anthropic cloud API requests, breaking prompt caching or thinking in cloud runs.
- **Guardrails and early‑abort checks:** Guard all normalization logic behind `is_local_target` check. If endpoint is not in `targets_from_env()` or local host list, skip normalization entirely.

### Success & Discard Criteria

- **Success:** Requests targeting local LLM servers have `thinking`, `output_config`, `context_management`, `anthropic-beta` headers, and `cache_control` stripped; local server processes the request without 400 Bad Request; cloud requests remain unchanged.
- **Discard:** Discard if normalization alters cloud requests or breaks SSE streaming delivery to Claude Code.

### Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.96  |
| entropy_pred        | 0.4   |
| impact_pred         | 92.0  |
| cost_pred           | 0.9   |
| learning_value_pred | 3.5   |
| ev_pred             | 89.05 |

### Step Metrics Rationale

- `p_success_pred` (0.96) and `entropy_pred` (0.4) reflect the nuances of Anthropic beta header stripping and message payload structure sanitization.
- Derivation: `EV = 0.96 * 92.0 + 0.5 * 3.5 - 0.3 * 0.4 - 0.9 = 88.32 + 1.75 - 0.12 - 0.9 = 89.05`.

---

## Step 6: Bidirectional Gemini v1beta to OpenAI / Anthropic Bridge with Tool Call Translation in `mitm_addon.py` (Bean 0051)

- **Sub‑intent recommendation:** NO
- **Reasoning:** Complex protocol bridging for Gemini requests targeting local OpenAI/Anthropic backends in `src/holon_coherence/mitm_addon.py`.
- **Step Type:** IMPLEMENT
- **Exploration level:** EXPLOIT

### Intent & Git Integration

- **Step Intent:** Implement a bidirectional Gemini bridge in `mitm_addon.py` translating Google Gemini v1beta `generateContent` and `streamGenerateContent` requests to OpenAI `/v1/chat/completions` (or Anthropic `/v1/messages`), with complete bidirectional translation of messages, tool declarations, tool calls, tool responses, token usage metadata, and SSE streaming chunks.
- **Git branch:** `I-1792039462-coherence-web-metrics-and-local-llm-runners/P-1792039477-antigravity-agent-gemini-3.8-flash-medium/E-gemini-openai-bridge/_`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- In `src/holon_coherence/mitm_addon.py`:
  - Implement request translation: `translate_gemini_to_openai_request(gemini_req: dict[str, Any]) -> dict[str, Any]`:
    - Translate `contents` array:
      - Map `role: "user"` to OpenAI `role: "user"`.
      - Map `role: "model"` to OpenAI `role: "assistant"`.
      - Translate parts:
        - Text parts `{"text": ...}` to text content.
        - Tool call parts `{"functionCall": {"name": ..., "args": ...}}` to OpenAI `tool_calls` structure (`[{"id": ..., "type": "function", "function": {"name": ..., "arguments": json.dumps(args)}}]`).
        - Tool response parts `{"functionResponse": {"name": ..., "response": ...}}` to OpenAI `role: "tool"` messages with matching `tool_call_id`.
    - Translate `systemInstruction` parts to OpenAI `role: "system"` message.
    - Translate `tools` with `functionDeclarations` to OpenAI `tools` (`[{"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}]`).
    - Translate `generationConfig`:
      - `temperature` -> `temperature`
      - `maxOutputTokens` -> `max_tokens`
      - `stopSequences` -> `stop`
      - `topP` -> `top_p`
    - Rewrite flow destination:
      - Change path from `/v1beta/models/...:generateContent` or `:streamGenerateContent` to `/v1/chat/completions`.
      - Tag flow as bridged (`flow.is_gemini_bridged = True`).
  - Implement response translation:
    - For non-streaming responses: `translate_openai_to_gemini_response(openai_resp: dict[str, Any]) -> dict[str, Any]`:
      - Map `choices[0].message.content` to Gemini `candidates[0].content.parts[0].text`.
      - Map `choices[0].message.tool_calls` to Gemini `candidates[0].content.parts` with `functionCall` objects.
      - Map finish reasons (`stop` -> `STOP`, `tool_calls` -> `STOP` / `TOOL_CALLS`).
      - Map `usage` (`prompt_tokens`, `completion_tokens`, `total_tokens`) to Gemini `usageMetadata` (`promptTokenCount`, `candidatesTokenCount`, `totalTokenCount`).
    - For streaming responses:
      - Intercept SSE chunks (`chat.completion.chunk`) and convert to Gemini streaming SSE format (`data: {"candidates": [{"content": {"parts": [...]}}]}`).
  - In `request` and `response` hooks:
    - Activate the bridge only when the destination is a host-local endpoint or when explicit local routing is in effect.
    - If request is targeting Google cloud (`generativelanguage.googleapis.com`), retain standard direct pass-through behavior without translation.

### Dependencies & Criticality

- **Depends on:** Step 4 & Step 5
- **Is Bottleneck:** YES (complex bidirectional schema translation for agent interaction loops)

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §2 (Static typing, robust error handling) and §3 (Hermetic testing).
- **Potential failure modes for this step:** Function call argument serialization issues, missing tool IDs, or streaming chunk delimiter corruption causing agent parse errors.
- **Guardrails and early‑abort checks:** Provide bidirectional unit tests validating round-trip translation of complex tool calls, parallel tool calls, multi-turn conversations, and error responses.

### Success & Discard Criteria

- **Success:** AGY generates requests in Gemini v1beta format; proxy seamlessly translates them to OpenAI chat completions; local model executes tool calls; responses and streaming chunks are translated back to Gemini format; AGY executes tool actions successfully.
- **Discard:** Discard if translation loses tool parameters or corrupts streaming SSE event boundaries.

### Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.95  |
| entropy_pred        | 0.5   |
| impact_pred         | 95.0  |
| cost_pred           | 1.0   |
| learning_value_pred | 4.0   |
| ev_pred             | 91.10 |

### Step Metrics Rationale

- `p_success_pred` (0.95) and `entropy_pred` (0.5) reflect the algorithmic complexity of bidirectional schema mapping between Gemini and OpenAI function calling.
- Derivation: `EV = 0.95 * 95.0 + 0.5 * 4.0 - 0.3 * 0.5 - 1.0 = 90.25 + 2.0 - 0.15 - 1.0 = 91.10`.

---

## Step 7: Documentation Updates (`README.md`, `AGENTS.md`) and Comprehensive Hermetic Verification (Beans 0043 & 0051)

- **Sub‑intent recommendation:** NO
- **Reasoning:** Updating documentation, authoring complete unit test suite, and executing test verification.
- **Step Type:** VERIFY
- **Exploration level:** EXPLOIT

### Intent & Git Integration

- **Step Intent:** Author exhaustive unit tests in `tests/test_mitm_addon.py` and `tests/test_cli.py`, update documentation in `README.md` and `AGENTS.md` covering the web metrics dashboard, CLI metrics command, and local LLM runner options for AGY and Claude Code, and verify all tests pass with clean Ruff checks.
- **Git branch:** `I-1792039462-coherence-web-metrics-and-local-llm-runners/P-1792039477-antigravity-agent-gemini-3.8-flash-medium/E-docs-and-verification/_`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- In `tests/test_mitm_addon.py`:
  - Test cumulative metrics aggregation across multiple simulated turns.
  - Test `GET /holon/api/metrics` and `GET /_holon/metrics` endpoint interception returning correct JSON payload.
  - Test `GET /holon/` dashboard endpoint returning valid HTML with statistical card elements and auto-refresh script.
  - Test strict Anthropic normalizer: stripping `thinking`, `output_config`, `context_management`, `anthropic-beta` headers, and suppressing `cache_control` on local endpoints.
  - Test Gemini-to-OpenAI request bridge: message translation, function call translation, system instructions, and generation config.
  - Test OpenAI-to-Gemini response bridge: candidate content, function call translation, streaming chunk translation, and usage metadata.
  - Verify cloud traffic remains unmodified.
- In `tests/test_cli.py`:
  - Test `holon-coherence metrics` command with terminal output and `--json` flag.
  - Test `holon-coherence status` displaying optimization metrics summary and web dashboard link.
  - Test `extract_runner_flags` for `--model` and `--local-llm-endpoint`.
  - Test `build_agent_env` for Claude Code (`ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, fallback suppression).
  - Test `build_agent_env` for AGY (`AGY_GATEWAY_URL` with non-loopback alias).
- In `README.md`:
  - Document the web metrics dashboard (`/holon/`) and `holon-coherence metrics` CLI command.
  - Document local LLM execution using `--model` and `--local-llm-endpoint` / `--local-llm-base` with AGY and Claude Code.
  - Provide quickstart examples for running Ollama, vLLM, and LM Studio with AGY and Claude Code.
- In `AGENTS.md`:
  - Document guidelines for testing local endpoints and protocol adapters.
- Verification Commands:
  - Run `uv run pytest -m "not integration_test"`.
  - Run `uv run ruff check .`.
  - Run `uv run ruff format --check .`.

### Dependencies & Criticality

- **Depends on:** Step 1, Step 2, Step 3, Step 4, Step 5, Step 6
- **Is Bottleneck:** NO

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §3 (All tests must pass, zero unstaged regressions).
- **Potential failure modes for this step:** Regressions in existing tests or formatting/linting issues.
- **Guardrails and early‑abort checks:** Hermetic unit test isolation with fast execution (< 20 seconds).

### Success & Discard Criteria

- **Success:** 100% of unit tests pass; `ruff check` and `ruff format` report zero errors; documentation is comprehensive and accurate.
- **Discard:** Discard if any baseline test fails or if linting produces violations.

### Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.99  |
| entropy_pred        | 0.1   |
| impact_pred         | 82.0  |
| cost_pred           | 0.5   |
| learning_value_pred | 1.5   |
| ev_pred             | 81.40 |

### Step Metrics Rationale

- Very high `p_success_pred` (0.99) and low entropy (0.1) as this is the final verification and documentation step.
- Derivation: `EV = 0.99 * 82.0 + 0.5 * 1.5 - 0.3 * 0.1 - 0.5 = 81.18 + 0.75 - 0.03 - 0.5 = 81.40`.
