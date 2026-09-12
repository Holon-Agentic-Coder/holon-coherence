# Methodical How-To: Hybrid & Semantic Local Cache Layer

## 🎯 Objective & Architectural Overview

Autonomous multi-agent systems and iterative development loops frequently re-execute identical or semantically
equivalent prompt sequences—such as re-evaluating unchanged architectural components, re-running validation checks, or
spawning parallel subagents with identical instruction templates. Without local caching, every repeated invocation
incurs full provider token costs and multiple seconds of network round-trip latency.

**Hybrid & Semantic Local Cache Layer** introduces an SQLite-backed exact and semantic caching store directly into the
proxy and execution harness. When an outgoing request matches an existing entry:

1. **Exact Match**: Stable SHA-256 hash match on normalized payload prefix.
2. **Semantic Match**: Jaccard word-level similarity index ($\ge 0.85$) against recent candidate turns.
3. **Operational Short-Circuiting**: The proxy intercepts the request before it reaches the external provider network,
   returning the cached completion immediately:
   - **Prompt Tokens Billed:** 0 tokens
   - **Output Tokens Billed:** 0 tokens
   - **Network Latency:** < 5 milliseconds

---

## 🏛️ Codebase Architecture & Source Locations

| Component                  | Repository Path                                                              | Core Function / Class                              |
| :------------------------- | :--------------------------------------------------------------------------- | :------------------------------------------------- |
| **Hybrid Cache Store**     | `apps/sandbox-executor/src/sandbox_executor/token_reduction/hybrid_cache.py` | `HybridCacheStore.get()`, `HybridCacheStore.put()` |
| **MITM Interception Hook** | `apps/sandbox-executor/src/sandbox_executor/token_reduction/mitm_addon.py`   | `MitmproxyAddon.request()` short-circuiting        |
| **Database Storage**       | `todo/cache/llm_cache.db`                                                    | Table `prompt_cache` (WAL mode enabled)            |

---

## ⚙️ Prerequisites & Environment Setup

### 1. Dynamic Model Discovery (Zero Hardcoded Models)

Discover active models dynamically via `agy models`:

```bash
agy models
```

Identify the target model (e.g., `gemini-3.8-flash-high` for Architect turns or `gemini-3.8-flash-low` for Executor
turns).

### 2. Configure Local Cache Directory

Ensure the SQLite cache directory exists:

```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
mkdir -p "${REPO_ROOT}/todo/cache"
```

### 3. Normalization Invariants

Before computing hashes or similarity scores, `HybridCacheStore.normalize_payload()` strips transient non-deterministic
artifacts:

- ISO-8601 timestamps: `2026-09-12T09:44:46Z` $\to$ `<TIMESTAMP>`
- UUID strings: `af81bebc-5e6e-481b-a33d-abd8588a616a` $\to$ `<UUID>`
- Transient run identifiers: `task-1787928877` $\to$ `task-<ID>`

This ensures that identical prompt structures generated across different execution runs produce identical cache keys.

---

## 🔬 High-Volume Workload Execution ($\ge 10,000$ Tokens)

To demonstrate cache performance on substantial real-world workloads, execute a two-phase trajectory where Turn 1
invokes the real LLM to generate a complex architectural document ($\ge 10,000$ tokens), and Turn 2 issues an identical
or semantically equivalent request.

### Step 1: Initialize Hybrid Cache Store

```python
import sys
from pathlib import Path

repo_root = Path(".").resolve()
sys.path.insert(0, str(repo_root / "apps/sandbox-executor/src"))
from sandbox_executor.token_reduction import HybridCacheStore

cache_store = HybridCacheStore(
    cache_dir=str(repo_root / "todo/cache"),
    similarity_threshold=0.85,
    candidate_limit=100,
)
```

### Step 2: Phase 1 — Cold Cache Miss (Real LLM Execution)

In the cold run, the request is not found in `llm_cache.db`. The request proceeds upstream to the real provider via
`agy`:

```python
import subprocess

# Model discovered dynamically via 'agy models'
selected_model = "gemini-3.8-flash-high"

high_volume_prompt = """
Conduct an exhaustive architectural review of the Holon token reduction proxy.
Detail the end-to-end flow from client socket interception to TLS decryption,
context cleaning, hybrid caching, and provider streaming reassembly.
Output must include full production Python implementations and ASCII flow diagrams.
"""

# Execute live via agy
proc = subprocess.run(
    ["agy", "exec", "--model", selected_model, high_volume_prompt],
    capture_output=True,
    text=True,
    check=True,
)
real_llm_response = proc.stdout

# Store verified completion into local cache
request_payload = {
    "model": selected_model,
    "messages": [{"role": "user", "content": high_volume_prompt}],
}
cache_store.put(request_payload, real_llm_response, provider="gemini")
print("Phase 1 Complete: Response cached in llm_cache.db")
```

### Step 3: Phase 2 — Warm Cache Hit (Operational Short-Circuit)

Execute the second turn with the same request payload (or with minor whitespace/timestamp variations). The cache store
detects the match and short-circuits the call:

```python
# Check cache before making external API call
cached_response = cache_store.get(request_payload, provider="gemini")

if cached_response is not None:
    print("✅ CACHE HIT! Short-circuiting request locally.")
    print(f"Cached output size: {len(cached_response):,} characters")
    # Tokens billed upstream: 0 Input, 0 Output
else:
    print("❌ Cache Miss")
```

---

## 📊 Verification & Telemetry Extraction

### 1. Query the SQLite Cache Database

Inspect the SQLite database directly to verify stored records, hit counters, and timestamps:

```bash
sqlite3 todo/cache/llm_cache.db << 'EOF'
.mode column
.headers on
SELECT
    substr(key, 1, 16) AS key_prefix,
    provider,
    hit_count,
    datetime(created_at, 'unixepoch') AS created_time,
    length(response_json) AS response_bytes
FROM prompt_cache;
EOF
```

Expected Output:

```text
key_prefix        provider    hit_count    created_time           response_bytes
----------------  ----------  -----------  ---------------------  --------------
e8a4d70b31f298c1  gemini      1            2026-09-12 09:44:46    96240
```

### 2. Verify Proxy Wire Log Telemetry

If running via the MITM proxy sidecar, verify the wire transaction record in `todo/mitm_wire_logs/transactions.jsonl`:

```bash
cat todo/mitm_wire_logs/transactions.jsonl | jq 'select(.cache_hit == true) | {
  timestamp: .timestamp,
  model: .request.model,
  cache_hit: .cache_hit,
  input_tokens: .response.usage.input_tokens,
  output_tokens: .response.usage.output_tokens
}'
```

The output confirms:

```json
{
  "cache_hit": true,
  "input_tokens": 0,
  "output_tokens": 0
}
```

### 3. Acceptance Criteria & Empirical Benchmarks

1. **Zero Provider Cost on Hit**: Warm requests must record 0 prompt tokens and 0 completion tokens billed.
2. **Hit Rate Target**: In repeated subagent workflows or idempotent build checks, achieve $\ge 50\%$ cache hit rates.
3. **Response Quality Invariant**: The returned completion must be identical to the authentic provider output and pass
   all downstream functional verifications.

---

## 🛠️ Troubleshooting & Failure Modes

- **Streaming SSE Short-Circuiting**: If an agent harness enforces Server-Sent Events (`stream: true`), returning a
  static buffered JSON response will cause the client parser to hang or drop the connection. For streaming clients, the
  proxy must either simulate SSE data chunks (`data: {...}\n\n`) or configure the harness in non-streaming mode during
  cache evaluation.
- **Cache Drift**: If prompt instructions are modified during active debugging, stale cache entries can return outdated
  results. Flush the local cache between clean benchmark runs via:
  ```bash
  rm -f todo/cache/llm_cache.db*
  ```
- **Semantic False Positives**: Setting `similarity_threshold` too low ($<0.75$) may cause prompts with subtle
  differences (e.g., different file names) to incorrectly return cached code for the wrong file. Maintain threshold
  $\ge 0.85$.
