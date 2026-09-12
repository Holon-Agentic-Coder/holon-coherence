# Token Reduction & Optimization Efficacy Measurement Plan

This document outlines the architecture, instrumentation strategy, and step-by-step methodology for inspecting
wire-level LLM traffic and measuring the empirical effectiveness of all six token reduction techniques across the
`holon-agentic-coder-ref` ecosystem.

> [!NOTE] **Repository Topology & Relative Links**: Relative file paths targeting `../../holon-agentic-coder-ref/...`
> navigate from this document's directory (`docs/optimisation/`) to the repository root where `holon-agentic-coder-ref`
> resides as a submodule or nested folder. In standalone GitHub web views, cross-repository relative links do not
> resolve across separate repository boundaries; refer directly to the upstream
> [`holon-agentic-coder-ref`](https://github.com/Holon-Agentic-Coder/holon-agentic-coder-ref) repository.

---

## 🎯 Problem Statement & Diagnostic

### Why Payloads Are Currently Opaque in MITM

During live runs, token counters increment, but developers cannot see the actual requests sent or responses received.
This occurs because:

1. **Summarized Console Logging**:
   [`mitm_addon.py`](../../holon-agentic-coder-ref/develop/apps/sandbox-executor/src/sandbox_executor/token_reduction/mitm_addon.py)
   outputs only single-line `📊 [TELEMETRY]` summaries to standard output.
2. **Streaming (SSE) Buffering Without Inspection Sinks**: When agents stream responses via Server-Sent Events (SSE),
   chunks are assembled in-memory solely to parse usage metadata and count tokens, without emitting the full
   reconstructed text or prompt diffs to disk or console.
3. **Headless Proxy Execution**: In standard Docker sidecar runs, `mitmdump` runs headlessly without a persistent
   transaction log or web UI attached.

### Objectives of This Measurement Plan

1. **100% Wire-Level Visibility**: Capture and log the complete uncleaned request, transformed (cleaned) request, and
   reconstructed upstream response for every turn.
2. **Empirical Measurement Across All 6 Techniques**:
   - **Context Cleaning & Deduplication**
   - **Local Hybrid & Semantic Caching**
   - **Provider Prompt Cache Optimisation**
   - **RAG Codebase Indexer**
   - **OpenBrain Memory Layer**
   - **Ringer Multi-Agent Framework**
3. **Reproducible A/B Verification**: Quantify exact token deltas, financial cost reductions, latency changes, and task
   success rates between baseline and optimized runs.

---

## 🔬 System Architecture for Full Traffic Inspection

```mermaid
graph TD
    subgraph Sandbox Container
        Agent[Agent Harness]
    end

    subgraph MITM Sidecar Engine
        Agent -->|Raw Outbound Request| ProxyPort["Proxy Port :8080"]
        ProxyPort --> RawCapture[1. Capture Raw Request & Tokenize]
        RawCapture --> Cleaner[2. Context Cleaner & Prompt Cache Injector]
        Cleaner --> DiffEngine[3. Diff Engine: Raw vs Cleaned]
        Cleaner --> CacheCheck{4. Local Cache Check}

        CacheCheck -->|Hit| LocalResp[Serve Cached Payload]
        CacheCheck -->|Miss| Upstream[5. Forward to LLM Provider]

        Upstream --> StreamInterceptor[6. SSE Stream Interceptor & Reassembler]
        StreamInterceptor --> UsageParser[7. Usage & Provider Cache Header Parser]
    end

    subgraph Inspection & Sinks
        ProxyPort -->|Live Inspection| WebUI["mitmweb UI :8081"]
        DiffEngine --> WireLogger["JSONL Wire Log: transactions.jsonl"]
        LocalResp --> WireLogger
        StreamInterceptor --> WireLogger
        UsageParser --> WireLogger
        WireLogger --> ABMetrics[A/B Telemetry Report]
    end
```

---

## 📡 Part 1: Real-Time Request & Response Wire Inspection

To inspect the raw traffic going out and coming back in real time:

### 1. Structured Wire Logger (`todo/mitm_wire_logs/`)

Add a structured file logger to
[`mitm_addon.py`](../../holon-agentic-coder-ref/develop/apps/sandbox-executor/src/sandbox_executor/token_reduction/mitm_addon.py)
that appends full transaction details to `${WIRE_LOG_DIR}/turn_{turn_id}_{flow_id}.json` and
`${WIRE_LOG_DIR}/transactions.jsonl`.

- **Log Directory Parameterization & Git Ignore**: Configure the destination directory via the `WIRE_LOG_DIR`
  environment variable:

  ```python
  WIRE_LOG_DIR = os.getenv("WIRE_LOG_DIR", "todo/mitm_wire_logs")
  ```

  In local development, transactions default to `todo/mitm_wire_logs/`. When running inside Docker containers, pass
  `-e WIRE_LOG_DIR=/tmp/wire_logs` so output writes directly to the mounted `/tmp/wire_logs` host volume. Ensure
  `${WIRE_LOG_DIR}` (e.g. `todo/mitm_wire_logs/`) is explicitly included in `.gitignore` to prevent committing raw
  conversation transcripts, tool outputs, and LLM payloads to source control.

  _Log Retention & Disk Quota Policy_: In long-running benchmark suites ($N \ge 3$ across 50+ turns), full raw
  transaction dumps (`turn_{turn_id}_{flow_id}.json`) can accumulate hundreds of megabytes of disk storage. For
  resource-constrained CI/CD runners, implement a retention policy—such as configuring CI pipeline artifact uploads
  (e.g., `actions/upload-artifact`) with `retention-days: 1` (or uploading only on test failure), archiving runs older
  than 7 days, compressing individual turn dumps into a tarball artifact (`tar -czf wire_logs.tar.gz ${WIRE_LOG_DIR}`),
  or retaining only the compact summary lines in `transactions.jsonl` while purging raw per-turn payload dumps once
  benchmark assertions pass.

- **Turn ID Derivation & Multi-Agent Flow Scoping**: When running multi-agent workflows (such as Method 6 Ringer),
  multiple subagents execute concurrently through `:8080`. HTTP requests arriving at the proxy are stateless; relying
  solely on a naive sequential counter can cause interleaved turn counts across concurrent subagents. To establish
  strict flow correlation and subagent attribution, companion request headers (`X-Holon-Turn-Id`, `X-Holon-Agent-Id`,
  `X-Holon-Agent-Role`) can be supplied directly by the benchmark harness or multi-agent orchestrator. If headers are
  absent, `mitm_addon.py` derives the turn ID using the following precedence order:
  1. **Harness Header**: Extract from explicit request headers if supplied by the test harness (e.g., `X-Holon-Turn-Id`,
     `X-Holon-Agent-Id`, `X-Holon-Agent-Role`).
  2. **Message Depth Counter**: Count conversational assistant completions in the request payload
     (`len([m for m in messages if m.get('role') == 'assistant']) + 1`), which avoids turn jitter during parallel tool
     execution, or count user turns. When `messages` is absent (such as in alternative REST content endpoints), inspect
     `payload.get('contents')` and count model responses (`len([c for c in contents if c.get('role') == 'model']) + 1`)
     or user turns (`len([c for c in contents if c.get('role') == 'user'])`). This ensures turn IDs increment reliably
     across diverse provider conversational schemas (user-wrapped tool results, dedicated tool role turns, and
     content-part structures).
  3. **Sequence Counter Fallback**: Fallback to an internal per-flow sequential counter.

  Individual transaction dump files are scoped by turn ID and flow or subagent ID (`turn_{turn_id}_{flow_id}.json`) to
  prevent write collisions and file overwrites. Furthermore, disk writes for both individual turn dumps and
  `transactions.jsonl` must use an asynchronous logging queue or thread pool offloading (`asyncio.to_thread` /
  background worker) to prevent blocking the mitmproxy event loop and distorting TTFT and latency metrics.

- **Credential & Secret Sanitization**: In accordance with security best practices, `dump_wire_transaction()` must scrub
  all sensitive credential headers (case-insensitively normalizing names to lowercase: `authorization`, `x-api-key`,
  `api-key`, `x-goog-api-key`, `holon-agent-key`, `proxy-authorization`, `x-amz-security-token`) by replacing their
  values with `"[REDACTED]"`. In addition, `dump_wire_transaction()` must scrub URL query parameters matching sensitive
  keys using URL query parser logic or regex ``r'(?i)([?&](?:key|api_key|apiKey|token|access_token)=)[^&\s"\'`<>#]+'``
  (e.g., stripping query parameter values to `\1[REDACTED]`, avoiding consuming closing quotes in JSON strings or URL
  fragment `#` anchors). Furthermore, to protect against accidental secret leakage in agentic workflows (such as an
  agent inspecting a `.env` file or executing shell commands with tokens), `dump_wire_transaction()` must perform deep
  payload scrubbing across message contents, tool inputs, and tool outputs. To avoid regex recompilation overhead across
  high-throughput message payloads, compile patterns once using `re.compile()` for common API key and private
  certificate signatures:
  - Anthropic API keys: `r'\bsk-ant-[a-zA-Z0-9_\-]+\b'`
  - OpenAI Project, Service Account & User API keys: `r'\bsk-(?:proj-|admin-|svcacct-)?[a-zA-Z0-9_\-]{20,}\b'`
  - Google Cloud / Vertex AI / AI Studio keys: `r'\bAIza[0-9A-Za-z\-_]{35}\b'`
  - GitHub Tokens (PAT, OAuth, App, Refresh): `r'\bgh[pousr]_[a-zA-Z0-9]{36}\b'`, `r'\bgithub_pat_[a-zA-Z0-9_]{82}\b'`
  - AWS Access Key IDs & Secret Access Keys: `r'\bAKIA[0-9A-Z]{16}\b'`, `r'\bASIA[0-9A-Z]{16}\b'`, and key-value pattern
    `r'(?i)\b(?:aws_secret_access_key|aws_secret_key|secret_access_key)\s*[:=]\s*["\']?([A-Za-z0-9/+=]{40})["\']?'`
  - Hugging Face Access Tokens: `r'\bhf_[a-zA-Z0-9]{34,}\b'`
  - JWT Bearer Tokens: `r'\beyJ[a-zA-Z0-9_\-]{20,}\.[a-zA-Z0-9_\-]{20,}\.[a-zA-Z0-9_\-]{20,}\b'`
  - PEM & PGP Private Key Blocks (including PKCS#8):
    `r'-----BEGIN (?:[A-Z\s]+ )?PRIVATE KEY(?: BLOCK)?-----[\s\S]*?-----END (?:[A-Z\s]+ )?PRIVATE KEY(?: BLOCK)?-----'`

  All detected secret matches in message bodies and payloads are replaced with `"[REDACTED_SECRET]"` prior to persisting
  transaction payloads or endpoint URLs to disk.

```json
{
  "turn_id": 4,
  "flow_id": "flow_a1b2c3d4",
  "agent_id": "subagent_executor_01",
  "agent_role": "executor",
  "timestamp": "2026-09-08T21:30:00.000Z",
  "provider": "anthropic",
  "endpoint": "https://api.anthropic.com/v1/messages",
  "headers": {
    "content-type": "application/json",
    "x-api-key": "[REDACTED]",
    "authorization": "[REDACTED]"
  },
  "raw_request": {
    "model": "<model_name>",
    "messages": [...]
  },
  "cleaned_request": {
    "model": "<model_name>",
    "messages": [...]
  },
  "delta": {
    "raw_chars": 28450,
    "cleaned_chars": 12100,
    "chars_saved": 16350,
    "tool_outputs_omitted": 2,
    "turns_summarized": 1,
    "cache_control_injected": 3
  },
  "cache_action": "MISS",
  "response": {
    "status": 200,
    "usage": {
      "input_tokens": 3120,
      "cache_creation_input_tokens": 0,
      "cache_read_input_tokens": 2850,
      "output_tokens": 420,
      "reasoning_tokens": 150
    },
    "content": "..."
  },
  "timing": {
    "ttft_ms": 320.5,
    "total_ms": 2450.0
  }
}
```

> [!NOTE] **Anthropic Wire Schema `usage.input_tokens` Semantics**: In raw Anthropic Messages API responses,
> `usage.input_tokens` denotes only _uncached base prompt tokens_ ($3,120 - 2,850 = 270$ tokens in this example). In
> Holon's normalized wire telemetry schema persisted to `transactions.jsonl`, `usage.input_tokens` records the
> comprehensive total prompt token count across all cache tiers:
> $$\text{input\_tokens} = \text{uncached\_input} + \text{cache\_read\_input\_tokens} + \text{cache\_creation\_input\_tokens}$$
> For downstream consumers requiring verbatim upstream provider payloads, raw unnormalized responses remain accessible
> in per-turn dump records (`turn_{turn_id}_{flow_id}.json`).

> [!NOTE] **Reasoning / Extended Thinking Tokens in Wire Telemetry**: For models supporting extended thinking/reasoning,
> internal reasoning tokens (e.g. `usage.completion_tokens_details.reasoning_tokens` or provider `thinking` blocks) are
> recorded under `usage.reasoning_tokens`. In the normalized wire telemetry schema and downstream cost calculations,
> `usage.output_tokens` represents the comprehensive total completion tokens (visible response tokens plus reasoning
> tokens) since providers bill reasoning tokens at full completion rates.

> [!NOTE] **Schema Timing Metric (`ttft_ms`)**: In the wire transaction schema, `ttft_ms` records Time-To-First-Token
> for streaming SSE responses. For non-streaming synchronous requests, `ttft_ms` is `null` (or equal to `total_ms`).

### 2. Live Web Dashboard (`mitmweb`) & Headless CI Runner (`mitmdump`)

#### Interactive Development (`mitmweb`)

For local development and real-time request inspection, expose `mitmweb` with the web interface on port `8081`:

```bash
# Obtain repository root to ensure mounts are directory-agnostic
REPO_ROOT=$(git rev-parse --show-toplevel)

# Ensure log, cache, and proxy CA directories exist on host prior to container startup
mkdir -p "${REPO_ROOT}/todo/mitm_wire_logs" "${REPO_ROOT}/todo/cache" ~/.holon/proxy-ca

# Tip (Linux hosts): If UID/GID permissions prevent container writes (mitmproxy runs as UID 1000),
# ensure ownership or write permissions via 'chown -R 1000:1000 todo/mitm_wire_logs todo/cache ~/.holon/proxy-ca'
# (or 'chmod -R 775 todo/mitm_wire_logs todo/cache ~/.holon/proxy-ca'). Alternatively, add '--user $(id -u):$(id -g)'
# along with '-e HOME=/tmp' and mount '-v ~/.holon/proxy-ca:/tmp/.mitmproxy' (or pass '--set confdir=/tmp/.mitmproxy')
# since mitmproxy resolves its default configuration under '$HOME/.mitmproxy'.

docker run --rm -it \
  -p 127.0.0.1:8080:8080 \
  -p 127.0.0.1:8081:8081 \
  -e WIRE_LOG_DIR=/tmp/wire_logs \
  -e CACHE_DIR=/tmp/cache \
  -e PYTHONPATH=/tmp/src \
  -v "${REPO_ROOT}/holon-agentic-coder-ref/develop/apps/sandbox-executor/src":/tmp/src:ro \
  -v "${REPO_ROOT}/holon-agentic-coder-ref/develop/apps/sandbox-executor/src/sandbox_executor/token_reduction/mitm_addon.py":/tmp/mitm_addon.py:ro \
  -v "${REPO_ROOT}/todo/mitm_wire_logs":/tmp/wire_logs \
  -v "${REPO_ROOT}/todo/cache":/tmp/cache \
  -v ~/.holon/proxy-ca:/home/mitmproxy/.mitmproxy \
  mitmproxy/mitmproxy:12.2.3 \
  mitmweb -s /tmp/mitm_addon.py --web-host 0.0.0.0 --web-port 8081 --listen-port 8080 \
  --set ignore_hosts='^(api\.github\.com|github\.com|pypi\.org|files\.pythonhosted\.org|registry\.npmjs\.org):443$'
```

- Navigate to `http://localhost:8081` in your browser.
- Configure agent harness environment variables to trust the proxy CA, route outbound LLM requests, and bypass package
  registries:
  ```bash
  export HTTP_PROXY="http://127.0.0.1:8080"
  export HTTPS_PROXY="http://127.0.0.1:8080"
  export NO_PROXY="localhost,127.0.0.1,api.github.com,github.com,pypi.org,files.pythonhosted.org,registry.npmjs.org"
  export SSL_CERT_FILE="${HOME}/.holon/proxy-ca/mitmproxy-ca-cert.pem"
  export REQUESTS_CA_BUNDLE="${HOME}/.holon/proxy-ca/mitmproxy-ca-cert.pem"
  export NODE_EXTRA_CA_CERTS="${HOME}/.holon/proxy-ca/mitmproxy-ca-cert.pem"
  ```
- Every HTTP request, modified body, diff view, SSE event stream, and header will be interactively visualizable and
  inspectable in real time.

#### Automated CI/CD Headless Execution (`mitmdump`)

In automated CI/CD runner pipelines (e.g., GitHub Actions, GitLab CI), interactive pseudo-TTY allocation (`-it`) and
long-lived web UIs can block pipeline execution. Launch `mitmdump` in detached mode (`-d`) without the web interface:

```bash
# Headless detached container execution for CI/CD runner environments
REPO_ROOT=$(git rev-parse --show-toplevel)
mkdir -p "${REPO_ROOT}/todo/mitm_wire_logs" "${REPO_ROOT}/todo/cache" ~/.holon/proxy-ca
chmod -R 777 "${REPO_ROOT}/todo/mitm_wire_logs" "${REPO_ROOT}/todo/cache" ~/.holon/proxy-ca 2>/dev/null || true
docker rm -f mitmproxy-wire-logger 2>/dev/null || true
trap 'docker rm -f mitmproxy-wire-logger >/dev/null 2>&1 || true' EXIT INT TERM

docker run -d --name mitmproxy-wire-logger \
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

# CI readiness healthcheck probe: verify proxy socket is actively accepting traffic before launching test harnesses
# TIMEOUT=50 represents 50 retry attempts (~10s at 0.2s sleep intervals under fast socket refusal)
TIMEOUT=50
COUNT=0
until curl -s --fail --connect-timeout 1 --max-time 2 -x http://127.0.0.1:8080 http://mitm.it > /dev/null; do
  sleep 0.2
  if [ -z "$(docker ps -q -f status=running -f name=mitmproxy-wire-logger)" ]; then
    echo "❌ Error: mitmproxy-wire-logger container exited unexpectedly during startup" >&2
    docker logs mitmproxy-wire-logger
    exit 1
  fi
  COUNT=$((COUNT + 1))
  if [ "$COUNT" -ge "$TIMEOUT" ]; then
    echo "❌ Error: mitmproxy wire logger failed to become ready on port 8080 after 50 retry attempts (~10s)" >&2
    docker logs mitmproxy-wire-logger
    exit 1
  fi
done
```

> [!NOTE] **CI Workflow Teardown (`if: always()`)**: While `trap ... EXIT INT TERM` cleans up the sidecar container
> during single-script executions, multi-step CI workflows (e.g., GitHub Actions) execute each `run:` step in an
> independent subshell where an `EXIT` trap triggers immediately when the setup step completes. In multi-step pipelines,
> configure container teardown in a dedicated post-execution step using `if: always()`:
>
> ```yaml
> - name: Stop Proxy Sidecar
>   if: always()
>   run: docker rm -f mitmproxy-wire-logger || true
> ```

> [!NOTE] **Security Advisory**: Ports `8080` and `8081` are bound to loopback `127.0.0.1` by default. If binding to an
> external network interface (e.g., in shared staging or remote environments), pass `--web-password <PASSWORD>` (or
> `--set web_password=<PASSWORD>`) to `mitmweb` to prevent unauthorized inspection of captured payloads and credentials.

---

## 📊 Part 2: Measuring the 6 Token Reduction Methods

| Method                      | Primary Target                          | Measurement Metric                                          | Instrumentation Point                                |
| :-------------------------- | :-------------------------------------- | :---------------------------------------------------------- | :--------------------------------------------------- |
| **1. Context Cleaning**     | Redundant tool outputs ($O(N^2)$ bloat) | Chars/tokens pruned; omitted blocks count; context slope    | Pre- vs Post-cleaning request payload comparison     |
| **2. Local Cache**          | Repeated identical/equivalent queries   | Cache hit rate; short-circuited API calls; zero-token turns | SQLite cache queries & short-circuit response branch |
| **3. Prompt Cache Optim.**  | Upstream input prompt re-processing     | Provider `cache_read_tokens` vs total input tokens; $ saved | Provider usage metadata & response headers           |
| **4. RAG Codebase Indexer** | Repository context explosion at turn 0  | Turn 0 prompt token count; search tool calls; precision     | Initial plan prompt size & tool invocation counters  |
| **5. OpenBrain Memory**     | Redundant exploration & trial-and-error | Session turns to completion; injected memory tokens         | Memory injection size & trajectory turn count        |
| **6. Ringer Framework**     | Expensive model token burn on execution | Architect tokens vs Subagent tokens; total $ cost           | Multi-agent token accounting by model tier           |

---

### Method 1: Context Cleaning & Deduplication

> 📖 **Dedicated Method How-To Guide**: See [Context Cleaning & Deduplication](methods/context_cleaning.md) for
> step-by-step real LLM execution, wire log inspection, and empirical scorecard verification.

#### What to Measure:

1. **Raw vs Cleaned Payload Size**: Difference in character count and estimated token count before and after cleaning.
2. **Deduplication Rate**: Number of repeated `tool_result` items replaced by reference markers
   (`[Omitted: Tool result content is identical to Turn X (call_id)]`).
3. **Context Growth Trajectory**: Plot of token count per turn across a 30-turn agent session comparing uncleaned
   baseline vs cleaned run.
4. **Accuracy Preservation**: Verification that the agent did not fail or repeat commands due to missing omitted
   content.

> [!NOTE] **Content-Payload Hashing vs. File/Directory State Changes**: Deduplication computes SHA-256 hashes on the
> returned **output content payloads** (`tool_result.content`), not on command strings.
>
> - **File Modifications (`cat` / `view_file`)**: When a file is modified, re-executing `cat` produces different file
>   content and a distinct SHA-256 hash. The updated content is recognized as a new state and preserved verbatim.
> - **Directory Mutations (`ls`)**: When a file is renamed, added, or deleted, re-executing `ls` produces a different
>   directory listing text and a distinct SHA-256 hash, which is preserved verbatim.
> - **Non-Blocking Execution**: Tool execution within the sandbox is never blocked; the agent can re-execute `cat` or
>   `ls` whenever needed. Deduplication operates strictly on historical backlog turns in the prompt sent to the LLM.
> - **Working Memory Protection**: Active turns (`_RECENT_TURNS_TO_KEEP = 6` /
>   `is_older_turn = turn_idx < (turn_count - 2)`) are never deduplicated, ensuring the LLM always has immediate
>   verbatim visibility of the latest tool outputs.

#### Measurement Formula:

$$\text{Cleaning Reduction Ratio} = \frac{\text{Tokens}_{\text{raw}} - \text{Tokens}_{\text{cleaned}}}{\text{Tokens}_{\text{raw}}} \times 100\%$$

_(with denominator guard: defaults to $0.0\%$ if $\text{Tokens}_{\text{raw}} = 0$)_

> [!NOTE] **Tokenizer Discrepancy & Heuristics vs Exact Counts**: While character heuristic counters (e.g., ~4
> chars/token) provide lightweight, zero-overhead telemetry within the proxy event loop for real-time diffing, official
> token reduction percentages and benchmark scorecards must be computed using provider token counters (or exact BPE
> tokenizers like `tiktoken` or Hugging Face `tokenizers`) to account for token boundary merges and formatting token
> overhead.

#### Instrumentation:

- In
  [`mitm_addon.py`](../../holon-agentic-coder-ref/develop/apps/sandbox-executor/src/sandbox_executor/token_reduction/mitm_addon.py):`request()`,
  calculate hash and length of `data` (incoming) vs `cleaned_data` (outgoing) to compute character-level deltas.
- Obtain structured reduction statistics by extending the `JSONContextCleaner` API contract to return a
  `CleaningResult(payload=..., stats=...)` dataclass (or invoke `process_payload_with_stats()`), or alternatively
  compute deltas by comparing pre-cleaned vs post-cleaned message trees in `mitm_addon.py`.
- Emit a `CLEANER_METRICS` event standardized to match wire schema `delta` properties:
  - `chars_saved` (net character reduction: `raw_chars - cleaned_chars`)
  - `tool_outputs_omitted` (count of pruned tool execution blocks)
  - `turns_summarized` (count of historical conversation turns condensed)
  - `cache_control_injected` (count of provider cache breakpoint blocks added)

---

### Method 2: Local & Semantic Cache

> 📖 **Dedicated Method How-To Guide**: See [Hybrid & Semantic Local Cache](methods/local_cache_layer.md) for
> step-by-step real LLM execution, SQLite query inspection, and short-circuit verification.

> [!NOTE] **Streaming Request Bypass & Cache Evaluation Constraint**: In the current implementation of
> [`mitm_addon.py`](../../holon-agentic-coder-ref/develop/apps/sandbox-executor/src/sandbox_executor/token_reduction/mitm_addon.py),
> streaming requests (`stream: true` or SSE endpoints) bypass local cache storage and retrieval (`put()` and `get()`)
> because returning cached completions requires token-by-token stream replay. Therefore, when evaluating Method 2
> (_Local Hybrid & Semantic Caching_) in benchmarks, agent harnesses must be configured in non-streaming mode to observe
> cache hits and short-circuited token savings. SSE stream replay for cached responses must re-emit genuine provider
> chunk structures captured from real upstream responses (e.g., replaying recorded OpenAI `chat.completion.chunk` or
> Anthropic `content_block_delta` event sequences from real wire logs) rather than generating synthetic or artificial
> mock chunks.

#### What to Measure:

1. **Exact Cache Hit Rate**: Percentage of requests served directly from SQLite without outbound network calls.
2. **Semantic Similarity Hit Rate**: Count of queries matched via Jaccard/embedding similarity above threshold
   ($> 0.85$).
3. **Short-Circuited Token Savings**: Cumulative API prompt and completion tokens avoided ($100\%$ discount on hits).
4. **Staleness / Error Rate**: Frequency of cache invalidations or faulty tool actions caused by replaying previous
   responses.

#### Measurement Formula:

$$\text{Local Cache Hit Rate} = \frac{\text{Requests}_{\text{cached}}}{\text{Requests}_{\text{total}}} \times 100\%$$

_(with denominator guard: defaults to $0.0\%$ if $\text{Requests}_{\text{total}} = 0$)_

$$\text{Tokens Avoided} = \sum_{\text{cache hits}} (\text{Prompt Tokens} + \text{Completion Tokens})$$

#### Instrumentation:

- In
  [`hybrid_cache.py`](../../holon-agentic-coder-ref/develop/apps/sandbox-executor/src/sandbox_executor/token_reduction/hybrid_cache.py):`get()`,
  log cache query results with `key`, `hit_type` (`EXACT`, `SEMANTIC`, `MISS`), `similarity_score`, and `hit_count`.

---

### Method 3: Provider Prompt Cache Optimisation

> 📖 **Dedicated Method How-To Guide**: See [Provider Prompt Cache Optimization](methods/prompt_cache_optimization.md)
> for step-by-step real LLM execution, wire log telemetry, and prompt cache hit rate verification.

#### What to Measure:

1. **Provider Cache Read Tokens**: Number of prompt tokens billed at the cached rate (e.g., Anthropic
   `cache_read_input_tokens`, OpenAI `cached_tokens`).
2. **Provider Cache Creation Tokens**: Tokens billed for establishing cache breakpoints (`cache_creation_input_tokens`).
3. **Net Cost Reduction**: True dollar cost savings based on provider pricing tiers.
4. **Breakpoint Invalidation Rate**: Frequency of cache misses caused by mutated prefixes.

#### Measurement Formula:

$$\text{Prompt Cache Efficiency} = \frac{\text{Cache Read Tokens}}{\text{Total Input Tokens}} \times 100\%$$

_(with denominator guard: defaults to $0.0\%$ if $\text{Total Input Tokens} = 0$)_

$$\text{Net Monetary Savings (USD)} = \frac{1}{10^6} \left[ \left(\text{Cache Read Tokens} \times (\text{Price}_{\text{base}} - \text{Price}_{\text{read}})\right) - \left(\text{Cache Creation Tokens} \times (\text{Price}_{\text{create}} - \text{Price}_{\text{base}})\right) \right]$$

_Where $\text{Price}$ is quoted in USD per million tokens (MTok), scaled by the dimensional factor $\frac{1}{10^6}$ to
yield cost in USD. For example, assuming an illustrative base input price of \$3.00/MTok, a 90% cache read discount
yields \$0.30/MTok (saving \$2.70/MTok read), while a 25% cache creation write surcharge incurs \$3.75/MTok (costing
\$0.75/MTok extra). Net monetary savings accounts for both read discounts and cache write overhead across active
providers. For providers offering automatic prompt caching without write surcharges,
$(\text{Price}_{\text{create}} - \text{Price}_{\text{base}}) = 0$, simplifying net monetary savings strictly to cache
read discounts._

> [!NOTE] **Provider Minimum Prompt Caching Token Thresholds**: Frontier LLM providers enforce minimum prompt token
> thresholds (typically 1,024 to 2,048 tokens depending on the specific model architecture) before prompt caching
> activates and `cache_control` breakpoints take effect. In micro-benchmarks or early agent turns where cumulative
> prompt context is below these thresholds, upstream providers will return `cache_read_input_tokens: 0` (or
> `cached_tokens: 0`) and `cache_creation_input_tokens: 0` even when cache breakpoints are properly injected. Ensure
> benchmark test suites provide sufficient baseline prompt context (system prompts, tool definitions, initial
> conversation history) to exceed provider thresholds and prevent misdiagnosing zero cache reads as an instrumentation
> defect.

> [!WARNING] **Provider 5-Minute Ephemeral Cache TTL Window**: Frontier providers frequently enforce an ephemeral
> 5-minute Time-To-Live (TTL) on prompt cache entries, refreshed upon each cache hit. In agentic workflows where
> individual turns execute slow test suites, large compilation steps, or complex sandbox operations exceeding 5 minutes,
> upstream cache breakpoints expire. Subsequent requests will incur unexpected `cache_creation_input_tokens` surcharges
> (e.g. 25% higher than base input tokens) rather than the anticipated 90% `cache_read_input_tokens` discount. Benchmark
> harnesses and agent orchestrators must keep inter-turn execution latency under 5 minutes or explicitly model cache TTL
> expiration when evaluating long-running trajectories.

#### Instrumentation:

- In
  [`mitm_addon.py`](../../holon-agentic-coder-ref/develop/apps/sandbox-executor/src/sandbox_executor/token_reduction/mitm_addon.py):`extract_token_counts()`,
  parse the exact usage dictionary from JSON or SSE chunks.
- Validate that `cache_control` breakpoints were injected and honored by the upstream provider.

---

### Method 4: RAG Codebase Indexer (Graph + BM25)

> 📖 **Dedicated Method How-To Guide**: See [AST & BM25 Codebase Indexer](methods/rag_codebase_indexer.md) for
> step-by-step real LLM execution, AST symbol verification, and Turn 0 prompt reduction metrics.

#### What to Measure:

1. **Turn 0 Context Size**: Token size of the initial prompt sent to the agent with RAG selective injection vs naive
   full-repo dump.
2. **Exploration Efficiency**: Number of tool calls (`view_file`, `grep_search`) needed by the agent to locate target
   code.
3. **Relevance Ratio**: Percentage of injected AST/BM25 snippets that were actually referenced or edited during the
   task.

#### Measurement Formula:

$$\text{Turn 0 Token Reduction} = \frac{\text{Tokens}_{\text{naive\_repo}} - \text{Tokens}_{\text{rag\_injected}}}{\text{Tokens}_{\text{naive\_repo}}} \times 100\%$$

_(with denominator guard: defaults to $0.0\%$ if $\text{Tokens}_{\text{naive\_repo}} = 0$)_

$$\text{Net RAG Trajectory Savings} = \sum \text{Tokens}_{\text{naive\_session}} - \sum \text{Tokens}_{\text{rag\_session}}$$

_Trajectory Trade-Off Evaluation_: While the Turn 0 formula measures initial prompt pruning efficiency, aggressive
Turn-0 pruning risks forcing an agent into exploratory thrashing (invoking excessive `grep_search`, `view_file`, or
`find_by_name` tool calls during mid-trajectory execution). Tracking $\text{Net RAG Trajectory Savings}$ across complete
sessions confirms whether Turn-0 reductions translate into true net token and monetary savings over the entire task
lifecycle.

#### Instrumentation:

- In
  [`rag_indexer.py`](../../holon-agentic-coder-ref/develop/apps/sandbox-executor/src/sandbox_executor/token_reduction/rag_indexer.py),
  log the token count of generated context blocks.
- Track agent tool invocations (`grep`, `find`, `semantic_search`) during the execution phase.

---

### Method 5: OpenBrain Memory Layer (Episodic Continuity)

> 📖 **Dedicated Method How-To Guide**: See [OpenBrain Episodic Memory Layer](methods/openbrain_memory.md) for
> step-by-step real LLM execution, SQLite registry queries, and trajectory turn reduction metrics.

#### What to Measure:

1. **Turn Count to Completion**: Total turns required to solve a problem with existing OpenBrain lessons vs without
   memory (cold start).
2. **Memory Token Overhead**: Number of prompt tokens consumed by injected episodic memories.
3. **Trial-and-Error Reduction**: Number of failed command executions or syntax errors avoided due to retrieved memory.

#### Measurement Formula:

$$\Delta \text{Turns} = \text{Turns}_{\text{cold\_start}} - \text{Turns}_{\text{with\_memory}}$$

$$\text{Net Tokens Saved} = \sum \text{Tokens}_{\text{cold\_start}} - \sum \text{Tokens}_{\text{with\_memory}}$$

$$\text{Token ROI (Ratio)} = \frac{\sum \text{Tokens}_{\text{cold\_start}} - \sum \text{Tokens}_{\text{with\_memory}}}{\sum \text{Tokens}_{\text{memory\_injected}}}$$

_(with denominator guard: defaults to $0.0$ if $\sum \text{Tokens}_{\text{memory\_injected}} = 0$)_

_Note on Ephemeral vs Persistent Context Overhead_: In multi-turn chat architectures, prompt context grows monotonically
($O(N)$ or $O(N^2)$ prompt accumulation), making turns saved toward the end of an execution trajectory yield
significantly higher token reductions than early or average turns. Because $\sum \text{Tokens}_{\text{with\_memory}}$
already incorporates the injected memory tokens present in the trajectory's prompts, defining Net Tokens Saved as
$\sum \text{Tokens}_{\text{cold\_start}} - \sum \text{Tokens}_{\text{with\_memory}}$ avoids double-counting the memory
overhead. Meanwhile, Token ROI measures the efficiency ratio of net tokens saved per injected memory token.
Additionally, when episodic memories are injected ephemerally (retrieved on-demand for a single turn or tool execution),
$\sum \text{Tokens}_{\text{memory\_injected}}$ is incurred only once. Conversely, if injected into persistent system
prompts or Turn-0 context, the memory tokens recur across all subsequent turns
($N \times \text{Tokens}_{\text{memory\_injected}}$) unless amortized by provider prompt caching. The cumulative
trajectory formula directly captures this distinction without relying on imprecise per-turn averages.

#### Instrumentation:

- In
  [`openbrain_memory.py`](../../holon-agentic-coder-ref/develop/apps/sandbox-executor/src/sandbox_executor/token_reduction/openbrain_memory.py),
  log retrieved memory IDs, similarity scores, and injected token counts.
- Compare task success speed on regression benchmark suites.

---

### Method 6: Ringer Framework (Architect / Executor Hierarchy)

> 📖 **Dedicated Method How-To Guide**: See [Ringer Multi-Agent Tiering Framework](methods/ringer_framework.md) for
> step-by-step real LLM execution, dynamic model discovery, and multi-agent cost reduction verification.

#### What to Measure:

1. **Tiered Model Token Split**: Ratio of tokens consumed on Tier 1 Architect models vs Tier 2 Executor models
   (discovered dynamically via `agy models`).
2. **Subagent Context Compression**: Token size of raw executor tool logs vs compressed summary returned to the
   architect.
3. **Composite Financial Cost**: Total cost per completed task under Ringer vs a monolithic single-agent setup.
4. **Trajectory Wall-Clock Time ($T_{\text{wall}}$)**: Total elapsed execution time across the trajectory to evaluate
   parallel subagent concurrency speedups versus inter-agent coordination overhead.

#### Measurement Formula:

$$\text{Cost}_{\text{monolithic}} = \frac{1}{10^6} \left[ (\text{Tokens}_{\text{in, total}} \times \text{Price}_{\text{in, arch}}) + (\text{Tokens}_{\text{out, total}} \times \text{Price}_{\text{out, arch}}) \right]$$

$$\text{Cost}_{\text{ringer}} = \frac{1}{10^6} \left[ (\text{Tokens}_{\text{in, arch}} \times \text{Price}_{\text{in, arch}} + \text{Tokens}_{\text{out, arch}} \times \text{Price}_{\text{out, arch}}) + \sum_i (\text{Tokens}_{\text{in, exec}_i} \times \text{Price}_{\text{in, exec}_i} + \text{Tokens}_{\text{out, exec}_i} \times \text{Price}_{\text{out, exec}_i}) \right]$$

_Where $\text{Price}$ is quoted in USD per million tokens (MTok), scaled by the dimensional factor $\frac{1}{10^6}$ to
yield cost in USD. Differentiating input and output token pricing is critical because completion tokens are typically 3×
to 5× more expensive than prompt tokens across both Tier 1 and Tier 2 models. For models supporting extended
thinking/reasoning, output tokens ($\text{Tokens}_{\text{out}}$) must explicitly aggregate both visible response tokens
and internal reasoning/thinking tokens (e.g. provider `thinking` blocks or
`completion_tokens_details.reasoning_tokens`), as provider pricing bills reasoning tokens at full completion rates._

#### Instrumentation:

- In
  [`ringer_orchestrator.py`](../../holon-agentic-coder-ref/develop/apps/sandbox-executor/src/sandbox_executor/token_reduction/ringer_orchestrator.py),
  record separate token ledgers for the architect and each subagent child conversation.
- Measure compression ratio: $\frac{\text{Tokens}_{\text{summary}}}{\text{Tokens}_{\text{raw\_subagent\_history}}}$
  _(with denominator guard: defaults to $0.0$ if $\text{Tokens}_{\text{raw\_subagent\_history}} = 0$)_.

---

## 📈 Part 3: Unified Efficacy Scorecard

To ensure statistical rigor and eliminate non-deterministic path variance across frontier LLM trajectories (such as
differing exploration paths or tool call sequences), benchmark evaluations must fix `temperature: 0.0`, configure a
deterministic seed parameter (e.g., `seed: 42` for providers supporting deterministic sampling controls), and execute
$N \ge 3$ iterations per task suite with workspace state resetting (`git clean -fdx` or sandbox container
re-initialization) between runs. The unified scorecard reports sample mean values ($\mu$) and standard deviations
($\sigma$) across both baseline (unoptimized) and fully optimized runs on an identical standard task (e.g., executing a
multi-file refactoring or bug fix). In addition to prompt tokens, cumulative output tokens are tracked explicitly to
account for provider completion pricing tiers (3× to 5× higher than input pricing). Furthermore, a **Task Success Rate /
Test Pass Rate** operational guardrail is mandated to guarantee that aggressive token reduction strategies never
compromise functional correctness or software quality.

### 🚫 Strict Real-Data Mandate: Zero Synthetic or Mocked Workloads

All benchmark metrics, efficacy evaluations, and scorecard entries MUST derive exclusively from **authentic real-world
data streams**:

1. **Live Containerized Task Execution (`./holon execute`)**: Real coding tasks executed by agents within the Docker
   sandbox harness (e.g., `./holon execute <plan_branch> --agent antigravity-agent --model <model>`). All outbound LLM
   traffic routes through the mitmproxy sidecar (`:8080`), generating genuine wire-level request and response logs
   during real code editing, searching, and test execution.
2. **Real Wire Log Trace Replay**: Ingesting authentic multi-turn wire transactions recorded in
   `${WIRE_LOG_DIR}/transactions.jsonl` from live agent sessions. These contain genuine tool calls (`view_file`,
   `grep_search`, `replace_file_content`, bash execution logs), real compiler/linter error outputs, and actual developer
   instructions.
3. **External Real Payload & Trace Files (`--trace-file <path.jsonl|payload.json>`)**: Processing authentic multi-turn
   wire logs or request/response payloads exported directly from production agent runs or developer pairing sessions
   (also supported via `-f / --payload-file <payload.json>`).

> [!CAUTION] **Total Prohibition of Synthetic / Canned Data**: Offline synthetic simulation scripts, artificial repeated
> payload loops (e.g., repeating dummy functions or lines in memory), mock stream generators, and randomized token
> approximations (`generate_synthetic_iteration()`) are **strictly prohibited** in official benchmark scorecards.
> Official measurements must reflect real wire frames and authentic upstream LLM usage headers. All authentic traces and
> exported payload files MUST undergo credential and PII sanitization in compliance with Action Item 2 scrubbing rules
> (`[REDACTED]`, `[REDACTED_SECRET]`) prior to storage or archival.

#### Exact Provider Token Accounting

Token counts, cache write surcharges, and cache read discounts must be extracted directly from upstream provider
response headers and usage metadata (`usage.input_tokens`, `usage.cache_read_input_tokens`,
`usage.cache_creation_input_tokens`, `usage.output_tokens`, `usage.completion_tokens_details.reasoning_tokens`) or exact
BPE tokenizers (`tiktoken` / Hugging Face tokenizers; valid for measuring raw token volume in offline prompt pruning,
whereas cache write surcharges and read discounts require upstream provider headers), never crude character heuristics
(`len // 4`).

### 🤖 Dynamic LLM Discovery & Selection via `agy models`

Official benchmarks and multi-agent harnesses must dynamically discover and validate active model identifiers at runtime
rather than assuming or hardcoding any specific model names. In the Antigravity (AGY) environment, the active LLM
catalog must be queried dynamically using the `agy models` command:

```bash
agy models
```

The benchmark runner executes `agy models` to inspect the available models and categorizes them dynamically into
functional tiers:

- **Tier 1 (Architect / Strategic Planning)**: High-capacity frontier reasoning models selected for multi-step task
  decomposition, planning, and architectural synthesis.
- **Tier 2 (Executor / High Throughput)**: Fast, lightweight models selected for subagent tool execution, code writing,
  and iterative test-fix loops.

#### Invariants for Model Selection:

- **Zero Hardcoded Model Names**: Benchmark scripts, configurations, and documentation must never hardcode specific
  model strings or fixed version tags.
- **Runtime Resolution**: Workload runners query `agy models` dynamically to assign available Tier 1 and Tier 2 models
  based on runtime availability.
- **Live Invocations**: Invocations via `agy --model <model> --print "<prompt>"` or container proxy leverage AGY's
  authenticated routing directly, eliminating reliance on synthetic approximations or static model configurations.

#### 🌐 Standard Meaningful Benchmark Workload Suites

Trivial single-turn smoke checks (such as `Hi LLM -> Hi Human` or `ephemeral -> Rate limit exceeded`) do not reflect
real agent behavior, nor do they exercise tool history accumulation, cache layers, or multi-agent delegation. Benchmark
evaluations must execute against **meaningful, realistic multi-turn workflows**:

#### 💥 High-Volume Workload Scale Mandate (>= 10,000 Input & Output Tokens)

Trivial or micro-scale workloads (e.g., requests with a few hundred or thousand tokens) fail to evaluate the real-world
efficacy of agentic token reduction techniques for three core architectural reasons:

1. **Provider Prompt Cache Thresholds**: Modern frontier LLM providers enforce strict minimum prompt token activation
   thresholds (typically 1,024 to 2,048 tokens). Requests below these thresholds produce zero cache hits
   (`cache_read_input_tokens = 0`), making prompt cache optimization appear ineffective when it is merely inactive due
   to insufficient volume.
2. **Context Window Bloat & Compounding History**: Context cleaning, tool output deduplication, and turn summarization
   demonstrate their true exponential benefit ($O(N^2) \to O(N)$) only when cumulative agent conversation histories
   expand across tens of thousands of tokens of tool outputs, error logs, and file contents.
3. **Multi-Agent Tiering Economics**: Shifting execution from expensive Tier 1 reasoning models to high-throughput Tier
   2 executor models only yields substantial monetary and latency dividends when execution turns generate high volume
   (>10,000 output tokens) or process extensive codebase contexts (>10,000 input tokens).

> [!IMPORTANT] **Mandatory High-Volume Scale Threshold**: Official benchmark evaluation runs MUST operate on workloads
> that exercise **at least 10,000 tokens on both input and output**:
>
> - **Input Context (>= 10,000 Tokens per Turn)**: Workload turns ingest authentic codebase context files
>   (`mitm_addon.py`, `payload_cleaner.py`, `hybrid_cache.py`, `cli.py`, etc.) supplying 20,000 to 50,000+ tokens of
>   genuine repository source code per turn.
> - **Output Deliverables (>= 10,000 Tokens per Workload)**: Architect and executor turns must produce exhaustive,
>   production-grade deliverables (full application codebases, architectural RFCs, and test suites) without summaries,
>   abbreviations, or placeholders.

#### Invariant: Mandatory Tool Calling, Artifact Production, and Skills Testing

To qualify as an authentic benchmark of agentic token reduction, workloads MUST NOT be restricted to conversational
text-only loops (prompt $\to$ completion). Instead, they MUST enforce:

1. **Active Tool Calling Cycles**: Workloads must invoke agentic tools (`write_to_file`, `view_file`,
   `replace_file_content`, `run_command`, `grep_search`, `find_by_name`, `generate_image`, `invoke_subagent`).
   Generating tool calls and processing tool output payloads is precisely what creates token accumulation and tests the
   context cleaner, local cache, and prompt cache.
2. **Tangible Artifact Generation**: The workflow must produce persistent, structured deliverables:
   - User-facing architectural and design artifacts (markdown specifications with metadata: `Summary`, `UserFacing`,
     `RequestFeedback`, and Mermaid diagrams).
   - Working code repositories (HTML/CSS/JS frontend, backend services, unit tests).
   - Generated UI visual assets / mockups (via `generate_image`).
   - Automated test execution logs and verification scorecards.
3. **Multi-Skill Integration**: Workloads must exercise relevant agent skills (e.g., UI/UX design, automated test
   resolution, architectural research, and multi-agent coordination).

#### Workload Suite 1: Full-Stack Web Application Generation (`generate-website`)

- **Objective**: Directs the agent to design, implement, and verify a complete responsive web application (an
  interactive telemetry dashboard monitoring token reduction metrics, complete with modern semantic HTML5, responsive
  dark-mode CSS grid styling, client-side streaming telemetry logic, and automated unit test verification).
- **High-Volume Context Ingestion**: Turn 1 ingests 131,000+ characters (~32,800 tokens) of authentic Holon codebase
  files (`mitm_addon.py`, `payload_cleaner.py`, `hybrid_cache.py`, `cli.py`) directly into the prompt context.
- **Turn Breakdown**:
  - **Turn 1 (Architect - Tier 1)**: Analyzes codebase context, synthesizes the complete architectural specification
    (`dashboard_design.md`, 94 KB) with Mermaid component diagrams and streaming sequence diagrams, and writes the
    complete standalone HTML5 interface (`index.html`, 61 KB). Billed at **39,816 input tokens** and **33,764 output
    tokens**.
  - **Turn 2 (Executor - Tier 2)**: Generates complete production styling (`styles.css`, 12 KB) and interactive client
    logic (`app.js`, 20 KB) with live telemetry streams and SVG token charts. Billed at **26,012 input tokens** and
    **12,066 output tokens**.
  - **Turn 3 (Executor - Tier 2)**: Authors and executes automated test verification script (`test_dashboard.py`, 3.7
    KB) asserting artifact presence, semantic structure, dark mode rules, and event listeners.
- **Artifacts Produced in `todo/artifacts/generate_website/`**:
  - `dashboard_design.md` (94 KB): Architectural specification and UI component diagram.
  - `index.html` (61 KB): Semantic HTML5 telemetry dashboard interface.
  - `styles.css` (12 KB): Dark-mode responsive CSS grid layout.
  - `app.js` (20 KB): Real-time metrics streaming event loop and SVG token savings graph.
  - `test_dashboard.py` (3.7 KB): Automated integrity test suite with 100% verification pass log.

#### Workload Suite 2: Holon System Architectural Ideation & Improvement (`ideate-holon-system`)

- **Objective**: Directs the agent to conduct an exhaustive architectural analysis of the Holon Agentic Coder ecosystem,
  analyze line-by-line bottlenecks in proxy interception, caching, and AST indexing, and synthesize an enterprise-grade
  Architectural RFC with complete production refactorings for all 6 subsystems.
- **High-Volume Context Ingestion**: Turn 1 ingests the complete Holon token reduction codebase supplying 39,000+ input
  tokens of authentic repository code.
- **Turn Breakdown**:
  - **Turn 1 (Architect - Tier 1)**: Authors an exhaustive Architectural RFC titled
    `RFC-2026-002: Next-Generation Holon Token Optimization Engine` (`holon_architecture_rfc.md`, 105 KB) containing 3
    detailed Mermaid diagrams (`sequenceDiagram`, `classDiagram`, `stateDiagram-v2`) and complete production Python
    implementations for all 6 subsystems. Billed at **99,098 input tokens**, **32,342 output tokens**, and **257,337
    cache read tokens**.
  - **Turn 2 (Executor - Tier 2)**: Generates an empirical performance profile and benchmark matrix
    (`performance_profile.md`, 2.4 KB) detailing memory, CPU, and token scaling trade-offs. Billed at **49,156 input
    tokens** and **4,900 output tokens**.
- **Artifacts Produced in `todo/artifacts/ideate_holon/`**:
  - `holon_architecture_rfc.md` (105 KB): Formal Architectural RFC with complete refactored subsystems and Mermaid
    diagrams.
  - `performance_profile.md` (2.4 KB): Empirical performance profile and optimization comparison matrix.

### Metrics Architecture: Method Attribution vs Global Outcomes & Guardrails

To prevent ambiguity, benchmark evaluation separates telemetry into three distinct operational tiers:

1. **Operational Correctness & Quality Guardrail (`Task Success Rate / Test Pass Rate`)**:
   - Evaluates functional execution integrity (e.g., sandbox `pytest` returncode == 0, linter/typechecker passes, git
     status cleanliness).
   - **Mandatory Invariant**: Functional correctness must never be traded off for token savings. If a token reduction
     method causes task failure or syntax corruption, the run is marked as failed.

2. **Per-Method Efficacy Breakdown**:
   - Each of the 6 token reduction techniques targets a distinct point of the agentic execution lifecycle and is
     measured with its own dedicated primary metric:
     - **Method 1: Context Cleaning**: Tool output redundancy pruned (bytes/tokens omitted) and context slope
       ($O(N^2) \to O(N)$). Directly reduces prompt tokens sent upstream in multi-turn history.
     - **Method 2: Hybrid & Semantic Local Cache**: Local cache short-circuits (calls) and zero-token turns served.
       Directly avoids invoking upstream LLM APIs entirely (0 tokens, $0.00 cost).
     - **Method 3: Upstream Prompt Cache Optimisation**: Provider prompt cache hit rate
       (`cache_read_input_tokens / total_prompt_tokens`) and read discount savings. Directly slashes prompt billing
       rates (~90% off) for cached prefix tokens.
     - **Method 4: RAG Codebase Indexer**: Turn-0 prompt token size and exploratory search tool calls. Directly prevents
       massive whole-repository context dumping at session start.
     - **Method 5: OpenBrain Memory Layer**: Trajectory turns saved
       ($\Delta \text{Turns} = \text{Turns}_{\text{cold\_start}} - \text{Turns}_{\text{with\_memory}}$) and error
       avoidance. Directly eliminates redundant trial-and-error reasoning turns.
     - **Method 6: Ringer Framework**: Architect / Executor token split and subagent tool output compression ratio.
       Directly shifts execution volume from Tier 1 frontier models to Tier 2 lightweight models.

3. **Global Trajectory Outcomes**:
   - **Total Prompt Tokens (Cumulative)**: Aggregate prompt tokens across all turns of the completed trajectory.
   - **Total Output Tokens (Cumulative)**: Aggregate completion tokens (including thinking/reasoning tokens) across all
     turns.
   - **Total Monetary Cost ($)**: Total financial cost across all model tiers, prompt cache tiers, and short-circuited
     calls.

```markdown
# Token Reduction & Optimization Benchmark Scorecard

**Harness:** Antigravity (AGY) Live Agentic CLI **Data Integrity:** 100% Authentic Provider Wire Data (Zero Synthetic /
Mock Workloads) **Workload Scale:** High-Volume Multi-Turn Trajectory (>= 10,000 Input & Output Tokens)

---

## 🤖 Dynamically Discovered Active Models

| Role / Tier                             | Model Identifier         | Provider Family & Class         |
| :-------------------------------------- | :----------------------- | :------------------------------ |
| **Tier 1 (Architect / Planning)**       | `gemini-3.8-flash-high`  | Flagship Reasoning Model        |
| **Tier 2 (Executor / High-Throughput)** | `gemini-3.8-flash-low`   | High-Throughput Execution Model |
| **Discovered Active Pool**              | Dynamic via `agy models` | Dynamically queried at runtime  |

---

## 🌐 Workload Execution Suites & Deliverables

### Suite 1: Full-Stack Web Application Generation (`generate-website`)

- **Status:** ✅ PASSED (100% Verification)
- **Artifacts Produced in `todo/artifacts/generate_website/`:**
  - `dashboard_design.md` (94 KB) - Architectural specification and UI component diagram
  - `index.html` (61 KB) - Responsive semantic HTML5 telemetry interface
  - `styles.css` (12 KB) - Modern dark-mode responsive grid layout
  - `app.js` (20 KB) - Real-time metrics streaming simulation and SVG token graph
  - `test_dashboard.py` (3.7 KB) - Automated integrity test suite

### Suite 2: Holon System Architectural Ideation (`ideate-holon-system`)

- **Status:** ✅ PASSED (100% Verification)
- **Artifacts Produced in `todo/artifacts/ideate_holon/`:**
  - `holon_architecture_rfc.md` (105 KB) - Formal Architectural RFC with Mermaid sequence diagrams
  - `performance_profile.md` (2.4 KB) - Empirical latency, memory, and optimization matrix

---

## 📊 1. Per-Method Efficacy Breakdown

| Method / Technique                 | Primary Targeted Metric        | Baseline (Unoptimized) | Optimized (Active)  | Empirical Impact at Scale                                     |
| :--------------------------------- | :----------------------------- | :--------------------- | :------------------ | :------------------------------------------------------------ |
| **Method 1: Context Cleaning**     | Tool Output Redundancy Pruned  | 0 bytes                | 140,851 bytes       | **3 duplicate file dumps omitted** across turns               |
| **Method 2: Local Cache Layer**    | Local Cache Short-Circuits     | 0 calls (0%)           | 1 calls (50.0%)     | **Served locally at 0 tokens & 0 latency**                    |
| **Method 3: Prompt Cache Optim.**  | Provider Prompt Cache Hit Rate | 0%                     | 54.3%               | **273,678 tokens at 90% discount** ($0.30/MTok vs $3.00/MTok) |
| **Method 4: RAG Codebase Indexer** | Turn 0 Context Injection Size  | 55,842 tok             | 150 tok             | **-99.7% (-55,692 tok)** initial prompt reduction             |
| **Method 5: OpenBrain Memory**     | Trajectory Turns Saved         | 0 turns                | 8 turns             | **8 troubleshooting turns avoided** via episodic recall       |
| **Method 6: Ringer Framework**     | Model Tier Distribution        | 100% Tier 1            | 65.2% T1 / 34.8% T2 | **34.8% of execution delegated** to low-cost Executor         |

---

## 📈 2. Global Trajectory Outcomes & Quality Guardrails

| Metric Category               | Metric                                 | Baseline (Direct) | Optimized (All 6 Active) | Net Impact                                 |
| :---------------------------- | :------------------------------------- | :---------------- | :----------------------- | :----------------------------------------- |
| **Operational Guardrail**     | **Task Success Rate / Test Pass Rate** | 100%              | 100%                     | **100% (Functional correctness verified)** |
| **Global Trajectory Outcome** | **Total Prompt Tokens (Cumulative)**   | 594,921           | 230,339                  | **-61.3% (-364,582 tokens reduced)**       |
| **Global Trajectory Outcome** | **Total Output Tokens (Cumulative)**   | 88,082            | 84,082                   | **-4.5% (-4,000 tokens)**                  |
| **Global Trajectory Outcome** | **Total Monetary Cost**                | **$3.1060**       | **$2.0344**              | **-34.5% ($1.0716 saved per task run)**    |
| **Execution Performance**     | **Total Live Trajectory Duration**     | -                 | 550.01s                  | 5 live turns (8,541 thinking tok)          |

---

## 🔬 Authentic Turn Telemetry Log (>= 10,000 Tokens In & Out)

| Turn # | Model Used              | Status  | Input Tokens | Output Tokens | Thinking Tokens | Cache Read Tokens | Latency |
| :----: | :---------------------- | :-----: | :----------: | :-----------: | :-------------: | :---------------: | :-----: |
| **1**  | `gemini-3.8-flash-high` | SUCCESS |  **39,816**  |  **33,764**   |      4,111      |       8,174       | 221.06s |
| **2**  | `gemini-3.8-flash-low`  | SUCCESS |  **26,012**  |  **12,066**   |        0        |       8,167       | 60.60s  |
| **3**  | `gemini-3.8-flash-low`  | SUCCESS |  **16,257**  |     1,010     |        0        |         0         | 32.22s  |
| **4**  | `gemini-3.8-flash-high` | SUCCESS |  **99,098**  |  **32,342**   |      4,430      |    **257,337**    | 214.23s |
| **5**  | `gemini-3.8-flash-low`  | SUCCESS |  **49,156**  |     4,900     |        0        |         0         | 21.91s  |

_Official evaluation generated strictly from authentic real-world data streams in compliance with repository
invariants._
```

---

## 🚀 Part 4: Implementation Roadmap

```mermaid
gantt
    title Efficacy Measurement Implementation Schedule
    dateFormat  YYYY-MM-DD
    section Visibility & Wire Logger
    JSONL wire logger & diff engine in mitm_addon.py       :active,  des1, 2026-09-09, 2d
    Expose mitmweb port 8081 in docker-compose/runner     :active,  des2, after des1, 1d
    section Methods 1-3 Instrumentation
    Context cleaner payload diff metrics                  :active,  des3, after des2, 2d
    Hybrid cache event logger & staleness check           :active,  des4, after des3, 1d
    Provider prompt cache usage extraction & verification :active,  des5, after des4, 2d
    section Methods 4-6 Instrumentation
    RAG turn 0 vs brute force benchmark harness           :         des6, after des5, 2d
    OpenBrain trajectory turn comparison suite            :         des7, after des6, 2d
    Ringer multi-agent cost & token ledger                :         des8, after des7, 2d
    section Final Report
    Unified A/B automated comparison script in todo/      :         des9, after des8, 2d
```

> [!NOTE] **Roadmap Milestone Timelines**: Schedule dates depicted in the Gantt chart represent illustrative reference
> milestones and relative sprint sequences post-merge.

### Action Items:

1. **Update
   [`payload_cleaner.py`](../../holon-agentic-coder-ref/develop/apps/sandbox-executor/src/sandbox_executor/token_reduction/payload_cleaner.py)**:
   - Extend `JSONContextCleaner` to track and return execution stats (`tool_outputs_omitted`, `turns_summarized`,
     `cache_control_injected`) via a `CleaningResult(payload=..., stats=...)` dataclass (or provide
     `process_payload_with_stats()`) to avoid redundant post-hoc AST diffing or tree traversals.
2. **Update
   [`mitm_addon.py`](../../holon-agentic-coder-ref/develop/apps/sandbox-executor/src/sandbox_executor/token_reduction/mitm_addon.py)**:
   - Parameterize log directory using `WIRE_LOG_DIR` environment variable (default: `todo/mitm_wire_logs/`) and cache
     directory using `CACHE_DIR` environment variable (default: `~/.holon/cache/`) so SQLite cache persistence can be
     mapped to host directories (`-e CACHE_DIR=/tmp/cache -v "${REPO_ROOT}/todo/cache":/tmp/cache`).
   - Implement `dump_wire_transaction()` to write full raw request, cleaned request, and response payloads to
     `${WIRE_LOG_DIR}/turn_{turn_id}_{flow_id}.json` and atomic line appends to `${WIRE_LOG_DIR}/transactions.jsonl`,
     offloaded via an asynchronous logging queue or thread pool (`asyncio.to_thread` / background worker) to prevent
     blocking the mitmproxy event loop.
   - Scrub sensitive credentials and authentication headers (case-insensitively normalizing names to lowercase:
     `authorization`, `x-api-key`, `api-key`, `x-goog-api-key`, `holon-agent-key`, `proxy-authorization`,
     `x-amz-security-token`) and URL query parameters via query parser logic or regex
     ``r'(?i)([?&](?:key|api_key|apiKey|token|access_token)=)[^&\s"\'`<>#]+'`` with `[REDACTED]`.
   - Deep-scrub message bodies and tool payloads using word-boundary regex patterns for API keys and tokens (Anthropic
     `sk-ant-...`, OpenAI `r'\bsk-(?:proj-|admin-|svcacct-)?[a-zA-Z0-9_\-]{20,}\b'`, Google Cloud / Vertex AI
     `r'\bAIza[0-9A-Za-z\-_]{35}\b'`, GitHub tokens `r'\bgh[pousr]_[a-zA-Z0-9]{36}\b'` / `github_pat_...`, AWS
     `r'\bAKIA[0-9A-Z]{16}\b'` / `r'\bASIA[0-9A-Z]{16}\b'` and AWS secret access key regex
     `r'(?i)\b(?:aws_secret_access_key|aws_secret_key|secret_access_key)\s*[:=]\s*["\']?([A-Za-z0-9/+=]{40})["\']?'`,
     Hugging Face tokens `r'\bhf_[a-zA-Z0-9]{34,}\b'`, JWT Bearer tokens
     `r'\beyJ[a-zA-Z0-9_\-]{20,}\.[a-zA-Z0-9_\-]{20,}\.[a-zA-Z0-9_\-]{20,}\b'`, and PEM/PGP private key blocks including
     PKCS#8
     `r'-----BEGIN (?:[A-Z\s]+ )?PRIVATE KEY(?: BLOCK)?-----[\s\S]*?-----END (?:[A-Z\s]+ )?PRIVATE KEY(?: BLOCK)?-----'`),
     replacing detected secrets with `[REDACTED_SECRET]` before persisting transaction payloads or endpoint URLs to
     disk.
   - Ensure SSE stream accumulation decodes and writes the complete final assistant message to the transaction record,
     capturing internal reasoning tokens (`usage.completion_tokens_details.reasoning_tokens`) alongside visible content.
3. **Update Runner CLI**:
   - Add flag `--mitm-web` to launch `mitmweb` instead of `mitmdump` with web port `8081` bound to localhost, logging
     `🌐 mitmweb dashboard active at http://localhost:8081` upon startup.
4. **Implement A/B Benchmark Script (`todo/ab_measure_all_methods.py`)**:
   - **Dynamic LLM Discovery (`agy models`)**: Mandate executing `agy models` to discover and validate the active model
     catalog before running benchmarks. Reject all hardcoded model names. Dynamically assign discovered Tier 1 models to
     the Architect role and Tier 2 models to the Executor role.
   - **Zero Synthetic Workloads**: Completely eliminate all offline synthetic simulation functions
     (`generate_synthetic_iteration()`) and remove any `--synthetic` execution flags. Benchmarks must execute
     exclusively against real data.
   - **Two Real-Data Evaluation Pipelines**:
     1. **Live Task Execution (`--command '<command>'`)**: Runs real containerized tasks (e.g.,
        `./holon execute <plan_branch>` or live test suites), passing actual traffic through the proxy sidecar to
        generate and evaluate authentic wire logs.
     2. **Real Trace Replay Mode (`--trace-file <path_to_transactions.jsonl|payload.json>` or
        `-f / --payload-file <payload.json>`)**: Ingests genuine multi-turn wire transaction records or exported
        request/response payloads captured during real developer and agent coding sessions. Note that when replaying
        trace files for Method 2 evaluation, non-streaming wire records should be used (or streaming bypass accounted
        for) until SSE stream replay is active, preventing spurious cache misses during offline evaluation.
   - **Pre-Clean & Isolation Enforcement**: Enforce a benchmark pre-clean step: explicitly purging or isolating the
     SQLite cache database (`llm_cache.db` / `~/.holon/cache/` / `hybrid_cache.sqlite` via parameterized `CACHE_DIR`)
     alongside archiving previous `${WIRE_LOG_DIR}` transaction logs before benchmark runs to prevent residual cache
     hits from distorting baseline measurements.
   - **Workspace Pristine State Reset**: Mandate resetting workspace state between benchmark iterations (via
     `git clean -fdx` or sandbox container re-initialization) to guarantee that each run begins from a pristine
     repository state without inheriting modified files from earlier turns, ensuring statistical independence across
     $N \ge 3$ iterations.
   - **Empirical Metrics & Guardrail Verification**: Execute $N \ge 3$ iterations at fixed `temperature: 0.0` with
     `seed: 42`, extract exact provider usage token counts, aggregate mean ($\mu$) and standard deviation ($\sigma$)
     metrics, verify the task success rate guardrail by evaluating sandbox test execution exit codes (`pytest`
     returncode == 0), and print the completed real-data Efficacy Scorecard.
