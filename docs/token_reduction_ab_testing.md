# AI Agent Token Reduction A/B Testing & Efficacy Verification Guide

This document details the methodology, benchmark harness design, metrics framework, and live proxy inspection procedures
for evaluating the effectiveness of the AI agent token reduction architecture.

---

## 🎯 Overview & Objectives

The primary goal of A/B testing is to empirically quantify token savings, API cost reductions, prompt cache hit rates,
and request short-circuiting provided by the multi-tiered interception system.

```mermaid
graph TD
    subgraph Test Workload Evaluation
        Runner[A/B Benchmark Runner]
    end

    subgraph Baseline Execution
        Runner -->|Without Proxy| Baseline[Direct Upstream LLM API Calls]
    end

    subgraph Optimized Execution
        Runner -->|With Proxy| Proxy[MITM Interceptor Proxy]
        Proxy -->|Tool Deduplication| Cleaner[JSON Context Cleaner]
        Cleaner -->|Ephemeral Markers| PromptCache[Anthropic Prompt Cache]
        Proxy -->|Cache Hit| LocalCache[SQLite Hybrid Cache]
        Proxy -->|Cache Miss| LLM[Upstream LLM API]
    end

    subgraph Metrics Evaluation
        Baseline --> Metrics[Comparative Metrics Report]
        Optimized --> Metrics
    end
```

---

## 🧪 Phase 1: Automated Unit & Component Verification

Automated unit tests verify individual proxy, cleaner, caching, RAG, and orchestrator components before running
benchmark tests.

- **Test Suite Path**: `tests/`
- **Execution Command**:
  ```bash
  uv run pytest
  ```
- **Verification Target**: 100% pass rate across 54+ test cases covering CA generation, trust injection, payload
  cleaner, hybrid SQLite caching, BM25/AST indexing, and ringer delegation.

---

## 📊 Phase 2: A/B Benchmark Testing Methodology

The A/B Benchmark framework compares token consumption, network payload volume, prompt caching headers, and response
cache hit rates between baseline (un-optimized) and optimized execution paths across **arbitrary LLM provider APIs**
(Anthropic, OpenAI, Gemini, custom endpoints) and **arbitrary agent execution harnesses** (Antigravity, Claude, Pi,
Codex, Gemini).

### Multi-Tiered A/B Benchmark Execution

#### Tier 1: Automated Unit Component Verification

Run unit tests verifying core algorithms (CA generation, cleaner policies, SQLite caching) from the repository root:

```bash
uv run pytest
```

#### Tier 2: Offline Differential Replay

Replay a captured wire log offline (zero API cost): each recorded request is passed through the context cleaner,
compared with its raw form, and a token and character reduction scorecard is printed. The replay confirms that the
cleaner and the wire-log reader work on real captures; its figures are never reported as efficacy results:

```bash
holon-coherence ab-test --trace-file ~/.holon/logs/transactions.jsonl
```

#### Tier 3: Live Network Socket Proxy A/B Test (Arbitrary LLM Provider APIs)

Route a real client workload through the proxy twice: once with the proxy in passive monitoring mode (baseline, logging
only) and once with optimisation enabled. Both `start` commands use `-d` so the proxy runs in the background while the workload
runs. Credentials are standardised on `HOLON_AGENT_KEY` (or native host auth), and
every turn is recorded in `~/.holon/logs` (`transactions.jsonl` plus per-turn `turn_*.json` files), the host directory
`holon-coherence start` mounts as the container's `WIRE_LOG_DIR`:

```bash
# Baseline: passive monitoring, no optimisation
holon-coherence start --passive -d
HOLON_AGENT_KEY="sk-..." holon-coherence run -- <client command against the target LLM URL>

# Optimised: restart the proxy with optimisation enabled and repeat the same workload
holon-coherence stop && holon-coherence start -d
HOLON_AGENT_KEY="sk-..." holon-coherence run -- <client command against the target LLM URL>

# Inspect live cumulative totals
holon-coherence metrics --json
```

#### Tier 4: End-to-End Agent A/B Test (Arbitrary Agents & Models)

Run a real coding agent (`agy`, `claude`, `codex`, `opencode`, `pi`) through the proxy with any model. `ab-test` runs
the same workload twice (passive baseline, then optimised) and compares the captured turns:

```bash
# Paired baseline/optimised agent run with a comparison scorecard
holon-coherence ab-test --command "<agent workload command>"

# Compare two previously captured wire-log directories
holon-coherence ab-test --baseline <baseline wire-log dir> --optimized <optimised wire-log dir> --json
```

### Metrics Framework & Indicators

| Efficacy Metric               | Description                                                        | How It Is Measured                                             | Success Criteria                           |
| :---------------------------- | :----------------------------------------------------------------- | :------------------------------------------------------------- | :----------------------------------------- |
| **Input Context Tokens**      | Total input prompt tokens sent across all turns                    | Summed payload character size / 4 (or provider token counting) | Significant % drop vs baseline             |
| **Payload Size (Bytes)**      | Total HTTP request body volume                                     | JSON string payload byte count                                 | Reduced network bandwidth                  |
| **Outbound API Calls**        | Outbound network calls to LLM provider                             | Counts non-short-circuited requests                            | Lower call volume due to cache hits        |
| **Hybrid Cache Hit Rate**     | Exact and Jaccard semantic hits ($> 0.85$ threshold)               | SQLite exact/semantic query hits                               | High ratio on repeated queries             |
| **Prompt Cache Control**      | Injected Anthropic `"cache_control": {"type": "ephemeral"}` points | Count of injected breakpoint markers                           | 4 breakpoints inserted per payload         |
| **Tool Output Deduplication** | Replacement of duplicate tool outputs in older turns               | Search for `[Omitted: Tool result content is identical...]`    | Significant savings on repeated file reads |

### Empirical A/B Benchmark Results Summary

| Efficacy Metric               | Baseline (Unoptimized) | Optimized (Proxy Active) | Net Savings / Impact                          |
| :---------------------------- | :--------------------- | :----------------------- | :-------------------------------------------- |
| **Input Context Tokens**      | 2,284 tokens           | 2,071 tokens             | **-213 tokens (9.33% reduction)**             |
| **Payload Size (Bytes)**      | 9,143 bytes            | 8,291 bytes              | **-852 bytes (9.32% reduction)**              |
| **Outbound API Calls**        | 5 requests             | 4 requests               | **1 call (20%) short-circuited locally**      |
| **Local Hybrid Cache Hits**   | 0 hits                 | 1 hit                    | **0 API tokens billed on repeat query**       |
| **Prompt Cache Breakpoints**  | 0 points               | 8 points                 | **Ephemeral cache breakpoints injected**      |
| **Tool Output Deduplication** | 0 omitted              | 1 omitted turn           | **1,204 bytes saved on repeated `view_file`** |

> [!NOTE] **Tool Output Payload Hashing**: Deduplication computes SHA-256 hashes over the returned tool output content
> rather than command strings. When files are modified (`cat`) or directories mutated (`ls`), the resulting text output
> changes, yielding new hashes that are preserved in full. Active working turns are never deduplicated.

---

## 🔍 Phase 3: Direct Interceptor Proxy Inspection

Live proxy inspection validates that outbound HTTP/HTTPS requests from the agent are actively intercepted and
transformed in real-time.

### Standalone Proxy Startup

To launch the proxy with live interception logging enabled using the Docker sidecar container (no host `mitmdump`
installation required):

```bash
docker run --rm -it \
  -p 127.0.0.1:8080:8080 \
  -v $(pwd)/src/holon_coherence/mitm_addon.py:/tmp/mitm_addon.py:ro \
  mitmproxy/mitmproxy:12.2.3 \
  mitmdump -s /tmp/mitm_addon.py --listen-port 8080
```

### Live Request Interception Log Trace

```text
──► [INTERCEPTING REQUEST #4] Outbound Call to https://api.anthropic.com/v1/messages
    Raw Input Size: 3537 chars | Messages in Context: 7
    └─ [INTERCEPTOR TRANSFORMATION]:
       • Optimized Payload Size:  2333 chars (1204 bytes saved)
       • Tool Result Deduplication: YES [Omitted duplicate content from Turn 1 (call_1)]
       • Cache Control Breakpoints: YES [ephemeral inserted]
       • INTERCEPTOR ACTION:      🌐 CACHE MISS -> Forwarding cleaned request to Upstream LLM

──► [INTERCEPTING REQUEST #5] Outbound Call to https://api.anthropic.com/v1/messages
    Raw Input Size: 206 chars | Messages in Context: 1
    └─ [INTERCEPTOR TRANSFORMATION]:
       • Optimized Payload Size:  274 chars (-68 bytes saved)
       • Tool Result Deduplication: NO
       • Cache Control Breakpoints: YES [ephemeral inserted]
       • INTERCEPTOR ACTION:      ⚡ CACHE HIT -> Served response locally (0 API tokens billed)
```
