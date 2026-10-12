# Plan for I-1791726197-cache-concurrency-and-sse-test-suite

- **Plan ID:** P-1791726209-antigravity-agent-gemini-3.8-flash-medium}
- **Parent Intent ID:** NONE
- **Agent:** antigravity-agent (version: 1.1.22)
- **Created At:** 2026-10-11T13:43:29.326Z

## Planner Autonomy Summary

- **Intent handling:** ACCEPT_AS_IS
- **Reframed intent (if applicable):** NONE
- **Exploration stance:** exploit with targeted empirical verification of SQLite WAL concurrency pragmas, token shingle
  indexing, batched TTL pruning mechanics, mitmproxy addon lifecycle hooks, multi-provider SSE streaming chunk
  reassembly, and code coverage boundaries.
- **Safety priority level:** standard
- **Priority Justification:** This plan addresses concurrency hardening, database performance, and unit test expansion
  across `hybrid_cache.py` (Bean 0072) and `mitm_addon.py` (Bean 0074). The objectives do not alter sensitive PKI
  cryptographic secrets or container security models, but require strict adherence to hermetic test isolation, zero
  unstaged regressions, and zero mock data benchmarking invariants.

## Exploration

- **Proportion of steps that are exploratory:** 0.00
- **Justification:** The technical requirements across Beans 0072 and 0074 are fully specified, concrete, and
  unambiguous. All necessary primitives (SQLite WAL pragmas, shingle schemas, TTL batching algorithms, mitmproxy event
  hook protocols, SSE parsing routines, and credential scrubbers) are established within the codebase. Execution focuses
  strictly on deterministic implementation verification, test authoring, and coverage expansion.

## Overall Plan Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.96  |
| entropy_pred        | 0.4   |
| impact_pred         | 92.0  |
| cost_pred           | 4.0   |
| learning_value_pred | 3.5   |
| ev_pred             | 85.95 |

### Strategy Rationale

The overall plan metrics are computed directly from individual step evaluations and the config-driven Expected Value
formula:

- **p_success_pred**: 0.96. Governed by the bottleneck step (Step 3: 0.96), where complex mitmproxy event flow
  lifecycles (`server_connect`, `request`, `responseheaders`, `response`, `_dump_flow_transaction`) require
  comprehensive mocking and event reconstruction.
- **entropy_pred**: 0.4. Represents the maximum single-step risk profile (Step 3: 0.4). The cumulative predicted entropy
  across all six steps is 1.5 (`0.2 + 0.3 + 0.4 + 0.3 + 0.2 + 0.1 = 1.5`), comfortably below the allocated entropy
  budget of 15.0.
- **impact_pred**: 92.0. Resolves Beans 0072 and 0074 by hardening database concurrency against lock exhaustion,
  eliminating write amplification during TTL eviction, optimizing semantic search with token shingles, and expanding
  `src/holon_coherence/mitm_addon.py` test coverage from 57% to well beyond 85%.
- **cost_pred**: 4.0. Computed as the direct sum of step execution costs (`0.5 + 0.7 + 1.0 + 0.8 + 0.6 + 0.4 = 4.0`).
- **learning_value_pred**: 3.5. Establishes robust test fixtures and reusable patterns for mitmproxy hook simulation,
  SSE chunk stream reassembly, and high-concurrency SQLite WAL testing in Python 3.13.
- **ev_pred**: 85.95. Derived using the physics-driven Expected Value formula:
  `EV = P(success) * Impact + mu * LearningValue - lambda * Delta_S_intent - Cost`. With system constants `lambda = 0.3`
  and `mu = 0.5` loaded from `holon-config/metrics/ev_config.json`:
  `EV = 0.96 * 92.0 + 0.5 * 3.5 - 0.3 * 0.4 - 4.0 = 88.32 + 1.75 - 0.12 - 4.0 = 85.95`.

## Safety & Constraint Alignment

- **Key world ruleset constraints that affect this plan:**
  - `holon-config/world/ruleset.md` §1 (Runtime & Environment Specification): Target Python `==3.13.*`, package
    execution managed strictly via `uv run` in the workspace root `.venv`.
  - `holon-config/world/ruleset.md` §2 (Coding Conventions & Standards): PEP 8 adherence, explicit static typing with
    standard library `typing`, docstring retention, and zero Ruff linting/formatting errors.
  - `holon-config/world/ruleset.md` §3 (Testing Constraints): Hermetic test isolation via `uv run pytest`, zero unstaged
    regressions across all 392+ baseline tests, and test-driven verification for all added tests.
  - `holon-config/world/constraints.md` §1 (Git Flow & Branch Disciplines): Isolated branches following Holon naming
    conventions (`I-.../P-.../E-.../_`), clean commit boundaries, no direct remote push to `main`.
  - `holon-config/world/constraints.md` §2 (Sandbox Containment): Operations strictly restricted to the workspace root;
    subprocess isolation without persistent shell environment mutations.
  - `holon-config/world/constraints.md` §3 (Ledger Immutability): Zero modifications to historical ledger records in
    `holon-knowledge/ledger/*.jsonl`.
  - `holon-config/world/constraints.md` §4 (Behavioral Invariants): Zero synthetic/mock data for benchmarking (Rule 1:
    evaluations must derive from authentic transactions; unit tests testing code logic use structured mocks), universal
    credentials `HOLON_AGENT_KEY` (Rule 4), and strict repository separation (Rule 5).
- **Potential violations or edge cases:**
  - Database locks or thread deadlocks during SQLite concurrency stress testing if connection handles leak or timeout
    thresholds are insufficient.
  - Inadvertently leaking unredacted test API keys in test fixtures or assertions.
  - Mitmproxy event mocks failing to accurately simulate `mitmproxy.http.HTTPFlow` state transitions (e.g., streaming
    chunks, headers, response status).
  - Test suites hanging on unjoined worker threads or unclosed thread pool executors.
- **Mitigations built into the plan:**
  - Ensure all database connections in `HybridCacheStore` use the context-managed `_connect()` helper with explicit
    `conn.close()` in `finally` blocks and `PRAGMA busy_timeout=5000;`.
  - Isolate cache stress tests to ephemeral `tmp_path` directories with timeouts on thread joins.
  - Use synthetic dummy tokens (`sk-ant-test...`, `[REDACTED]`) exclusively inside unit test assertions.
  - Build hermetic mock flow fixtures conforming to `mitmproxy.http.HTTPFlow` interface conventions with isolated
    headers, content streams, and request/response lifecycles.
  - Explicitly flush and shut down thread pool executors (`flush_wire_logs`, `shutdown_wire_logs`) in test teardowns.
- **Residual risk accepted (and why):**
  - High concurrency stress tests with 8+ worker threads depend on OS thread scheduling; robust retry timeouts and
    deterministic bounds are set to avoid test flakiness.
- **Allocated Entropy Budget:** 15.0
- **Predicted Plan Entropy:** 1.5
- **Budget Compliance:** The cumulative predicted plan entropy of 1.5 remains well within the allocated budget limit of
  15.0.

## Plan Description & Strategy

This implementation is divided into 6 sequential steps:

1. **Step 1: Audit and Verify Hybrid Cache WAL Concurrency, Token Shingles, and TTL Eviction (Bean 0072)**: Verify
   SQLite WAL mode, `busy_timeout=5000`, `synchronous=NORMAL`, precomputed token shingles, candidate limit scanning, and
   batched time-gated TTL eviction in `src/holon_coherence/hybrid_cache.py`.
2. **Step 2: Expand Concurrency Stress Tests and Edge-Case Assertions in `tests/test_hybrid_cache.py` (Bean 0072)**: Add
   intensive multi-threaded read/write stress tests, verify lock contention resilience under rapid interleaved
   operations, validate TTL boundary conditions, and test database schema upgrade resilience.
3. **Step 3: Implement Lifecycle Hook Unit Tests for `MitmproxyAddon` in `tests/test_mitm_addon_sse.py` (Bean 0074)**:
   Add comprehensive unit tests covering all mitmproxy addon lifecycle hooks (`server_connect`, `request`,
   `responseheaders`, `response`, `_dump_flow_transaction`) for both streaming and non-streaming requests.
4. **Step 4: Expand Provider Streaming Chunk Reassembly, Token Estimation, and Credential Scrubbing Tests (Bean 0074)**:
   Add unit tests for OpenAI, Anthropic, and Gemini SSE reassembly edge cases, fragmented tool calls, reasoning content
   extraction, fallback token heuristics, and recursive dictionary/list payload scrubbing (`scrub_payload`).
5. **Step 5: Measure and Verify >85% Code Coverage for `mitm_addon.py` and Full Suite Integrity**: Run test coverage
   analysis ensuring `src/holon_coherence/mitm_addon.py` exceeds 85% line coverage, and execute the complete test suite
   to verify 100% pass rate with zero regressions.
6. **Step 6: Code Quality, Linting, Formatting, and Workspace Hygiene Verification**: Execute `uv run ruff check .` and
   `uv run ruff format --check .`, verify all documentation and typing standards, and ensure clean git status before
   completion.

---

## Step 1: Audit and Verify Hybrid Cache WAL Concurrency, Token Shingles, and TTL Eviction (Bean 0072)

- **Sub‑intent recommendation:** NO
- **Reasoning:** Verification and targeted hardening of `src/holon_coherence/hybrid_cache.py` directly within the core
  module.
- **Step Type:** IMPLEMENT
- **Exploration level:** EXPLOIT

### Intent & Git Integration

- **Step Intent:** Verify and guarantee that `HybridCacheStore` correctly sets SQLite WAL mode, `busy_timeout=5000`,
  `synchronous=NORMAL`, precomputed token shingles (`user_tokens`, `system_hash`), and batched time-gated TTL pruning.
- **Git branch:**
  `I-1791726197-cache-concurrency-and-sse-test-suite/P-1791726209-antigravity-agent-gemini-3.8-flash-medium/E-cache-concurrency-verify/_`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- Inspect `src/holon_coherence/hybrid_cache.py`:
  - Verify that `_connect()` sets `PRAGMA busy_timeout=5000;` and `PRAGMA synchronous=NORMAL;` on every opened
    connection.
  - Verify that `_init_db()` executes `PRAGMA journal_mode=WAL;` and creates indexes `idx_prompt_cache_provider_created`
    and `idx_prompt_cache_provider_system_created`.
  - Confirm table migration adds `user_tokens TEXT` and `system_hash TEXT` if they do not exist.
  - Confirm that `_freshness_clause()` correctly excludes expired entries in both exact prefix and semantic queries even
    before a prune sweep.
  - Confirm that `_prune_expired()` is gated by `prune_interval_seconds` and deletes in bounded batches defined by
    `prune_batch_size`.
  - Ensure `_normalized_payload`, `_tokenize`, and `_system_hash` are robust against malformed or missing payload
    fields.

### Dependencies & Criticality

- **Depends on:** NONE
- **Is Bottleneck:** NO

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §1 & §2 (Python 3.13, PEP 8, static typing, docstrings).
- **Potential failure modes for this step:** Misconfigured pragma statements or schema migration syntax errors on older
  SQLite database formats.
- **Guardrails and early‑abort checks:** Validate with isolated temporary SQLite databases across standard database
  operations.

### Success & Discard Criteria

- **Success:** `hybrid_cache.py` conforms strictly to all Bean 0072 requirements with verified WAL pragmas, shingle
  indexing, and batched TTL pruning.
- **Discard:** Discard if SQLite pragmas cause compatibility issues or unhandled exceptions.

### Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.99  |
| entropy_pred        | 0.2   |
| impact_pred         | 85.0  |
| cost_pred           | 0.5   |
| learning_value_pred | 1.5   |
| ev_pred             | 84.34 |

### Step Metrics Rationale

- High `p_success_pred` (0.99) and low entropy (0.2) as the underlying logic in `hybrid_cache.py` is mature and requires
  targeted verification.
- Derivation: `EV = 0.99 * 85.0 + 0.5 * 1.5 - 0.3 * 0.2 - 0.5 = 84.15 + 0.75 - 0.06 - 0.5 = 84.34`.

---

## Step 2: Expand Concurrency Stress Tests and Edge-Case Assertions in `tests/test_hybrid_cache.py` (Bean 0072)

- **Sub‑intent recommendation:** NO
- **Reasoning:** Adding robust concurrency stress tests and regression tests in `tests/test_hybrid_cache.py`.
- **Step Type:** TEST
- **Exploration level:** EXPLOIT

### Intent & Git Integration

- **Step Intent:** Verify cache stability under multi-threaded concurrency stress, validate zero lock exhaustion, verify
  immediate connection handle release, and test edge-case TTL sweeps.
- **Git branch:**
  `I-1791726197-cache-concurrency-and-sse-test-suite/P-1791726209-antigravity-agent-gemini-3.8-flash-medium/E-cache-stress-tests/_`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- In `tests/test_hybrid_cache.py`:
  - Expand `test_concurrent_writers_and_readers_do_not_error` with high-throughput interleaved operations:
    - Increase worker threads to 12 concurrent workers executing interleaved `put()`, `get()`, and `_prune_expired()`
      operations across different providers (`openai`, `anthropic`, `gemini`).
    - Verify that no `sqlite3.OperationalError: database is locked` occurs under heavy concurrent contention.
    - Assert that all committed rows are retrievable or accounted for.
  - Add `test_sqlite_pragmas_applied_on_every_connection`:
    - Connect via store context manager and query `PRAGMA busy_timeout;`, `PRAGMA journal_mode;`, and
      `PRAGMA synchronous;`.
    - Assert `busy_timeout` is 5000, `journal_mode` is `wal`, and `synchronous` is 1 (`NORMAL`).
  - Add `test_concurrent_prune_and_read_write_interleaving`:
    - Run background pruning threads concurrently with active readers and writers to verify that batched deletions do
      not block read transactions.
  - Add `test_malformed_payload_normalization_does_not_corrupt_cache`:
    - Test unparseable JSON strings, missing messages/system prompts, and non-dict payload elements.
    - Verify fallback to raw payload and graceful semantic miss without error.
  - Execute tests via `uv run pytest tests/test_hybrid_cache.py`.

### Dependencies & Criticality

- **Depends on:** Step 1
- **Is Bottleneck:** NO

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §3 (Hermetic test isolation, zero regressions).
- **Potential failure modes for this step:** Thread deadlocks or tests hanging indefinitely if threads are unjoined.
- **Guardrails and early‑abort checks:** Enforce explicit join timeouts (e.g. `thread.join(timeout=5.0)`) and assert
  `thread.is_alive() is False`.

### Success & Discard Criteria

- **Success:** All new and existing tests in `tests/test_hybrid_cache.py` pass cleanly within seconds with zero
  concurrency errors.
- **Discard:** Discard if tests exhibit flakiness, deadlocks, or lock timeout errors.

### Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.98  |
| entropy_pred        | 0.3   |
| impact_pred         | 88.0  |
| cost_pred           | 0.7   |
| learning_value_pred | 2.0   |
| ev_pred             | 86.45 |

### Step Metrics Rationale

- High `p_success_pred` (0.98) due to deterministic thread pool assertions and existing helper foundations in
  `test_hybrid_cache.py`.
- Derivation: `EV = 0.98 * 88.0 + 0.5 * 2.0 - 0.3 * 0.3 - 0.7 = 86.24 + 1.00 - 0.09 - 0.7 = 86.45`.

---

## Step 3: Implement Lifecycle Hook Unit Tests for `MitmproxyAddon` in `tests/test_mitm_addon_sse.py` (Bean 0074)

- **Sub‑intent recommendation:** NO
- **Reasoning:** Adding unit tests for core mitmproxy addon lifecycle methods in `tests/test_mitm_addon_sse.py`.
- **Step Type:** TEST
- **Exploration level:** EXPLOIT

### Intent & Git Integration

- **Step Intent:** Provide exhaustive test coverage for `MitmproxyAddon` lifecycle hooks: `server_connect`, `request`,
  `responseheaders`, `response`, and `_dump_flow_transaction`.
- **Git branch:**
  `I-1791726197-cache-concurrency-and-sse-test-suite/P-1791726209-antigravity-agent-gemini-3.8-flash-medium/E-mitm-lifecycle-tests/_`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- In `tests/test_mitm_addon_sse.py`:
  - Add test class `TestMitmAddonLifecycle`:
    - Create lightweight mock flow classes mimicking `mitmproxy.http.HTTPFlow` with `request`, `response`, `headers`,
      and timing attributes.
    - Test `server_connect`:
      - Test container mode with host-local target (e.g. `localhost:11434`): assert address rewritten to gateway IP.
      - Test proxy own port safety check: assert connection to proxy's own listen port is blocked with `server.error`
        set.
      - Test non-container execution: assert no connection rewriting occurs.
      - Test gateway resolution failure: assert warning logged only once (`self._warned_gateway`).
    - Test `request`:
      - Test non-JSON request body: assert provider detected from URL and unparseable body handled gracefully without
        crashing.
      - Test passive monitoring mode (`is_passive_monitoring` True): assert payload cleaning and caching are bypassed
        while preserving raw request data.
      - Test cache hit: assert flow response synthesized with status 200, telemetry headers injected
        (`X-Holon-Cache-Hit-Rate`, `X-Holon-TTFT-Ms`), telemetry logged, and transaction dumped.
      - Test cache miss: assert request body cleaned, cleaner metrics logged, and flow forwarded.
    - Test `responseheaders`:
      - Test `text/event-stream` content type: assert `flow.sse_chunks` initialized, stream wrapped with
        `sse_stream_wrapper`, and `first_chunk_time` recorded on first chunk.
      - Test non-SSE response: assert stream remains unwrapped.
      - Test SSE buffer truncation at `_MAX_SSE_BUFFER_BYTES` limit.
    - Test `response`:
      - Test HTTP 200 SSE streaming response: assert chunks reassembled, token counts extracted, timing metrics (TTFB,
        TTFT, prefill TPS, decode time, output TPS) calculated, headers injected, and wire transaction dumped.
      - Test HTTP 200 non-streaming JSON response: assert response parsed, cached in store, and wire transaction dumped.
      - Test non-200 HTTP error responses (e.g. 429, 500): assert warning logged, request/response logged without
        caching, and wire transaction dumped.
      - Test unknown provider or cached flow early return.
    - Test `_dump_flow_transaction`:
      - Test transaction record structure: assert `turn_id`, `flow_id`, `agent_id`, `agent_role`, `endpoint`, `delta`,
        and telemetry timings match expected format.
      - Test wire logging disabled (`is_wire_logging_enabled` False): assert no dump is scheduled.
    - Test `done`: assert `shutdown_wire_logs` is invoked.
  - Execute tests via `uv run pytest tests/test_mitm_addon_sse.py -k TestMitmAddonLifecycle`.

### Dependencies & Criticality

- **Depends on:** Step 1 & Step 2
- **Is Bottleneck:** YES (Major driver of the >85% code coverage milestone)

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §3 (Hermetic test isolation, mocks must not make real network
  connections).
- **Potential failure modes for this step:** Incomplete mock flow attributes causing unexpected `AttributeError` in hook
  callbacks.
- **Guardrails and early‑abort checks:** Use structured mock flow helper classes with default fallback attributes
  mirroring mitmproxy specs.

### Success & Discard Criteria

- **Success:** All lifecycle hooks are thoroughly tested across all branches (streaming, non-streaming, cache hit, cache
  miss, error codes, port loops) and pass cleanly.
- **Discard:** Discard if mocks fail or cause flaky assertions.

### Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.96  |
| entropy_pred        | 0.4   |
| impact_pred         | 92.0  |
| cost_pred           | 1.0   |
| learning_value_pred | 3.0   |
| ev_pred             | 88.70 |

### Step Metrics Rationale

- `p_success_pred` (0.96) reflects the complexity of accurately simulating mitmproxy flows and asynchronous wire log
  execution.
- Derivation: `EV = 0.96 * 92.0 + 0.5 * 3.0 - 0.3 * 0.4 - 1.0 = 88.32 + 1.50 - 0.12 - 1.0 = 88.70`.

---

## Step 4: Expand Provider Streaming Chunk Reassembly, Token Estimation, and Credential Scrubbing Tests (Bean 0074)

- **Sub‑intent recommendation:** NO
- **Reasoning:** Authoring focused unit tests in `tests/test_mitm_addon_sse.py` to test provider parsers, token
  heuristics, and recursive scrubbing.
- **Step Type:** TEST
- **Exploration level:** EXPLOIT

### Intent & Git Integration

- **Step Intent:** Test streaming chunk reassembly across OpenAI, Anthropic, and Gemini, test non-streaming and fallback
  token estimations, test recursive payload credential scrubbing, and test helper utility functions.
- **Git branch:**
  `I-1791726197-cache-concurrency-and-sse-test-suite/P-1791726209-antigravity-agent-gemini-3.8-flash-medium/E-streaming-scrubbing-tests/_`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- In `tests/test_mitm_addon_sse.py`:
  - Add test class `TestProviderSSEReassembly`:
    - Anthropic: test complex mixed streams with thinking deltas, text deltas, signature blocks, and multi-turn tool
      use.
    - OpenAI: test multi-choice responses, legacy completions endpoint format, function calling vs tool calling, and
      fragmented JSON arguments.
    - Gemini: test candidate content parts, citations metadata, safety ratings chunks, and
      `candidates[0].content.parts[0].text` aggregation.
  - Add test class `TestScrubPayload`:
    - Test recursive scrubbing on nested dicts, lists, and primitives.
    - Test secret dict keys (`authorization`, `api_key`, `token`, `secret`, `credentials`, `client_secret`,
      `refresh_token`): assert values masked with `[REDACTED]`.
    - Test string value pattern matching: assert strings containing `sk-...`, `Bearer ...` are redacted.
    - Test depth limit recursion guard (`max_depth=50`): assert protection against circular dictionary references.
  - Add test class `TestTokenEstimationAndFallbacks`:
    - Test `estimate_chars` across deeply nested lists, dictionaries, strings, and non-string types.
    - Test `extract_detailed_token_counts` with missing keys, malformed objects, and invalid integers.
    - Test `derive_turn_id` with various header permutations (`x-holon-turn-id`, message counts, fallback counters).
    - Test wire log worker synchronization functions (`flush_wire_logs`, `shutdown_wire_logs`,
      `_get_wire_log_executor`).
  - Execute tests via `uv run pytest tests/test_mitm_addon_sse.py`.

### Dependencies & Criticality

- **Depends on:** Step 3
- **Is Bottleneck:** NO

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §2 & §3, `holon-config/world/constraints.md` §4 (No synthetic
  benchmark data, authentic test shapes).
- **Potential failure modes for this step:** Circular object references in `scrub_payload` causing recursion depth
  errors.
- **Guardrails and early‑abort checks:** Use recursion depth limit checks already implemented in `scrub_payload`.

### Success & Discard Criteria

- **Success:** All chunk reassembly, token estimation, and payload scrubbing tests pass with 100% assertions satisfied.
- **Discard:** Discard if provider parsers drop tokens or fail to redact sensitive keys.

### Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.97  |
| entropy_pred        | 0.3   |
| impact_pred         | 90.0  |
| cost_pred           | 0.8   |
| learning_value_pred | 2.5   |
| ev_pred             | 87.66 |

### Step Metrics Rationale

- High `p_success_pred` (0.97) as the tests target pure functions and parsers with clear input/output expectations.
- Derivation: `EV = 0.97 * 90.0 + 0.5 * 2.5 - 0.3 * 0.3 - 0.8 = 87.30 + 1.25 - 0.09 - 0.8 = 87.66`.

---

## Step 5: Measure and Verify >85% Code Coverage for `mitm_addon.py` and Full Suite Integrity

- **Sub‑intent recommendation:** NO
- **Reasoning:** Verification of line coverage targets and total test suite integrity.
- **Step Type:** VERIFY
- **Exploration level:** EXPLOIT

### Intent & Git Integration

- **Step Intent:** Verify that line test coverage for `src/holon_coherence/mitm_addon.py` strictly exceeds 85%, and
  ensure all tests across the repository pass without regressions.
- **Git branch:**
  `I-1791726197-cache-concurrency-and-sse-test-suite/P-1791726209-antigravity-agent-gemini-3.8-flash-medium/E-coverage-verification/_`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- Run coverage measurement using `uv run --with coverage coverage run -m pytest tests/test_mitm_addon_sse.py`.
- Run `uv run --with coverage coverage report --include="src/holon_coherence/mitm_addon.py"`.
- Verify that line coverage for `src/holon_coherence/mitm_addon.py` is >= 85%.
  - If coverage is below 85%, inspect remaining uncovered lines with `coverage report -m` and add targeted unit tests in
    `tests/test_mitm_addon_sse.py` to cover remaining uncovered branches.
- Run complete test suite: `uv run pytest`.
- Verify that all 392+ baseline tests plus all newly added tests pass cleanly (target: >450 passing tests, 0 failures, 0
  errors).

### Dependencies & Criticality

- **Depends on:** Step 1 through Step 4
- **Is Bottleneck:** YES (Milestone threshold validation)

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §3 (Hermetic test isolation, zero regressions).
- **Potential failure modes for this step:** Coverage falling short of 85% due to missed error handling blocks or
  unexercised branches.
- **Guardrails and early‑abort checks:** Inspect missing line ranges and author targeted unit tests for unhit branches.

### Success & Discard Criteria

- **Success:** Coverage of `src/holon_coherence/mitm_addon.py` exceeds 85% and all unit tests in the entire repository
  pass with zero errors.
- **Discard:** Discard if coverage is below 85% or any pre-existing test regresses.

### Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.98  |
| entropy_pred        | 0.2   |
| impact_pred         | 94.0  |
| cost_pred           | 0.6   |
| learning_value_pred | 2.0   |
| ev_pred             | 92.46 |

### Step Metrics Rationale

- High `p_success_pred` (0.98) because previous steps systematically target every lifecycle method and utility function.
- Derivation: `EV = 0.98 * 94.0 + 0.5 * 2.0 - 0.3 * 0.2 - 0.6 = 92.12 + 1.00 - 0.06 - 0.6 = 92.46`.

---

## Step 6: Code Quality, Linting, Formatting, and Workspace Hygiene Verification

- **Sub‑intent recommendation:** NO
- **Reasoning:** Standard final pass validating linters, formatters, and git workspace cleanliness.
- **Step Type:** VERIFY
- **Exploration level:** EXPLOIT

### Intent & Git Integration

- **Step Intent:** Verify PEP 8 compliance, Ruff linting, Ruff formatting, and working tree cleanliness.
- **Git branch:**
  `I-1791726197-cache-concurrency-and-sse-test-suite/P-1791726209-antigravity-agent-gemini-3.8-flash-medium/E-lint-and-hygiene/_`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- Execute code linting: `uv run ruff check .` and ensure 0 errors and 0 warnings.
- Execute code format check: `uv run ruff format --check .` and ensure all files are properly formatted.
- If formatting or lint issues exist, run `uv run ruff check --fix .` and `uv run ruff format .`.
- Run `git status` to verify no untracked scratch files, temporary databases, or leftover caches exist.
- Verify that historical ledger files (`holon-knowledge/ledger/*.jsonl`) remain unaltered.

### Dependencies & Criticality

- **Depends on:** Step 1 through Step 5
- **Is Bottleneck:** NO

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §2 (PEP 8, Ruff zero errors), `holon-config/world/constraints.md`
  §3 (Ledger immutability).
- **Potential failure modes for this step:** Unused test imports or formatting violations introduced during test
  authoring.
- **Guardrails and early‑abort checks:** Automatically format and fix via Ruff before completing step.

### Success & Discard Criteria

- **Success:** Ruff reports all checks pass cleanly, all tests pass, and working tree is in pristine state.
- **Discard:** Discard if linting errors remain unresolved.

### Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.99  |
| entropy_pred        | 0.1   |
| impact_pred         | 88.0  |
| cost_pred           | 0.4   |
| learning_value_pred | 1.0   |
| ev_pred             | 87.19 |

### Step Metrics Rationale

- High `p_success_pred` (0.99) and minimal entropy (0.1) as this is a deterministic validation and hygiene check.
- Derivation: `EV = 0.99 * 88.0 + 0.5 * 1.0 - 0.3 * 0.1 - 0.4 = 87.12 + 0.50 - 0.03 - 0.4 = 87.19`.
