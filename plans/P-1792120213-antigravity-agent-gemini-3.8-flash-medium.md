# Plan for I-1792120178-coherence-ab-testing-suite-and-docs

- **Plan ID:** P-1792120213-antigravity-agent-gemini-3.8-flash-medium
- **Agent:** antigravity-agent
- **Model:** gemini-3.8-flash-medium
- **Created At:** 2026-10-16T03:10:13Z
- **Bean:** holon-agentic-coder-ref-metadata-0098
- **Target Repository:** `holon-coherence` (base `origin/main` @ `97cc295`, Bean 0097 merged)

## Overall Plan Metrics

| metric              | value |
| ------------------- | ----- |
| p_success_pred      | 0.9   |
| entropy_pred        | 2.0   |
| impact_pred         | 80.0  |
| cost_pred           | 4.0   |
| learning_value_pred | 3.0   |
| ev_pred             | 68.9  |

## 1. Problem Statement & Motivation

`holon-coherence` optimizes LLM context by stripping redundant tool outputs, deduplicating repetitive messages, injecting prompt cache breakpoints, and caching deterministic requests. However, operators and CI pipelines currently lack an automated, reproducible testing harness to:

1. **Quantify Optimization Efficacy**: Objectively measure the exact percentage of prompt tokens reduced, characters saved, and tool calls pruned across multi-turn sessions.
2. **Validate Semantic Parity**: Formally prove that active token reduction does not alter completion semantics, corrupt code generation, or drop critical function-call arguments.
3. **Prevent Latency Regressions**: Compare Time-To-First-Token (TTFT) and decode throughput between unoptimized pass-through (Variant A) and optimized mitigation (Variant B).
4. **Comply with Repository Invariant 10**: Enforce testing against authentic wire logs (`transactions.jsonl` or real production payload streams) while strictly banning synthetic mock string loops.

## 2. Technical Architecture & Design

### 2.1 A/B Testing Harness & Runner (`src/holon_coherence/commands/ab_test.py`)

A dedicated command module implementing:

- **`ABRunConfig`**: Dataclass specifying trace payload path, target endpoints/ports for Variant A (baseline) and Variant B (optimized), round count, timeout limits, and CI pass thresholds (`--fail-under-reduction`).
- **`ABRoundResult`**: Captures per-request and per-turn metrics for both variants:
  - Input tokens, output tokens, provider cache read tokens.
  - TTFT (ms), total latency (ms), decode throughput (tokens/sec).
  - Tool call count, pruned tool output count.
  - Response text / tool-call parity verification.
- **`ABComparisonScorecard`**: Aggregates all rounds into a statistical scorecard:
  - Absolute and percentage prompt token savings ($\Delta\text{Tokens} = \text{Tokens}_A - \text{Tokens}_B$).
  - Net character savings and omitted tool call ratio.
  - TTFT difference ($\Delta\text{TTFT}$).
  - Semantic match verification (structural equivalence of completion content).
- **Execution Modes**:
  1. **Offline Replay Mode**: Reads recorded transactions from an authentic `transactions.jsonl` trace file, feeds payloads through local payload cleaner / tokenizer functions, and compares baseline vs optimized metrics without external network egress.
  2. **Live Proxy Mode**: Replays trace requests sequentially or concurrently against Variant A (e.g. passive monitoring port or unoptimized gateway) and Variant B (optimized proxy), recording upstream telemetry headers (`X-Holon-*`).
- **Scorecard Output Formatters**:
  - `render_table()`: Rich terminal formatted ASCII summary table for human operators.
  - `to_dict()` / JSON serialization: Machine-readable output for automated CI gating (`--json`).

### 2.2 CLI Integration (`src/holon_coherence/cli.py`)

Integrate `ab-test` subcommand into the `holon-coherence` CLI:

- `holon-coherence ab-test --trace-file <path>` (alias: `-f`)
- `--rounds <N>` (default: 1)
- `--baseline-port <port>` / `--optimized-port <port>`
- `--passive-mode` (runs Variant A with passive monitoring)
- `--fail-under-reduction <float>` (exits with non-zero status if reduction % falls below threshold)
- `--json` (emits structured JSON to stdout)

### 2.3 Integration & Regression Test Suite (`tests/test_ab_testing.py`)

Comprehensive automated pytest suite verifying:

- Argument parsing, flag validation, and default configuration loading.
- Differential metric computation (token savings, cache read ratio, TTFT delta).
- Simulation of multi-turn traces with repeated tool outputs (e.g. repeated `git status` or build outputs) asserting $>20\%$ prompt token reduction without payload corruption.
- Error handling for missing trace files, corrupted JSON records, and unparseable provider formats.
- Semantic integrity validation ensuring modified payloads preserve essential instructions and schemas.

### 2.4 Operator Documentation (`docs/ab_testing_guide.md` & `README.md`)

Create comprehensive operator documentation detailing:

- Setup and execution workflow for local developer benchmarking, Docker-based testbeds, and CI pipelines.
- Detailed interpretation of each metric in the comparative scorecard.
- Configuration variables (`HOLON_PASSIVE_MONITORING`, `COHERENCE_TOKEN_REDUCTION`, `HOLON_PROXY_PORT`).
- Guidelines for capturing authentic production traces adhering to Rule 10.
- Reference and link the guide within root `README.md`.

## 3. Implementation Steps

1. **Step 1: Harness & Metric Calculation Module** (`src/holon_coherence/commands/ab_test.py`):
   - Implement configuration models, trace reader, differential metric calculators, and formatters.
2. **Step 2: CLI Subcommand Integration** (`src/holon_coherence/cli.py`, `src/holon_coherence/commands/__init__.py`):
   - Register `ab-test` command parser and dispatch handler.
3. **Step 3: Test Suite Implementation** (`tests/test_ab_testing.py`):
   - Write comprehensive tests asserting reduction, scorecards, and error handling.
4. **Step 4: Operator Documentation & README Update** (`docs/ab_testing_guide.md`, `README.md`):
   - Author complete operator guide and link in README.
5. **Step 5: Verification & Prettier Hygiene**:
   - Run `uv run pytest tests/test_ab_testing.py`, verify `ruff check .` / `ruff format --check .`, and ensure clean Prettier format.

## 4. Acceptance Criteria Mapping

| Acceptance Criterion                                                                                        | Implementation                                       | Verification Test                                                 |
| :---------------------------------------------------------------------------------------------------------- | :--------------------------------------------------- | :---------------------------------------------------------------- |
| Automated A/B test command compares Variant A (baseline) vs Variant B (optimized) on identical trace inputs | `src/holon_coherence/commands/ab_test.py`            | `tests/test_ab_testing.py::test_ab_test_run_execution`            |
| Outputs comparative scorecard with tokens reduced, tool calls pruned, cache hit ratios, and TTFT delta      | `ABComparisonScorecard.render_table()` / `to_dict()` | `tests/test_ab_testing.py::test_ab_scorecard_calculations`        |
| Integration tests assert >20% reduction on repetitive turn traces without payload loss                      | `tests/test_ab_testing.py`                           | `tests/test_ab_testing.py::test_repetitive_tool_reduction`        |
| Operator documentation in `docs/ab_testing_guide.md` and linked in `README.md`                              | `docs/ab_testing_guide.md`, `README.md`              | Doc inspection & markdown check                                   |
| 100% clean test pass and ruff lint clean                                                                    | Entire test suite and ruff                           | `uv run ruff check .` & `uv run pytest -m "not integration_test"` |

## 5. Risks and Mitigations

- **Risk: Flaky network comparisons during live runs.**  
  _Mitigation:_ Provide robust offline trace replay using authentic wire-log transactions so CI and local tests never depend on upstream provider availability or network latency fluctuations.
- **Risk: Prettier configuration collision from nested worktree.**  
  _Mitigation:_ Strictly observe Bean 0099 Invariant 13: format only touched markdown files with `--no-config` and verify `git diff --stat`.
