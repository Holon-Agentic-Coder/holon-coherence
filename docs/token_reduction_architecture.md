# AI Agent Token Reduction System Architecture

This document describes the design, data flow, and implementation details of the multi-tiered token reduction
architecture.

---

## 🗺️ System Architecture Overview

The system operates as an interception layer between the containerized AI agent running inside the sandbox and the
external LLM API endpoints.

```mermaid
graph TD
    subgraph Sandbox Container [Docker Sandbox]
        Agent[AI Agent / sandbox_executor]
    end

    subgraph Host / Interceptor Network
        Proxy[MITM Interceptor Proxy]
        Cleaner[Context Cleaner & Deduplicator]
        Cache[SQLite Hybrid Cache Store]
        RAG[AST RAG Codebase Indexer]
    end

    subgraph LLM Providers
        Anthropic[Anthropic API]
        OpenAI[OpenAI API]
    end

    Agent -->|HTTPS Traffic| Proxy
    Proxy --> Cleaner
    Cleaner --> Cache
    Cache -->|Cache Hit| Proxy
    Cache -->|Cache Miss| Anthropic
    Cache -->|Cache Miss| OpenAI
    RAG -.->|Bootstrap Context| Agent
```

---

## 🔍 Detail by Phase

### Phase 1: MITM Interceptor & SSL/TLS Trust

- **Root CA Generation**: Generates a self-signed Root Certificate Authority (`holon-root-ca.crt`).
- **Trust Injection**: The host CLI automatically mounts the generated Root CA into `/usr/local/share/ca-certificates/`
  inside the target container and configures:
  - `NODE_EXTRA_CA_CERTS` (Node.js/Prettier/TypeScript tools)
  - `REQUESTS_CA_BUNDLE` & `SSL_CERT_FILE` (Python library requests)
  - `CURL_CA_BUNDLE` (cURL command line calls)
- **Proxy Interception**: Outbound requests are routed via `mitmproxy` using a custom scripting addon (`mitm_addon.py`).

---

### Phase 2: JSON Payload Cleaner & Prompt Cache Breakpoints

- **Tool Result Deduplication**: Computes SHA-256 hashes on returned tool output payloads (`tool_result.content`).
  Identical older turns (>100 chars) are replaced with
  `[Omitted: Tool result content is identical to Turn N (call_id)]`. Because hashing evaluates the output text rather
  than the command string, modified files (`cat`) and mutated directory listings (`ls`) produce new hashes and remain
  preserved in full. Recent turns (`_RECENT_TURNS_TO_KEEP = 6`) are never deduplicated to safeguard active working
  context.
- **Anthropic Cache Breakpoints**: Automatically injects `"cache_control": {"type": "ephemeral"}` onto the system prompt
  block, tools definitions block, and the most recent user turn (up to 4 breakpoints total) to trigger cheaper cached
  pricing.
- **Context Summarization**: When the history turn count exceeds the threshold limit, the intermediate turns are
  summarized into a concise summary block, freeing up context space.

---

### Phase 3: Hybrid & Semantic Cache Store

- **Key Normalization**: Before caching, JSON requests are normalized by stripping transient data patterns like UUIDs,
  timestamps, and randomized task IDs.
- **Exact Matching**: Checks the normalized prompt representation in the SQLite database (`llm_cache.db`) for identical
  prompt keys.
- **Semantic Similarity Matching**: If exact match misses, the store executes a token-overlap similarity check (Jaccard
  Index) against all stored entries. Matches above the configured threshold (e.g., `0.85`) are returned as a cache hit,
  handling slight variations in agent phrasing:

  $$\text{Jaccard Similarity}(A, B) = \frac{|A \cap B|}{|A \cup B|}$$

- **Tuple Return & Operational Short-Circuiting**: `MITMProxyInterceptor.intercept_request()` returns a 2-element tuple
  `(cleaned_request_json, cached_response_or_none)`:
  1. **First Element (`cleaned_request_json`)**: The cleaned request body (with deduplicated tool outputs and cache
     control breakpoints).
  2. **Second Element (`cached_response_or_none`)**: The pre-cached LLM response payload served from the local SQLite
     database (`llm_cache.db`), or `None` on a cache miss.

  In `MitmproxyAddon.request(flow)`, when `cached_resp` is present, the proxy short-circuits the HTTP request directly
  on cache hits without sending outbound traffic to LLM provider endpoints:

  ```python
  cleaned_data, cached_resp = self.interceptor.intercept_request(url, data)
  flow.request.set_text(json.dumps(cleaned_data))

  if cached_resp:
      # Serve cached response locally and skip upstream network call
      headers = {"Content-Type": "application/json"}
      flow.response = Response.make(200, json.dumps(cached_resp).encode("utf-8"), headers)
  ```

---

### Phase 4: Codebase RAG & Ringer Delegation

#### AST & BM25 Codebase indexing (RAG)

- Extracts function, class, and class method signatures to build a lightweight symbol directory.
- Limits initial agent prompt injection by providing only relevant symbol summaries rather than printing entire code
  structures.

#### Ringer Orchestrator (Architect/Executor Pattern)

- A high-capability Architect model (e.g. Claude 3.5 Sonnet) designs execution tasks.
- Specific terminal commands, linters, or small edits are delegated to a cheaper, faster Executor model (e.g. Gemini 3.5
  Flash) via the CLI.
- Execution output is summarized and compressed before being returned to the Architect, preventing context window bloat.

---

## 🛡️ Code Quality & Complexity Gate

To ensure sustainable codebase health, maintainability, and architectural coherence, `holon-coherence` enforces automated static complexity gates aligned with the broader Holon ecosystem. These gates ensure that incoming modifications remain modular, readable, and testable without regressing into deeply nested procedural routines.

### Static Analysis Complexity Thresholds

Static complexity metrics are evaluated via Ruff's McCabe (`C901`) and Pylint structural complexity (`PLR0911`–`PLR0915`) rules configured directly within `pyproject.toml`:

| Rule Code | Analysis Dimension           | Configured Section        | Numerical Ceiling     | Rationale & Impact                                                                             |
| :-------- | :--------------------------- | :------------------------ | :-------------------- | :--------------------------------------------------------------------------------------------- |
| `C901`    | McCabe Cyclomatic Complexity | `[tool.ruff.lint.mccabe]` | `max-complexity = 10` | Restricts independent execution paths per function to ensure straightforward unit testing.     |
| `PLR0911` | Maximum Return Statements    | `[tool.ruff.lint.pylint]` | `max-returns = 6`     | Limits excessive exit branches, encouraging clean control flow consolidation.                  |
| `PLR0912` | Maximum Branching Paths      | `[tool.ruff.lint.pylint]` | `max-branches = 12`   | Prevents deeply nested conditional logic (`if`/`elif`/`match`/`try`) within a single scope.    |
| `PLR0913` | Maximum Function Arguments   | `[tool.ruff.lint.pylint]` | `max-args = 5`        | Encourages parameter grouping into typed structures, dataclasses, or configuration namespaces. |
| `PLR0915` | Maximum Statements           | `[tool.ruff.lint.pylint]` | `max-statements = 50` | Prevents monolithic function bodies by requiring decomposed helper procedures.                 |

### Inline `# noqa` Baseline Policy

Legacy functions created prior to the introduction of these complexity constraints are grandfathered strictly using targeted, inline `# noqa` annotations placed directly on their function definition (`def`) lines:

```python
def legacy_processing_routine(payload: dict[str, Any]) -> dict[str, Any]:  # noqa: C901, PLR0912, PLR0915
    ...
```

The baseline policy adheres to three non-negotiable operational invariants:

1. **No Blanket Suppressions**: Complexity rules must never be bypassed globally via `[tool.ruff.lint].ignore` or on a file level via `[tool.ruff.lint.per-file-ignores]`. Suppressions must remain localised and explicitly visible at the exact point of definition.
2. **Zero Runtime Alterations**: Grandfathering legacy routines preserves exact existing control flow, error handling, and networking behaviour with zero refactoring risk during baseline establishment.
3. **No Legacy Expansion**: New functions or touched methods must comply with the complexity thresholds without introducing new inline suppressions.

### Automated Ratchet Ceiling Governance

To prevent technical debt accumulation and ensure that legacy complexity is monotonically eliminated over time, an automated ratchet ceiling is enforced in `tests/test_complexity_baseline.py`.

The ratchet test programmatically inspects all source files under `src/holon_coherence/`:

- **Inventory & Matching**: Accurately counts every line containing inline complexity suppressions (`C901`, `PLR0911`, `PLR0912`, `PLR0913`, `PLR0915`).
- **Ceiling Enforcement**: Asserts that total suppressions do not exceed `BASELINE_CEILING` (currently 40). Any commit introducing an ungrandfathered complexity violation or additional `# noqa` suppression will fail CI automatically.
- **Monotonic Ratchet Down**: When legacy functions are refactored into smaller, modular sub-routines during standard maintenance, the corresponding `# noqa` tags are removed and `BASELINE_CEILING` is reduced accordingly, permanently locking in the code quality improvement.
