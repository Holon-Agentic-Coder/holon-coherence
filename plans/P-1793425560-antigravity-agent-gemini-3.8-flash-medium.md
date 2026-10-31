# Plan for I-1793425546-coherence-decompose-ab-test-and-metrics-commands

- **Plan ID:** P-1793425560-antigravity-agent-gemini-3.8-flash-medium
- **Parent Intent ID:** NONE
- **Agent:** antigravity-agent (version: 1.4.12)
- **Created At:** 2026-10-31T05:46:01.353Z

---

## Overall Plan Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.98  |
| entropy_pred        | 3.60  |
| impact_pred         | 8.80  |
| cost_pred           | 0.80  |
| learning_value_pred | 2.40  |
| ev_pred             | 7.94  |

---

## Step 1: Create Dedicated A/B Testing Evaluation Domain Module (`src/holon_coherence/ab_testing/evaluation.py`)

### Step Intent & Git Integration

- **Sub-intent recommendation:** none (monolithic execution within intent scope)
- **Reasoning:** Establish the domain module `src/holon_coherence/ab_testing/evaluation.py` that encapsulates all A/B test run models, trace loading, and differential scoring logic (`evaluate_offline_ab_run`, `evaluate_runs`). Decompose monolithic routines into granular, cohesive helper functions that strictly adhere to Bean 0186 complexity thresholds ($C901 \le 10$, $PLR0911 \le 6$, $PLR0912 \le 12$, $PLR0913 \le 5$, $PLR0915 \le 50$) with zero `# noqa` suppressions.
- **Step type:** implementation
- **Exploration level:** 0.05
- **Git branch:** `I-1793425546-coherence-decompose-ab-test-and-metrics-commands`

### Implementation Details

1. **Package Initialization**:
   - Create package directory `src/holon_coherence/ab_testing/`.
   - Create `src/holon_coherence/ab_testing/__init__.py` exposing domain classes and evaluator functions.

2. **Domain Dataclasses & Data Structures (`evaluation.py`)**:
   - Move `ABRunConfig`, `ABTurnMetrics`, and `ABComparisonScorecard` into `src/holon_coherence/ab_testing/evaluation.py`.
   - Provide aliases or domain representations (`AbRun`, `AbEvaluation`) aligned with intent acceptance criteria while maintaining 100% backward compatibility for all existing attributes and methods (`to_dict()`, `format_console()`).

3. **Trace Loading Decomposition**:
   - Decompose `load_trace_transactions` into:
     - `_parse_json_array_stream(file_obj, file_path) -> list[dict[str, Any]]`
     - `_parse_jsonl_stream(file_obj, file_path) -> list[dict[str, Any]]`
     - `load_trace_transactions(file_path: str) -> list[dict[str, Any]]`
   - Decompose `load_transactions_from_path` into:
     - `_find_trace_files(dir_path: str) -> list[str]`
     - `_load_trace_directory(dir_path: str) -> list[dict[str, Any]]`
     - `load_transactions_from_path(path: str) -> list[dict[str, Any]]`

4. **Offline Evaluation Decomposition (`evaluate_offline_ab_run`)**:
   - Decompose the 167-line monolithic `evaluate_offline_ab_run` (CC 44) into single-purpose helpers:
     - `_extract_request_payload(tx: dict[str, Any]) -> dict[str, Any] | None`
     - `_extract_baseline_tokens(resp: dict[str, Any], baseline_chars: int) -> int`
     - `_check_semantic_parity(orig_payload: dict[str, Any], opt_payload: dict[str, Any]) -> bool`
     - `_evaluate_single_offline_turn(tx: dict[str, Any], cleaner: JSONContextCleaner, round_num: int, idx: int) -> tuple[ABTurnMetrics, float | None, bool]`
     - `_aggregate_offline_turns(turns: list[ABTurnMetrics], ttft_samples: list[float], rounds: int, fail_under: float | None) -> ABComparisonScorecard`
     - Orchestrator function `evaluate_offline_ab_run` strictly complying with $C901 \le 10$.

5. **Dual-Run Differential Evaluation Decomposition (`evaluate_runs`)**:
   - Decompose the 185-line monolithic `evaluate_runs` (CC 69) into:
     - `_pair_baseline_and_optimized_runs(base_txs: list[dict], opt_txs: list[dict]) -> tuple[list[dict], list[dict]]`
     - `_extract_turn_tokens_and_chars(tx: dict) -> tuple[int, int]`
     - `_extract_recorded_timing(tx: dict) -> tuple[float | None, float | None]`
     - `_evaluate_paired_turn(base_tx: dict, opt_tx: dict, round_num: int, idx: int) -> tuple[ABTurnMetrics, dict[str, Any]]`
     - `_aggregate_scorecard_totals(scorecard: ABComparisonScorecard, turns: list[ABTurnMetrics], samples: dict[str, list[float]]) -> None`
     - Orchestrator function `evaluate_runs` strictly complying with $C901 \le 10$.

### Dependencies & Criticality

- **Dependencies:** None
- **Is bottleneck:** Yes — Establishes the decoupled domain foundation for A/B testing evaluation before CLI handler refactoring.

### Safety & Constraint Considerations

- **Relevant rules:** §2 Coding Conventions & Standards, Bean 0186 Complexity Limits, Rule 1 (Zero Synthetic / Mock Data for Benchmarking).
- **Failure modes:** Subtle token rounding discrepancies or changes to scorecard summary formatting in `to_dict()` and `format_console()`.
- **Guardrails:** Keep all mathematical formulas, fallback heuristics (`chars // 4`), rounding logic, and key names identical to existing implementations.

### Success & Discard Criteria

- **Success:** `src/holon_coherence/ab_testing/evaluation.py` exists, exports all evaluation dataclasses and functions, passes all static complexity checks with 0 `# noqa` suppressions ($C901 \le 10$).
- **Discard:** Discard if any metric computation or dictionary output differs from baseline behavior.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.99  |
| entropy_pred        | 0.70  |
| impact_pred         | 8.50  |
| cost_pred           | 0.15  |
| learning_value_pred | 1.50  |
| ev_pred             | 8.81  |

### Step Metrics Rationale

- $\text{EV} = 0.99 \times 8.50 + 0.5 \times 1.50 - 0.3 \times 0.70 - 0.15 = 8.415 + 0.75 - 0.21 - 0.15 = 8.805 \approx 8.81$. Extracting domain scoring logic from the CLI handler into a pure domain module eliminates high cyclomatic complexity and enables direct testing of evaluation algorithms.

---

## Step 2: Create Dedicated Offline Metrics Aggregation Domain Module (`src/holon_coherence/metrics/aggregation.py`)

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Encapsulate offline wire-log aggregation domain logic currently trapped inside `commands/metrics.py` (`_read_offline_metrics`, CC 36) into a pure, testable domain module `src/holon_coherence/metrics/aggregation.py`. Decompose aggregation across request accounting, token counters, timing samples, and rate computations into small cohesive functions complying strictly with Bean 0186 thresholds.
- **Step type:** implementation
- **Exploration level:** 0.05
- **Git branch:** `I-1793425546-coherence-decompose-ab-test-and-metrics-commands`

### Implementation Details

1. **Package Initialization**:
   - Create package directory `src/holon_coherence/metrics/`.
   - Create `src/holon_coherence/metrics/__init__.py`.

2. **Domain Aggregation Model & State Container (`aggregation.py`)**:
   - Define domain dataclass/container `OfflineMetricsAccumulator` (or `OfflineMetricsState`) to cleanly pass mutable aggregation state without exceeding function parameter limits ($PLR0913 \le 5$).
   - Fields encapsulate:
     - Request and turn counters (`total_requests`, `seen_turn_ids`, `cache_hits`)
     - Context delta counters (`tool_calls_pruned`, `chars_saved`, `turns_summarized`, `cache_control_injected`)
     - Token counters (`total_input_tokens`, `total_output_tokens`, `total_cache_read_tokens`, `total_cache_creation_tokens`, `total_reasoning_tokens`)
     - Timing & rate accumulators (`sum_ttft_ms`, `count_ttft`, `sum_decode_throughput_tps`, `count_decode`, `sum_prefill_throughput_tps`, `count_prefill`, etc.)

3. **Granular Record Parsing Subroutines**:
   - `_process_record_cache_and_deltas(record: dict[str, Any], state: OfflineMetricsAccumulator) -> None`:
     - Extracts `turn_id`, detects `cache_action == "HIT"`, and accumulates `delta` fields.
   - `_process_record_usage(record: dict[str, Any], state: OfflineMetricsAccumulator) -> tuple[int, int, int]`:
     - Safely extracts `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_creation_tokens`, and reasoning tokens. Returns `(in_toks, out_toks, cache_read_toks)`.
   - `_process_record_timing(record: dict[str, Any], in_toks: int, out_toks: int, cache_read_toks: int, state: OfflineMetricsAccumulator) -> None`:
     - Converts millisecond timings to seconds, handles prefill rate derivations, tail prefill, and valid decode throughput streaming windows using `holon_coherence.metrics_math`.

4. **Aggregate Assembly & Formatting**:
   - `_compute_metrics_summary(state: OfflineMetricsAccumulator) -> dict[str, Any]`:
     - Calculates hit rates, token reductions (`chars_saved // 4`), average throughputs and TTFTs, and formats final dictionary matching exact offline telemetry dictionary schema.
   - `read_offline_metrics(wire_log_dir: str) -> dict[str, Any] | None`:
     - Reads `transactions.jsonl`, orchestrates line-by-line streaming, handles errors gracefully, and returns aggregated dictionary or `None`.
     - Meets $C901 \le 10$, with zero `# noqa` suppressions.

### Dependencies & Criticality

- **Dependencies:** None
- **Is bottleneck:** Yes — Decouples offline metrics domain logic from CLI rendering in `commands/metrics.py`.

### Safety & Constraint Considerations

- **Relevant rules:** §2 Coding Conventions & Standards, Bean 0186 Complexity Limits, Invariant 1 (Zero Synthetic Data).
- **Failure modes:** Subtle divergence in rate resolution between stored rate and derived rate (`_stored_rate`), or improper decode window filter handling.
- **Guardrails:** Reuse proven primitives from `holon_coherence.metrics_math` (`compute_decode_tps`, `compute_prefill_tps`, `compute_tail_prefill_tps`, `positive_rate`, `positive_seconds`, `average`).

### Success & Discard Criteria

- **Success:** `src/holon_coherence/metrics/aggregation.py` is created with zero `# noqa` comments, produces identical dictionary payloads as historical `_read_offline_metrics`, and complies with Bean 0186.
- **Discard:** Discard if aggregated numbers deviate from existing offline metrics expectations.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.99  |
| entropy_pred        | 0.60  |
| impact_pred         | 8.00  |
| cost_pred           | 0.12  |
| learning_value_pred | 1.50  |
| ev_pred             | 8.37  |

### Step Metrics Rationale

- $\text{EV} = 0.99 \times 8.00 + 0.5 \times 1.50 - 0.3 \times 0.60 - 0.12 = 7.92 + 0.75 - 0.18 - 0.12 = 8.37$. Decomposing the complex multi-pass line aggregation into an explicit state accumulator with focused handlers reduces technical debt and prepares for simplified CLI dispatch.

---

## Step 3: Refactor A/B Testing CLI Handler (`src/holon_coherence/commands/ab_test.py`)

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Refactor `src/holon_coherence/commands/ab_test.py` to strip out domain logic and retain solely CLI concerns: argument parsing, subparser registration, delegating execution to `holon_coherence.ab_testing.evaluation`, and output rendering (JSON vs console). Re-export domain items for backward compatibility, and decompose `handle_ab_test` and `run_live_replay_ab_test` to eliminate all `# noqa` comments.
- **Step type:** implementation
- **Exploration level:** 0.05
- **Git branch:** `I-1793425546-coherence-decompose-ab-test-and-metrics-commands`

### Implementation Details

1. **Re-export Domain Symbols for 100% Backward Compatibility**:
   - In `src/holon_coherence/commands/ab_test.py`:
     - Import and re-export `ABRunConfig`, `ABTurnMetrics`, `ABComparisonScorecard`, `load_trace_transactions`, `load_transactions_from_path`, `evaluate_offline_ab_run`, and `evaluate_runs` from `holon_coherence.ab_testing.evaluation`.
     - Define `__all__` to guarantee seamless compatibility with external scripts and tests.

2. **Decompose `run_live_replay_ab_test`**:
   - The current `run_live_replay_ab_test` is 90 statements and carries `# noqa: PLR0915`.
   - Decompose into focused operational subroutines:
     - `_warmup_proxy_endpoints(baseline_port: int, optimized_port: int, timeout: float) -> None`
     - `_execute_workload_replay(command: str, port: int, rounds: int) -> None`
     - `_collect_wire_log_transactions(wire_dir: str) -> list[dict[str, Any]]`
     - Orchestrator `run_live_replay_ab_test` calling the steps and delegating scoring to `evaluate_runs(...)`.
   - Remove `# noqa: PLR0915`.

3. **Decompose `handle_ab_test`**:
   - The current `handle_ab_test` (CC 18, 36 statements) carries `# noqa: C901, PLR0911, PLR0912`.
   - Decompose into:
     - `_parse_ab_run_config(args: argparse.Namespace) -> ABRunConfig`
     - `_dispatch_ab_test(config: ABRunConfig) -> ABComparisonScorecard`
     - `_render_ab_test_output(scorecard: ABComparisonScorecard, output_json: bool) -> int`
     - Main entry point `handle_ab_test(args: argparse.Namespace) -> int` delegating cleanly in < 15 lines.
   - Remove `# noqa: C901, PLR0911, PLR0912`.

### Dependencies & Criticality

- **Dependencies:** Step 1
- **Is bottleneck:** Yes — Transitions `commands/ab_test.py` from a domain monolith to a clean CLI adapter.

### Safety & Constraint Considerations

- **Relevant rules:** §2 Coding Conventions & Standards, Bean 0186 Complexity Limits, Backward-Compatibility Invariants.
- **Failure modes:** Broken CLI argument parsing or changes to exit codes (0 for pass, 1 for gate failure or error).
- **Guardrails:** Preserve identical CLI arguments in `register(subparsers)` and exact return code logic based on `scorecard.passed_threshold`.

### Success & Discard Criteria

- **Success:** `commands/ab_test.py` delegates domain logic cleanly, contains 0 `# noqa` complexity comments, satisfies $C901 \le 10$, and CLI tests pass without regression.
- **Discard:** Discard if CLI options or console output formats deviate from existing standards.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.98  |
| entropy_pred        | 0.70  |
| impact_pred         | 8.50  |
| cost_pred           | 0.18  |
| learning_value_pred | 1.00  |
| ev_pred             | 8.44  |

### Step Metrics Rationale

- $\text{EV} = 0.98 \times 8.50 + 0.5 \times 1.00 - 0.3 \times 0.70 - 0.18 = 8.33 + 0.50 - 0.21 - 0.18 = 8.44$. Simplifying CLI command dispatch to pure argument parsing and rendering enforces single responsibility and removes multiple legacy noqa suppressions.

---

## Step 4: Refactor Metrics CLI Handler (`src/holon_coherence/commands/metrics.py`)

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Refactor `src/holon_coherence/commands/metrics.py` to delegate offline log aggregation to `holon_coherence.metrics.aggregation` and decompose `handle_metrics` (currently CC 36, 172 lines) into modular helpers for port resolution, live/offline retrieval, terminal block formatting, and JSON output, eliminating all `# noqa` suppressions.
- **Step type:** implementation
- **Exploration level:** 0.05
- **Git branch:** `I-1793425546-coherence-decompose-ab-test-and-metrics-commands`

### Implementation Details

1. **Delegate `_read_offline_metrics`**:
   - In `src/holon_coherence/commands/metrics.py`, refactor `_read_offline_metrics(wire_log_dir: str)` into a one-line delegating wrapper pointing to `read_offline_metrics` in `holon_coherence.metrics.aggregation`.
   - Remove `# noqa: C901, PLR0912, PLR0915` from `_read_offline_metrics`.

2. **Decompose `handle_metrics`**:
   - The current `handle_metrics` carries `# noqa: C901, PLR0912, PLR0915`.
   - Decompose into cohesive functional units:
     - `_resolve_target_port(args: Any, port: int | None) -> int`:
       - Handles args, explicit port, `HOLON_PROXY_PORT` env, container port mapping, and default port fallback.
     - `_query_live_proxy_metrics(port: int) -> dict[str, Any] | None`:
       - Dispatches HTTP request to `http://127.0.0.1:{port}/holon/api/metrics`.
     - `_find_and_read_offline_metrics(args: Any) -> dict[str, Any] | None`:
       - Searches `WIRE_LOG_DIR`, `DEFAULT_WIRE_LOG_DIR`, and `~/.holon/logs`.
     - `_render_metrics_terminal(metrics: dict[str, Any], is_live: bool, port: int, container: str, resolve_fn: Any) -> None`:
       - Formats and displays terminal table rows:
         - Optimization overview block (tool calls, tokens reduced, cache hit rate)
         - Latency and throughput block (TTFT, prefill, tail prefill, decode throughput)
         - Token accounting block (input, output, cache read/write, reasoning)
         - Endpoint details block via `format_endpoint_rows`
     - Orchestrator `handle_metrics` coordinating port resolution, fetch, error printing, JSON dump, or terminal rendering in < 25 statements, strictly adhering to Bean 0186 limits.
   - Remove `# noqa: C901, PLR0912, PLR0915` from `handle_metrics`.

### Dependencies & Criticality

- **Dependencies:** Step 2
- **Is bottleneck:** Yes — Decouples CLI presentation from data fetching and calculation in `commands/metrics.py`.

### Safety & Constraint Considerations

- **Relevant rules:** §2 Coding Conventions & Standards, Bean 0186 Complexity Limits, Rule 2 & 6 (Telemetry Verification).
- **Failure modes:** Breakage of endpoint token scrubbing in JSON mode, subtle layout deviations in terminal table formatting, or altered exit codes when proxy is unreachable without `--offline`.
- **Guardrails:** Keep exact string formatting (`format_table_row`, banner dividers, status lines) identical to preserve 100% snapshot parity.

### Success & Discard Criteria

- **Success:** `commands/metrics.py` contains 0 `# noqa` complexity comments, satisfies $C901 \le 10$, and all CLI tests in `tests/commands/test_metrics.py` pass without modification.
- **Discard:** Discard if any test fixture or CLI output format deviates.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.98  |
| entropy_pred        | 0.60  |
| impact_pred         | 8.20  |
| cost_pred           | 0.15  |
| learning_value_pred | 1.00  |
| ev_pred             | 8.21  |

### Step Metrics Rationale

- $\text{EV} = 0.98 \times 8.20 + 0.5 \times 1.00 - 0.3 \times 0.60 - 0.15 = 8.036 + 0.50 - 0.18 - 0.15 = 8.206 \approx 8.21$. Decomposing `handle_metrics` into targeted fetch, resolution, and presentation functions simplifies maintenance and eliminates legacy noqa suppressions.

---

## Step 5: Domain Test Suite Expansion & 100% Parity Verification

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Author dedicated domain unit tests targeting `src/holon_coherence/ab_testing/evaluation.py` and `src/holon_coherence/metrics/aggregation.py` directly, verifying algorithmic correctness, edge case handling, and error handling without depending on CLI argument parsers. Concurrently verify 100% regression-free execution of existing CLI test suites.
- **Step type:** testing
- **Exploration level:** 0.05
- **Git branch:** `I-1793425546-coherence-decompose-ab-test-and-metrics-commands`

### Implementation Details

1. **A/B Testing Evaluation Domain Tests (`tests/test_ab_testing.py` or new dedicated test module)**:
   - Test `load_trace_transactions` with authentic JSON array vs JSON Lines files, invalid JSON lines, empty files, and non-existent paths.
   - Test `load_transactions_from_path` with single files vs directory walks (`turn_*.json` and `*.jsonl`).
   - Test `evaluate_offline_ab_run`:
     - Verification of token reduction calculations, ratio bounds, and character counting.
     - Verification of structural semantic parity (preserving messages/contents structure).
     - Gate verification (`fail_under_reduction` threshold passing and failing).
   - Test `evaluate_runs`:
     - Pairing logic when baseline and optimized runs have different turn counts.
     - TTFT and TPS sample extraction and average calculation.
     - Scorecard dictionary conversion and formatted text output.

2. **Offline Metrics Aggregation Domain Tests**:
   - Test `read_offline_metrics` with authentic wire-log streams:
     - Multi-turn tracking and `seen_turn_ids` count.
     - Cache hit calculation and cache hit rate rounding.
     - Token accounting for input, output, cache read/creation, and reasoning tokens.
     - Prefill and decode throughput derivations (including stored vs derived rates and streaming window validation).
     - Handling missing `transactions.jsonl` and empty or corrupted lines.

3. **CLI Test Suite Regression Verification**:
   - Execute existing test suites:
     - `tests/test_ab_testing.py`
     - `tests/commands/test_ab_test.py`
     - `tests/commands/test_metrics.py`
   - Confirm 100% pass rate with zero behavioral drift.

### Dependencies & Criticality

- **Dependencies:** Step 1, Step 2, Step 3, Step 4
- **Is bottleneck:** Yes — Validates behavioral invariance and domain robustness across all refactored surfaces.

### Safety & Constraint Considerations

- **Relevant rules:** §3 Testing Constraints, Rule 1 (Zero Synthetic Data for Benchmarking).
- **Failure modes:** Flaky assertions on mock timing or unmeasured rates.
- **Guardrails:** Utilize authentic wire-log fixtures conforming to project standards.

### Success & Discard Criteria

- **Success:** All new domain tests and existing CLI tests pass cleanly without modifications to test assertions.
- **Discard:** Discard if any test breaks or requires altering expected outputs.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.99  |
| entropy_pred        | 0.50  |
| impact_pred         | 8.00  |
| cost_pred           | 0.10  |
| learning_value_pred | 1.00  |
| ev_pred             | 8.17  |

### Step Metrics Rationale

- $\text{EV} = 0.99 \times 8.00 + 0.5 \times 1.00 - 0.3 \times 0.50 - 0.10 = 7.92 + 0.50 - 0.15 - 0.10 = 8.17$. Dedicated domain test coverage isolates core calculations from CLI harness overhead and proves parity.

---

## Step 6: Complexity Ratchet Audit, Baseline Ceiling Reduction & Full Gate Verification

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Audit the entire repository for strict Bean 0186 complexity compliance, update the ratchet ceiling in `tests/test_complexity_baseline.py` to permanently capture the elimination of legacy `# noqa` suppressions from `commands/ab_test.py` and `commands/metrics.py`, format code with Ruff, format markdown with Prettier, and prepare a single clean squashed commit.
- **Step type:** validation
- **Exploration level:** 0.05
- **Git branch:** `I-1793425546-coherence-decompose-ab-test-and-metrics-commands`

### Implementation Details

1. **Complexity Ratchet Audit**:
   - Audit all eliminated `# noqa` complexity suppressions:
     - `src/holon_coherence/commands/ab_test.py`: 6 eliminated (`load_trace_transactions`, `load_transactions_from_path`, `evaluate_offline_ab_run`, `evaluate_runs`, `run_live_replay_ab_test`, `handle_ab_test`).
     - `src/holon_coherence/commands/metrics.py`: 2 eliminated (`_read_offline_metrics`, `handle_metrics`).
   - Audit newly created modules:
     - `src/holon_coherence/ab_testing/evaluation.py`: 0 `# noqa` suppressions.
     - `src/holon_coherence/metrics/aggregation.py`: 0 `# noqa` suppressions.
   - Verify every function satisfies Bean 0186 complexity limits:
     - McCabe cyclomatic complexity: $C901 \le 10$
     - Maximum function returns: $PLR0911 \le 6$
     - Maximum branches: $PLR0912 \le 12$
     - Maximum function arguments: $PLR0913 \le 5$
     - Maximum function statements: $PLR0915 \le 50$
   - Update `BASELINE_CEILING` in `tests/test_complexity_baseline.py` (ratcheting down from 24 to 16).
   - Run complexity ratchet test:
     ```bash
     uv run pytest tests/test_complexity_baseline.py
     ```

2. **Full Pytest Suite Execution**:
   - Execute the entire test suite from the root of the worktree:
     ```bash
     uv run pytest
     ```
   - Confirm 100% passing tests with zero regressions.

3. **Ruff Linting and Formatting**:
   - Run Ruff linter and formatter:
     ```bash
     uv run ruff check .
     uv run ruff format --check .
     ```

4. **Documentation and Markdown Formatting**:
   - Format all markdown documentation and plan artifacts using Prettier:
     ```bash
     npx prettier --write "**/*.md"
     ```

5. **Squash Commits & Clean Working Tree**:
   - Ensure all feature changes are squashed into a single logical commit relative to `origin/main` according to Holon git workflow rules.

### Dependencies & Criticality

- **Dependencies:** Step 1, Step 2, Step 3, Step 4, Step 5
- **Is bottleneck:** Yes — Final gate for acceptance criteria fulfillment.

### Safety & Constraint Considerations

- **Relevant rules:** §1 Runtime & Environment, §2 Coding Conventions & Standards, §3 Testing Constraints, Worktree Isolation & Squash Commits.
- **Failure modes:** Unintended ratchet drift or unformatted markdown.
- **Guardrails:** Automated test execution via `uv run pytest` and static checks with Ruff prior to completion.

### Success & Discard Criteria

- **Success:** Full `uv run pytest` suite passes, Ruff checks report 0 errors, ratchet ceiling reduced from 24 to 16 and passing, Prettier passes, and git history is squashed cleanly.
- **Discard:** Discard if any test failure, complexity violation, or lint error persists.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.99  |
| entropy_pred        | 0.50  |
| impact_pred         | 9.00  |
| cost_pred           | 0.10  |
| learning_value_pred | 1.00  |
| ev_pred             | 9.16  |

### Step Metrics Rationale

- $\text{EV} = 0.99 \times 9.00 + 0.5 \times 1.00 - 0.3 \times 0.50 - 0.10 = 8.91 + 0.50 - 0.15 - 0.10 = 9.16$. Enforcing permanent complexity ratchet reduction locks in architectural decoupling and ensures codebase hygiene.

---

## Strategy Rationale

The overall plan metrics are computed using the physics-driven Expected Value (EV) formula:

$$\text{EV} = P(\text{success}) \times \text{Impact} + \mu \times \text{LearningValue} - \lambda \times \Delta S_{\text{intent}} - \text{Cost}$$

Using baseline calibration constants $\lambda = 0.3$ and $\mu = 0.5$:

$$\text{EV} = (0.98 \times 8.80) + (0.5 \times 2.40) - (0.3 \times 3.60) - 0.80 = 8.624 + 1.20 - 1.08 - 0.80 = 7.944 \approx 7.94$$

- **$P(\text{success})$ (0.98):** The refactoring strategy relies on clean domain extraction without changing underlying evaluation math, parsing rules, or CLI contracts. High existing test coverage across `tests/test_ab_testing.py` and `tests/commands/test_metrics.py` ensures regressions are caught immediately.
- **$\text{Impact}$ (8.80):** Decouples domain computation from CLI rendering in two major command handlers (`commands/ab_test.py` and `commands/metrics.py`), eliminating 8 legacy `# noqa` complexity suppressions and reducing the baseline complexity ceiling in `tests/test_complexity_baseline.py` from 24 to 16.
- **$\mu \times \text{LearningValue}$ ($0.5 \times 2.40 = 1.20$):** Codifies reusable architectural patterns for separating pure domain evaluation from CLI presentation adapters and demonstrates how to decompose high-complexity loops and data accumulators to meet strict Bean 0186 thresholds.
- **$\lambda \times \Delta S_{\text{intent}}$ ($0.3 \times 3.60 = 1.08$):** Controlled entropy distribution across 6 sequential execution steps totaling 3.60, well within the allocated 5.0 entropy budget.
- **$\text{Cost}$ (0.80):** Implementation cost covering new domain package creation, helper function decomposition, backwards-compatible symbol re-exports, test authoring, and multi-tool gate verification.

---

## Planner Autonomy Summary

- **Intent handling:** `ACCEPT_AS_IS`
- **Reframed intent (if applicable):** NONE
- **Exploration stance:** Exploitation-dominant (0.05 exploration). The boundaries of the new modules (`src/holon_coherence/ab_testing/evaluation.py` and `src/holon_coherence/metrics/aggregation.py`), the command handlers, and the acceptance criteria are explicitly defined. The task is a structural separation of concerns with 100% behavioral parity.
- **Safety priority level:** `standard`
- **Priority Justification:** All refactoring operations are internal architectural refactorings. No network interception pipelines, wire logging schemas, or credentials are altered. All public CLI signatures and command options remain identical.

---

## Exploration

- **Proportion of steps that are exploratory:** 0.05
- **Justification:** The algorithms for evaluating A/B test runs and aggregating offline wire-log metrics are already functioning and fully exercised in existing tests. Minimal exploration (0.05) is allocated for confirming backward-compatible re-exports and ensuring no unexpected circular import cycles.

---

## Safety & Constraint Alignment

- **Key world ruleset constraints that affect this plan:**
  - `holon-config/world/ruleset.md`: Runtime compatibility with Python 3.13, execution of tests strictly via `uv run pytest` from worktree root, Ruff lint and format cleanliness, docstring and comment preservation.
  - Bean 0186 Complexity Limits: Enforce McCabe $C901 \le 10$, $PLR0911 \le 6$, $PLR0912 \le 12$, $PLR0913 \le 5$, $PLR0915 \le 50$. Update and ratchet down `BASELINE_CEILING` in `tests/test_complexity_baseline.py`.
  - Testing constraints: Zero test failures under `uv run pytest`, 100% preservation of existing test cases, and authentic non-synthetic test fixtures (Rule 1).
  - Git workflow constraints: Dedicated worktree branching off `origin/main`, single squashed commit relative to `main`, no autonomous remote push.
- **Potential violations or edge cases:**
  - Circular import cycles: Potential cycles between `holon_coherence.ab_testing.evaluation` and `holon_coherence.commands.ab_test`. Mitigated by keeping `evaluation.py` pure and having `commands/ab_test.py` import from `evaluation.py`.
  - Rate calculation drift: Differences in `_stored_rate` logic or decode throughput window validation during aggregation decomposition. Mitigated by directly reusing `holon_coherence.metrics_math` helpers.
  - CLI argument or exit code discrepancy: Changes in `handle_ab_test` or `handle_metrics` return values. Mitigated by maintaining exact dispatch pathways and return code semantics.
  - Ratchet test failure: Removing `# noqa` comments without reducing `BASELINE_CEILING` in `tests/test_complexity_baseline.py`. Mitigated by explicitly ratcheting down the ceiling in Step 6.
- **Mitigations built into the plan:**
  - Backward-compatible facades: Re-exporting all moved classes and functions in `commands/ab_test.py` and `commands/metrics.py`.
  - Modular helper decomposition: Designing state accumulator containers to keep argument counts $\le 5$ and cyclomatic complexity $\le 10$.
  - End-to-end regression testing: Running the full pytest test suite to verify 0 regressions across unit, CLI, and integration tests.
- **Allocated Entropy Budget:** 5.0
- **Predicted Plan Entropy:** 3.60 (sum of step entropies: $0.70 + 0.60 + 0.70 + 0.60 + 0.50 + 0.50 = 3.60$)
- **Budget Compliance:** Full compliance ($3.60 \le 5.00$).

---

## Plan Description & Strategy

1. **Step 1: Create Dedicated A/B Testing Evaluation Domain Module (`src/holon_coherence/ab_testing/evaluation.py`)**:
   Establish `src/holon_coherence/ab_testing/evaluation.py` with `AbRun`, `AbEvaluation`, `ABRunConfig`, `ABTurnMetrics`, and `ABComparisonScorecard`. Decompose `load_trace_transactions`, `load_transactions_from_path`, `evaluate_offline_ab_run`, and `evaluate_runs` into single-responsibility subroutines satisfying Bean 0186 complexity limits ($C901 \le 10$) with 0 `# noqa` suppressions.
2. **Step 2: Create Dedicated Offline Metrics Aggregation Domain Module (`src/holon_coherence/metrics/aggregation.py`)**:
   Establish `src/holon_coherence/metrics/aggregation.py` with `OfflineMetricsAccumulator` state model. Decompose offline wire-log stream aggregation (`read_offline_metrics`) into granular request, token, timing, and rate accounting functions satisfying Bean 0186 complexity limits with 0 `# noqa` suppressions.
3. **Step 3: Refactor A/B Testing CLI Handler (`src/holon_coherence/commands/ab_test.py`)**:
   Re-export domain classes and functions from `evaluation.py` to maintain 100% backward compatibility. Refactor `handle_ab_test` and `run_live_replay_ab_test` into thin CLI dispatch and rendering routines, eliminating all legacy `# noqa` comments.
4. **Step 4: Refactor Metrics CLI Handler (`src/holon_coherence/commands/metrics.py`)**:
   Delegate `_read_offline_metrics` directly to `holon_coherence.metrics.aggregation`. Decompose `handle_metrics` into port resolution, live proxy querying, offline fallback, and table/JSON rendering, eliminating all legacy `# noqa` comments.
5. **Step 5: Domain Test Suite Expansion & 100% Parity Verification**:
   Add direct domain unit tests for `evaluation.py` and `aggregation.py`. Verify existing CLI test suites (`tests/test_ab_testing.py`, `tests/commands/test_ab_test.py`, `tests/commands/test_metrics.py`) pass cleanly without regression.
6. **Step 6: Complexity Ratchet Audit, Baseline Ceiling Reduction & Full Gate Verification**:
   Audit the elimination of 8 legacy `# noqa` suppressions across both command handlers, reduce `BASELINE_CEILING` from 24 to 16 in `tests/test_complexity_baseline.py`, run `uv run pytest`, run Ruff checks, format markdown with Prettier, and prepare a squashed git commit.
