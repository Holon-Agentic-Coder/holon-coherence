# Methodical How-To: Provider Prompt Cache Optimization

## 🎯 Objective & Architectural Overview

Modern frontier LLM providers (Anthropic, Google Gemini, OpenAI) offer native upstream prompt caching. When an API
request reuses a large prefix (such as system guidelines, repository constraints, or large codebase context) identical
to a recent request, the provider bypasses full transformer re-computation:

- **Cache Read Discount**: Cached prompt tokens are billed at an **80% to 90% discount** (e.g., Anthropic charges
  **$0.30/MTok** for cache reads versus **$3.00/MTok** for uncached prompt tokens).
- **Latency Reduction**: Time-To-First-Token (TTFT) drops dramatically because the provider skips prefix attention
  computation.

However, upstream prompt caching fails completely if:

1. **Prompt Volume is Too Small**: Providers enforce a strict minimum activation threshold (typically **1,024 tokens**
   for Anthropic and **2,048 tokens** for other providers). Requests with fewer tokens produce 0 cache hits.
2. **Volatile Variables Break the Prefix**: Placing timestamps, dynamic task UUIDs, or changing iteration counters near
   the beginning of the prompt invalidates the provider's prefix tree from that token onward.

**Provider Prompt Cache Optimization** establishes strict prefix stability:

- Anchors large immutable blocks (system rules, tool schemas, codebase source dumps) at the absolute beginning of the
  payload.
- Automatically inserts provider-specific cache control breakpoints (e.g., `"cache_control": {"type": "ephemeral"}` for
  Anthropic Messages API) at the optimal 4-breakpoint boundary.
- Appends all volatile, turn-specific user prompts exclusively at the tail.

---

## 🏛️ Codebase Architecture & Source Locations

| Component                     | Repository Path                                                                 | Core Function / Class                                  |
| :---------------------------- | :------------------------------------------------------------------------------ | :----------------------------------------------------- |
| **Cache Control Injector**    | `apps/sandbox-executor/src/sandbox_executor/token_reduction/payload_cleaner.py` | `JSONContextCleaner._inject_anthropic_cache_control()` |
| **MITM Telemetry Normalizer** | `apps/sandbox-executor/src/sandbox_executor/token_reduction/mitm_addon.py`      | Normalization of `cache_read_input_tokens`             |
| **Unified Benchmark Harness** | `todo/ab_measure_all_methods.py`                                                | Multi-turn cache read measurement                      |

---

## 📐 Invariant: Provider Accounting Formula

In raw Anthropic and Gemini wire responses:

- `usage.input_tokens` denotes uncached base prompt tokens.
- `usage.cache_read_input_tokens` (or `cached_content_token_count`) denotes tokens served from cache at the 90%
  discount.

The total prompt context offered to the LLM is:

$$\text{Total Prompt Tokens} = \text{input\_tokens} + \text{cache\_read\_input\_tokens}$$

The Provider Prompt Cache Hit Rate is calculated as:

$$R_{\text{hit}} = \frac{\text{cache\_read\_input\_tokens}}{\text{input\_tokens} + \text{cache\_read\_input\_tokens}} \times 100\%$$

---

## ⚙️ Prerequisites & Environment Setup

### 1. Dynamic Model Discovery (Zero Hardcoded Models)

Verify active provider models via `agy models`:

```bash
agy models
```

Prompt caching is supported on frontier reasoning models (e.g., `gemini-3.8-flash-high`, `claude-sonnet-4-6`).

### 2. High-Volume Workload Requirement ($\ge 10,000$ Tokens)

To surpass the provider's activation threshold and measure authentic prompt caching, the prompt context MUST exceed
10,000 tokens. Load authentic codebase files from the Holon repository:

```python
from pathlib import Path

repo_root = Path(".").resolve()
files = [
    "apps/sandbox-executor/src/sandbox_executor/token_reduction/mitm_addon.py",
    "apps/sandbox-executor/src/sandbox_executor/token_reduction/payload_cleaner.py",
    "apps/sandbox-executor/src/sandbox_executor/token_reduction/hybrid_cache.py",
    "apps/sandbox-executor/src/sandbox_executor/cli.py",
]
large_context = "\n".join(
    f"=== FILE {f} ===\n{(repo_root / f).read_text(encoding='utf-8')}"
    for f in files
    if (repo_root / f).exists()
)
print(f"Context loaded: {len(large_context):,} characters (~{len(large_context)//4:,} tokens)")
```

---

## 🔬 Multi-Turn Workload Execution (Real LLMs)

### Step 1: Baseline Trajectory (Unoptimized Prefix Ordering)

In the unoptimized baseline, dynamic metadata is injected at the beginning of each turn:

```python
# Unoptimized: Dynamic timestamp prepended to system instructions
import datetime

unoptimized_payload = {
    "system": f"Current timestamp: {datetime.datetime.now().isoformat()}\nYou are an expert agent.",
    "messages": [
        {"role": "user", "content": f"{large_context}\n\nTask: Analyze code."}
    ],
}
```

Because the timestamp changes on every turn, the provider's prefix cache key changes completely on every call, yielding
**0% cache hits** and full pricing on all tokens.

### Step 2: Optimized Trajectory (Stable Prefix + Cache Breakpoints)

In the optimized trajectory, system rules and codebase context are permanently anchored at the prefix. Cache breakpoints
are injected via `JSONContextCleaner`:

```python
import sys
from pathlib import Path

repo_root = Path(".").resolve()
sys.path.insert(0, str(repo_root / "apps/sandbox-executor/src"))
from sandbox_executor.token_reduction import JSONContextCleaner

cleaner = JSONContextCleaner(enable_prompt_caching=True)

# Optimized payload: Static prefix with cache_control breakpoint
optimized_payload = {
    "system": [
        {
            "type": "text",
            "text": "You are the Holon Flagship Architect. Adhere to all repository constraints.",
            "cache_control": {"type": "ephemeral"},  # Breakpoint 1
        }
    ],
    "messages": [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": large_context,
                    "cache_control": {"type": "ephemeral"},  # Breakpoint 2
                },
                {
                    "type": "text",
                    "text": "Turn 1: Formulate the architectural RFC.",
                },
            ],
        }
    ],
}

cleaned = cleaner.process_payload_with_stats(
    optimized_payload, provider="anthropic"
)
print(f"Cache control breakpoints injected: {cleaned.cache_control_injected}")
```

### Step 3: Execute Across Successive Live Turns via `agy`

Dispatch multi-turn requests to the real LLM:

- **Turn 1 (Cache Creation)**: Provider processes the full prefix and writes it to the prompt cache.
- **Turn 2 (Cache Read)**: Agent submits follow-up questions referencing the same codebase context. Provider serves the
  prefix directly from cache.

Execute live:

```bash
TIER1_MODEL=$(agy models | grep -E "gemini-3.8-flash-high|claude-sonnet-4-6" | head -n1 | awk '{print $1}')
echo "Using real model: ${TIER1_MODEL}"

# Turn 1: Initial creation
agy exec --model "${TIER1_MODEL}" "Analyze the token reduction codebase and draft the design."

# Turn 2: Follow-up referencing the same context
agy exec --model "${TIER1_MODEL}" "Based on the previous codebase analysis, generate the performance profile."
```

---

## 📊 Verification & Telemetry Extraction

### 1. Extract Provider Wire Telemetry

Inspect `todo/mitm_wire_logs/transactions.jsonl` (or the transcript logs in
`~/.gemini/antigravity-cli/brain/<conv_id>/.system_generated/logs/transcript.jsonl`):

```bash
cat todo/mitm_wire_logs/transactions.jsonl | jq '{
  turn: .turn_id,
  model: .request.model,
  input_tokens: .response.usage.input_tokens,
  cache_read_tokens: .response.usage.cache_read_input_tokens,
  cache_creation_tokens: .response.usage.cache_creation_input_tokens,
  output_tokens: .response.usage.output_tokens
}'
```

### 2. Live Verification Scorecard from Empirical Run

From our high-volume multi-turn benchmark run (`ab_measure_all_methods.py`):

|   Turn #   | Model                   | Status  | Input Tokens | Cache Read Tokens | Output Tokens | Duration |
| :--------: | :---------------------- | :-----: | :----------: | :---------------: | :-----------: | :------: |
| **Turn 1** | `gemini-3.8-flash-high` | SUCCESS |    39,816    |       8,174       |    33,764     | 221.06s  |
| **Turn 2** | `gemini-3.8-flash-low`  | SUCCESS |    26,012    |       8,167       |    12,066     |  60.60s  |
| **Turn 3** | `gemini-3.8-flash-low`  | SUCCESS |    16,257    |         0         |     1,010     |  32.22s  |
| **Turn 4** | `gemini-3.8-flash-high` | SUCCESS |    99,098    |    **257,337**    |    32,342     | 214.23s  |
| **Turn 5** | `gemini-3.8-flash-low`  | SUCCESS |    49,156    |         0         |     4,900     |  21.91s  |

**Hit Rate Calculation for Turn 4**:

$$R_{\text{hit}} = \frac{257,337}{99,098 + 257,337} \times 100\% = 72.2\%$$

Across the entire 5-turn session, **273,678 tokens** were served at the 90% discounted cache rate.

### 3. Acceptance Criteria & Guardrails

1. **Cache Hit Rate**: Achieves $\ge 50\%$ prompt cache hit rate across multi-turn trajectories with large context.
2. **Financial Savings**: Demonstrates $>50\%$ monetary reduction on cached prompt tokens.
3. **Correctness**: The LLM output quality must not degrade; full contextual reasoning is preserved across all turns.

---

## 🛠️ Troubleshooting & Failure Modes

- **Sub-Threshold Payloads**: If prompt size is $<1,024$ tokens, `cache_read_input_tokens` will report 0. Always verify
  that context size exceeds provider minimums.
- **Breakpoint Limit Exceeded**: Anthropic enforces a maximum of 4 `"cache_control"` blocks per request. If more than 4
  are provided, the API returns HTTP 400. `JSONContextCleaner` automatically bounds injections to $\le 4$.
- **Cache Eviction TTL**: Upstream provider prompt caches typically persist for 5 minutes of inactivity. For continuous
  benchmarking, ensure turns execute within the active TTL window.
