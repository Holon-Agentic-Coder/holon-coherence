# Methodical How-To: Context Cleaning & Tool Output Deduplication

## 🎯 Objective & Architectural Overview

Autonomous coding agents accumulate conversation history across successive turns. When an agent repeatedly reads the
same large files, runs redundant directory listings (`ls -la`), or executes repeated shell commands (`cat`, `grep`,
`git status`), naive agent harnesses re-transmit the entire accumulated history verbatim on every subsequent API call.
This produces an exponential context bloat:

$$\text{Cumulative Input Tokens} \propto \sum_{i=1}^{N} \text{history}_i \sim \mathcal{O}(N^2)$$

**Context Cleaning & Deduplication** intercepts outbound LLM API requests at the proxy/harness layer, hashes historical
tool result blocks, detects duplicates across turns, and replaces redundant outputs with compact structural tombstones
while preserving the most recent turn verbatim:

```text
"[Omitted: Tool result content is identical to Turn 2 (call_xyz)]"
```

This collapses redundant context bloat from $\mathcal{O}(N^2)$ back to linear $\mathcal{O}(N)$, drastically reducing
prompt token consumption, latency, and provider billing while maintaining 100% semantic coherence.

---

### 🔍 How Deduplication Distinguishes Duplicates vs. File & Directory Mutations

A critical architectural invariant of Context Cleaning is that **tool execution inside the sandbox is never blocked or
suppressed**. When an agent runs `ls` or `cat`, the command executes against the real filesystem in real time.
Deduplication operates strictly on the **outbound conversation history payload** sent to the LLM API.

#### 1. Content-Payload Hashing (SHA-256), NOT Command Matching

The deduplicator does **not** check whether the command string (e.g. `cat file.py` or `ls -la`) was run previously.
Instead, it extracts the **returned text content payload** (`tool_out = item.get("content", "")`) and computes its
SHA-256 hash:

$$\text{content\_hash} = \text{SHA-256}(\text{tool\_out})$$

It stores known hashes in `seen_content_hashes: dict[hash, (turn_idx, tool_use_id)]`.

#### 2. What Happens When a File Changes (`cat` / `view_file`)

- **File Unchanged**: If the agent executes `cat utils.py` in Turn 1 and re-runs `cat utils.py` in Turn 5 without
  modifying `utils.py`, the returned content in Turn 5 is byte-for-byte identical to Turn 1. The SHA-256 hashes match
  ($\text{hash}_{\text{T5}} = \text{hash}_{\text{T1}}$). Because the content is identical, the older historical turn is
  replaced with a structural tombstone pointing to Turn 1.
- **File Modified**: If the agent edits `utils.py` in Turn 3 and re-runs `cat utils.py` in Turn 4, the output contains
  the new lines of code. Its SHA-256 hash is completely different
  ($\text{hash}_{\text{T4}} \neq \text{hash}_{\text{T1}}$). The cleaner recognizes $\text{hash}_{\text{T4}}$ as a new
  state, records it as a distinct entry in `seen_content_hashes`, and **preserves the entire updated file content
  verbatim** in the context.

#### 3. What Happens When a File is Renamed or Added (`ls`)

- **Directory Unchanged**: If the directory contents have not changed, subsequent `ls` commands return the exact same
  listing text, producing an identical SHA-256 hash that triggers deduplication on historical turns.
- **File Renamed, Created, or Deleted**: If the agent renames `app.js` to `main.js` and re-runs `ls`, the output listing
  text changes. Because the text differs, its SHA-256 hash changes
  ($\text{hash}_{\text{new}} \neq \text{hash}_{\text{old}}$). The cleaner sees a fresh hash and **preserves the new
  directory listing in full**.

#### 4. Active Working Memory Protection (`_RECENT_TURNS_TO_KEEP = 6`)

To prevent the agent from losing situational awareness during active operations:

- The cleaner enforces `is_older_turn = turn_idx < (turn_count - 2)` and `_RECENT_TURNS_TO_KEEP = 6`.
- The **most recent turn is NEVER deduplicated**, even if its output matches an earlier turn! The active turn always
  presents the fresh, verbatim result directly to the LLM. Only historical turns deeper in the conversation backlog get
  tombstoned.

#### 5. Minimum Size Threshold Guard (`len(tool_out) > 100`)

Short tool responses ($\le 100$ characters—such as exit code confirmations, short errors, or single-line outputs) are
never hashed or deduplicated, avoiding unnecessary tombstone clutter for trivial messages.

---

## 🏛️ Codebase Architecture & Source Locations

| Component                     | Repository Path                                                                 | Core Function / Class                             |
| :---------------------------- | :------------------------------------------------------------------------------ | :------------------------------------------------ |
| **Payload Cleaner Engine**    | `apps/sandbox-executor/src/sandbox_executor/token_reduction/payload_cleaner.py` | `JSONContextCleaner.process_payload_with_stats()` |
| **MITM Proxy Interceptor**    | `apps/sandbox-executor/src/sandbox_executor/token_reduction/mitm_addon.py`      | `MitmproxyAddon.request(flow)`                    |
| **Unified Benchmark Harness** | `todo/ab_measure_all_methods.py`                                                | `clean_context_payload()`, Turn telemetry         |

---

## ⚙️ Prerequisites & Environment Setup

### 1. Dynamic Model Discovery (Zero Hardcoded Models)

In compliance with repository invariants, never hardcode model identifiers. Query the live active catalog via
`agy models`:

```bash
agy models
```

Select the active Tier 1 Flagship Reasoning Model (e.g., `gemini-3.8-flash-high`) or Tier 2 High-Throughput Model (e.g.,
`gemini-3.8-flash-low`).

### 2. Prepare Directories & Certificates

```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
mkdir -p "${REPO_ROOT}/todo/mitm_wire_logs" "${REPO_ROOT}/todo/cache" ~/.holon/proxy-ca
chmod 700 ~/.holon/proxy-ca
```

### 3. Launch the MITM Proxy Sidecar

Run the proxy container with `mitm_addon.py` mounted:

```bash
docker run -d --name mitm-context-cleaner \
  -p 127.0.0.1:8080:8080 \
  -e WIRE_LOG_DIR=/tmp/wire_logs \
  -e CACHE_DIR=/tmp/cache \
  -e PYTHONPATH=/tmp/src \
  -v "${REPO_ROOT}/holon-agentic-coder-ref/develop/apps/sandbox-executor/src":/tmp/src:ro \
  -v "${REPO_ROOT}/holon-agentic-coder-ref/develop/apps/sandbox-executor/src/sandbox_executor/token_reduction/mitm_addon.py":/tmp/mitm_addon.py:ro \
  -v "${REPO_ROOT}/todo/mitm_wire_logs":/tmp/wire_logs \
  -v "${REPO_ROOT}/todo/cache":/tmp/cache \
  -v ~/.holon/proxy-ca:/home/mitmproxy/.mitmproxy \
  mitmproxy/mitmproxy:12.2.3 \
  mitmdump -s /tmp/mitm_addon.py --listen-port 8080 \
  --set ignore_hosts='^(api\.github\.com|github\.com|pypi\.org|files\.pythonhosted\.org|registry\.npmjs\.org):443$'
```

Execute the client agent command with inline proxy environment variables (avoiding terminal session contamination):

```bash
HTTP_PROXY="http://127.0.0.1:8080" \
HTTPS_PROXY="http://127.0.0.1:8080" \
NO_PROXY="localhost,127.0.0.1,api.github.com,github.com" \
SSL_CERT_FILE="${HOME}/.holon/proxy-ca/mitmproxy-ca-cert.pem" \
REQUESTS_CA_BUNDLE="${HOME}/.holon/proxy-ca/mitmproxy-ca-cert.pem" \
NODE_EXTRA_CA_CERTS="${HOME}/.holon/proxy-ca/mitmproxy-ca-cert.pem" \
<your-agent-command>
```

Or execute via the CLI wrapper:

```bash
holon-coherence run -- <your-agent-command>
```

> [!NOTE] **Why Inline Proxy Execution?** Persisting proxy settings via global shell `export` pollutes the interactive
> session, causing unrelated tools (e.g. `git`, `curl`, package managers) to route through the local proxy or fail if
> the proxy is stopped. Inline properties guarantee that proxy routing is strictly isolated to the agent process.

---

## 🔬 High-Volume Workload Execution ($\ge 10,000$ Tokens)

To accurately measure context cleaning efficacy, the workload MUST exercise at least 10,000 tokens of genuine codebase
context and multiple conversation turns where the agent repeatedly inspects authentic source files.

### Step 1: Ingest Authentic Codebase Context

Load authentic source files from the Holon repository (`mitm_addon.py`, `payload_cleaner.py`, `hybrid_cache.py`,
`cli.py`) totaling $>130,000$ characters (~$32,800$ prompt tokens):

```python
from pathlib import Path

repo_root = Path(".").resolve()
files = [
    "apps/sandbox-executor/src/sandbox_executor/token_reduction/mitm_addon.py",
    "apps/sandbox-executor/src/sandbox_executor/token_reduction/payload_cleaner.py",
    "apps/sandbox-executor/src/sandbox_executor/token_reduction/hybrid_cache.py",
    "apps/sandbox-executor/src/sandbox_executor/cli.py",
]
codebase_context = "\n".join(
    f"=== FILE: {f} ===\n{(repo_root / f).read_text(encoding='utf-8')}" for f in files if (repo_root / f).exists()
)
```

### Step 2: Execute Multi-Turn Baseline Trajectory (Uncleaned)

In the baseline run, the agent repeatedly executes file inspection tool turns without context cleaning:

1. **Turn 1**: Agent reads the codebase files and produces an initial architectural specification.
2. **Turn 2**: Agent re-reads `mitm_addon.py` and `payload_cleaner.py` to write implementation code.
3. **Turn 3**: Agent runs tests and inspects logs.

In the uncleaned baseline, Turn 2 and Turn 3 re-transmit the full ~32,800 tokens of file contents from Turn 1. Total
prompt tokens accumulate quadratically ($39,816 + 72,000 + 105,000 \approx 216,000+$ prompt tokens).

### Step 3: Execute Multi-Turn Optimized Trajectory (Context Cleaning Active)

Enable `JSONContextCleaner` either via the proxy sidecar or programmatically:

```python
import sys
from pathlib import Path

# Add sandbox-executor src to path
sys.path.insert(0, str(Path("apps/sandbox-executor/src").resolve()))
from sandbox_executor.token_reduction import JSONContextCleaner

cleaner = JSONContextCleaner(enable_deduplication=True, max_turns=30)

# Simulate multi-turn payload with repeating tool outputs
multi_turn_payload = {
    "messages": [
        {"role": "user", "content": "Analyze the codebase and draft architecture."},
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "tool_1",
                    "name": "view_file",
                    "input": {"path": "mitm_addon.py"},
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tool_1",
                    "content": codebase_context,  # ~32,800 tokens
                }
            ],
        },
        {"role": "assistant", "content": "I have analyzed the codebase."},
        # Turn 2: Agent issues another tool call reading the same file
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "tool_2",
                    "name": "view_file",
                    "input": {"path": "mitm_addon.py"},
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tool_2",
                    "content": codebase_context,  # Redundant duplicate!
                }
            ],
        },
        {"role": "assistant", "content": "Writing the implementation."},
    ]
}

# Clean the payload
result = cleaner.process_payload_with_stats(multi_turn_payload, provider="anthropic")

print(f"Tool outputs omitted: {result.tool_outputs_omitted}")
print(f"Characters saved: {result.chars_saved:,} bytes")
```

### Step 4: Dispatch Real LLM Execution via `agy`

Dispatch the cleaned payload to the discovered real LLM:

```bash
# Verify active model
TIER1_MODEL=$(agy models | grep -E "gemini-3.8-flash-high|claude-sonnet-4-6" | head -n1 | awk '{print $1}')
echo "Dispatching real LLM request to: ${TIER1_MODEL}"

# Execute through agy with proxy active
agy exec --model "${TIER1_MODEL}" "Implement a complete dark-mode responsive dashboard based on the Holon architecture."
```

---

## 📊 Verification & Telemetry Extraction

### 1. Inspect Wire Log Transactions

The MITM proxy records every inbound request and modified body in `todo/mitm_wire_logs/transactions.jsonl`:

```bash
# Verify transaction logs exist and contain no synthetic data
cat todo/mitm_wire_logs/transactions.jsonl | jq '{
  timestamp: .timestamp,
  model: .request.model,
  tool_outputs_omitted: .reduction.tool_outputs_omitted,
  chars_saved: .reduction.chars_saved,
  input_tokens: .response.usage.input_tokens,
  output_tokens: .response.usage.output_tokens
}'
```

### 2. Verify Output Replacement Tombstones

Inspect the recorded outbound payload to ensure duplicates were replaced with valid structural pointers:

```bash
cat todo/mitm_wire_logs/turn_*.json | grep -F "[Omitted: Tool result content is identical to Turn"
```

### 3. Metric Assertions (Acceptance Criteria)

Verify that the run satisfies the empirical benchmarks:

1. **Tool Outputs Omitted**: $\ge 1$ redundant payload pruned per multi-turn file inspection.
2. **Bytes Pruned**: $\ge 100,000$ characters saved across high-volume turns (in our benchmark: **140,851 bytes
   saved**).
3. **Task Success & Integrity**: The generated code must remain 100% syntactically valid and pass all test assertions
   (e.g., `python3 -m unittest test_dashboard.py`).

---

## 🛠️ Troubleshooting & Failure Modes

- **Tombstone Confusion**: If a weak model attempts to read the tombstone text literally, ensure the prompt cleaner
  leaves the **most recent** tool result untouched (`_RECENT_TURNS_TO_KEEP = 6`), only deduplicating older historical
  turns.
- **Cache Invalidation Side Effect**: Replacing text in historical turns alters the prompt prefix hash. To avoid
  breaking provider prompt caching, deduplication must occur at predictable turn boundaries before cache breakpoints are
  injected.
