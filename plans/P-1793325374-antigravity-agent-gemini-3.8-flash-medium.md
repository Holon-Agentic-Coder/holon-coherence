# Plan for I-1793325144-coherence-ci-timing-gate-composite-action

- **Plan ID:** P-1793325374-antigravity-agent-gemini-3.8-flash-medium
- **Parent Intent ID:** NONE
- **Agent:** antigravity-agent (version: 1.4.10)
- **Created At:** 2026-10-30T01:56:15.295Z

---

## Overall Plan Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.95  |
| entropy_pred        | 2.40  |
| impact_pred         | 8.00  |
| cost_pred           | 0.80  |
| learning_value_pred | 2.00  |
| ev_pred             | 7.08  |

---

## Step 1: Author Composite Action `.github/actions/ci-timing-gate/action.yml`

### Step Intent & Git Integration

- **Sub-intent recommendation:** none (monolithic execution within intent scope)
- **Reasoning:** Defining the composite action establishes the single point of truth for recording CI job start
  timestamps and enforcing the CI runtime budget across all workflows.
- **Step type:** implementation
- **Exploration level:** 0.05
- **Git branch:** `I-1793325144-coherence-ci-timing-gate-composite-action`

### Implementation Details

- Create directory `.github/actions/ci-timing-gate/` and author `.github/actions/ci-timing-gate/action.yml`.
- Declare metadata:
  - `name: "CI Timing Gate"`
  - `description: "Records job start time or checks total elapsed job runtime against a threshold budget."`
- Declare inputs:
  - `phase`: required string, valid values `'start'` or `'check'`.
  - `max-seconds`: optional string/number, default `'300'`.
- Define composite run steps:
  1. **Phase Validation Step**:
     ```yaml
     - name: Validate Phase Input
       if: inputs.phase != 'start' && inputs.phase != 'check'
       shell: bash
       run: |
         echo "::error::Invalid phase '${{ inputs.phase }}'. Expected 'start' or 'check'."
         exit 1
     ```
  2. **Phase: Start Step**:
     ```yaml
     - name: CI Timing Gate (Start)
       if: inputs.phase == 'start'
       shell: bash
       run: |
         CI_JOB_START_EPOCH=$(date +%s)
         echo "CI_JOB_START_EPOCH=${CI_JOB_START_EPOCH}" >> "$GITHUB_ENV"
         # Maintain backward compatibility with CI_TIMING_STARTED_AT consumers
         echo "CI_TIMING_STARTED_AT=${CI_JOB_START_EPOCH}" >> "$GITHUB_ENV"
     ```
  3. **Phase: Check Step**:
     ```yaml
     - name: CI Timing Gate (Check)
       if: inputs.phase == 'check'
       shell: bash
       run: |
         python3 "${GITHUB_WORKSPACE}/scripts/check_ci_runtime_budget.py" \
           --start-epoch "${CI_JOB_START_EPOCH}" \
           --max-seconds "${{ inputs.max-seconds }}" \
           --step-summary "${GITHUB_STEP_SUMMARY}"
     ```

### Dependencies & Criticality

- **Dependencies:** None
- **Is bottleneck:** Yes — All 5 workflows depend on this action being created before they can invoke it.

### Safety & Constraint Considerations

- **Relevant rules:** Non-destructive execution, strict standard bash shell syntax.
- **Failure modes:**
  - Invoking action with unrecognised phase (e.g. empty or typo like `finish`): caught by validation step.
  - Action path unavailable if executed prior to `actions/checkout`: handled by workflow ordering.
- **Guardrails:** Explicit validation step with `::error::` annotation and exit code 1.

### Success & Discard Criteria

- **Success:** `.github/actions/ci-timing-gate/action.yml` is syntactically valid YAML, handles both `'start'` and
  `'check'`, validates input phase, and sets environment variables as specified.
- **Discard:** Discard and reconstruct if composite action syntax errors are flagged by workflow parsers.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.98  |
| entropy_pred        | 0.40  |
| impact_pred         | 8.00  |
| cost_pred           | 0.15  |
| learning_value_pred | 1.50  |
| ev_pred             | 8.32  |

### Step Metrics Rationale

- $\text{EV} = 0.98 \times 8.00 + 0.5 \times 1.50 - 0.3 \times 0.40 - 0.15 = 7.84 + 0.75 - 0.12 - 0.15 = 8.32$. High
  probability of success with zero external dependencies.

---

## Step 2: Runtime Budget Verification Bridge & Script Alignment

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Acceptance Criterion 3 specifies that when `inputs.phase == 'check'`, the composite action invokes
  `python3 "${GITHUB_WORKSPACE}/scripts/check_ci_runtime_budget.py" --start-epoch "${CI_JOB_START_EPOCH}" --max-seconds "${{ inputs.max-seconds }}" --step-summary "${GITHUB_STEP_SUMMARY}"`.
  Ensuring this script exists and behaves deterministically prevents job check execution failures while maintaining
  backward compatibility with `scripts/ci_timing_gate.py`.
- **Step type:** implementation
- **Exploration level:** 0.05
- **Git branch:** `I-1793325144-coherence-ci-timing-gate-composite-action`

### Implementation Details

- Author `scripts/check_ci_runtime_budget.py` (standard library only: `argparse`, `os`, `sys`, `time`):
  - Parse CLI arguments:
    - `--start-epoch`: integer or float timestamp (epoch seconds)
    - `--max-seconds`: float/int maximum allowed runtime (seconds, e.g. 300)
    - `--step-summary`: optional path to GitHub Step Summary file
  - Logic:
    - Determine `current_epoch = time.time()`
    - Compute `elapsed = current_epoch - start_epoch`
    - Format status output: elapsed seconds, maximum budget, and percentage of budget used.
    - If `step_summary` is provided and file path exists/writable, append Markdown table summary:

      ```markdown
      ### CI Runtime Budget Check

      | Metric             | Value           |
      | :----------------- | :-------------- |
      | Elapsed Duration   | <elapsed> s     |
      | Maximum Budget     | <max_seconds> s |
      | Budget Utilization | <pct>%          |
      | Status             | PASS / FAIL     |
      ```

    - Check if `elapsed > max_seconds`:
      - If violated: print `::error::Job runtime (<elapsed>s) exceeded budget (<max_seconds>s)` and `sys.exit(1)`.
      - If within budget: print notice/summary and `sys.exit(0)`.

  - Ensure compatibility with Python 3.11+ so system python can run it without requiring conda or uv.

### Dependencies & Criticality

- **Dependencies:** Step 1
- **Is bottleneck:** No

### Safety & Constraint Considerations

- **Relevant rules:** Standard library only, no external dependencies, Australian English in user output.
- **Failure modes:** Unset or invalid `--start-epoch`: fallback gracefully (warn or skip with exit 0 rather than failing
  the build if start epoch wasn't set).
- **Guardrails:** Guard against division by zero if `max_seconds <= 0`.

### Success & Discard Criteria

- **Success:** `scripts/check_ci_runtime_budget.py` correctly parses flags, calculates elapsed time, writes summary, and
  exits with non-zero status only when runtime budget is exceeded.
- **Discard:** Discard if execution introduces syntax incompatibilities on older Python versions.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.98  |
| entropy_pred        | 0.30  |
| impact_pred         | 7.50  |
| cost_pred           | 0.15  |
| learning_value_pred | 1.00  |
| ev_pred             | 7.61  |

### Step Metrics Rationale

- $\text{EV} = 0.98 \times 7.50 + 0.5 \times 1.00 - 0.3 \times 0.30 - 0.15 = 7.35 + 0.50 - 0.09 - 0.15 = 7.61$. Clean,
  pure script with explicit parameter validation.

---

## Step 3: Refactor `docker-build.yml` and `make.yml` to Use Composite Action

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Eliminate inline CI timing steps in `docker-build.yml` and `make.yml`, ensuring `actions/checkout`
  executes first before calling `./.github/actions/ci-timing-gate`.
- **Step type:** implementation
- **Exploration level:** 0.00
- **Git branch:** `I-1793325144-coherence-ci-timing-gate-composite-action`

### Implementation Details

- **In `.github/workflows/docker-build.yml`:**
  - Reorder initial steps so `actions/checkout@v7` is the very first step under `steps:`
  - Add start step immediately following checkout:
    ```yaml
    - name: CI Timing Gate (Start)
      uses: ./.github/actions/ci-timing-gate
      with:
        phase: start
    ```
  - At the end of the job steps, add check step (preserving `if: always()`):
    ```yaml
    - name: CI Timing Gate (Check <= 5 min)
      if: always()
      uses: ./.github/actions/ci-timing-gate
      with:
        phase: check
        max-seconds: "300"
    ```
  - Remove redundant inline `Record job start time` step (`echo "CI_TIMING_STARTED_AT=$(date +%s)" >> "$GITHUB_ENV"`).
  - Retain existing `CI timing gate (record)`, `CI timing gate (compare with main)`, and `Upload CI timing record` steps
    if desired, or replace them cleanly with the unified gate action as required by acceptance criteria.

- **In `.github/workflows/make.yml`:**
  - In `make` job (`matrix: os: [ubuntu-latest, macos-latest]`):
  - Ensure `actions/checkout@v7` is step 1.
  - Insert `CI Timing Gate (Start)` using `./.github/actions/ci-timing-gate` with `phase: start` right after checkout.
  - At job end, add `CI Timing Gate (Check <= 5 min)` with `if: always()`, `phase: check`, and `max-seconds: "300"`.
  - Remove duplicated inline start block.

### Dependencies & Criticality

- **Dependencies:** Step 1, Step 2
- **Is bottleneck:** Yes

### Safety & Constraint Considerations

- **Relevant rules:** Workflows must remain valid YAML; matrix expansion on both Ubuntu and macOS runners must be
  preserved.
- **Failure modes:** Action invocation failing because local repository checkout has not occurred.
- **Guardrails:** Order `actions/checkout` strictly before any `uses: ./.github/actions/*` step.

### Success & Discard Criteria

- **Success:** `docker-build.yml` and `make.yml` cleanly parse, invoke the composite action, and preserve step
  semantics.
- **Discard:** Discard if YAML indentation or schema errors occur.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.96  |
| entropy_pred        | 0.40  |
| impact_pred         | 7.50  |
| cost_pred           | 0.15  |
| learning_value_pred | 1.00  |
| ev_pred             | 7.43  |

### Step Metrics Rationale

- $\text{EV} = 0.96 \times 7.50 + 0.5 \times 1.00 - 0.3 \times 0.40 - 0.15 = 7.20 + 0.50 - 0.12 - 0.15 = 7.43$.

---

## Step 4: Refactor `test-hygiene.yml`, `test-integration.yml`, and `test-unit.yml`

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Complete composite action adoption across remaining test workflows, standardising start and check gate
  invocations across all CI jobs.
- **Step type:** implementation
- **Exploration level:** 0.00
- **Git branch:** `I-1793325144-coherence-ci-timing-gate-composite-action`

### Implementation Details

- **In `.github/workflows/test-hygiene.yml`:**
  - Order `actions/checkout@v7` first.
  - Add `CI Timing Gate (Start)` immediately following checkout (`phase: start`).
  - Add `CI Timing Gate (Check <= 5 min)` as final step with `if: always()`, `phase: check`, and `max-seconds: "300"`.
  - Remove inline `Record job start time` block.

- **In `.github/workflows/test-integration.yml`:**
  - Order `actions/checkout@v7` first.
  - Add `CI Timing Gate (Start)` immediately following checkout (`phase: start`).
  - Add `CI Timing Gate (Check <= 5 min)` at end with `if: always()`, `phase: check`, and `max-seconds: "300"`.
  - Remove inline `Record job start time` block.

- **In `.github/workflows/test-unit.yml`:**
  - Order `actions/checkout@v7` first.
  - Add `CI Timing Gate (Start)` immediately following checkout (`phase: start`).
  - Add `CI Timing Gate (Check <= 5 min)` at end with `if: always()`, `phase: check`, and `max-seconds: "300"`.
  - Remove inline `Record job start time` block.

### Dependencies & Criticality

- **Dependencies:** Step 1, Step 2
- **Is bottleneck:** No

### Safety & Constraint Considerations

- **Relevant rules:** Maintain all matrix definitions, permissions blocks, and environment setups intact.
- **Failure modes:** Regressions in test execution or reporting steps.
- **Guardrails:** Keep all test commands (`uv run task test`, `uv run task test-docker`, `uv run task lint`) unchanged.

### Success & Discard Criteria

- **Success:** All three test workflows invoke the composite action cleanly at start and check phases.
- **Discard:** Discard if any test task definition is accidentally altered.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.97  |
| entropy_pred        | 0.40  |
| impact_pred         | 7.50  |
| cost_pred           | 0.15  |
| learning_value_pred | 1.00  |
| ev_pred             | 7.51  |

### Step Metrics Rationale

- $\text{EV} = 0.97 \times 7.50 + 0.5 \times 1.00 - 0.3 \times 0.40 - 0.15 = 7.275 + 0.50 - 0.12 - 0.15 = 7.505 \approx
  7.51$.

---

## Step 5: Document Composite Action in `.github/workflows/README.md`

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Maintain accurate documentation of reusable actions and workflow architecture.
- **Step type:** documentation
- **Exploration level:** 0.00
- **Git branch:** `I-1793325144-coherence-ci-timing-gate-composite-action`

### Implementation Details

- In `.github/workflows/README.md`, under `## Reusable Actions`, add a new subsection documenting
  `.github/actions/ci-timing-gate`:
  - Detail action location: `.github/actions/ci-timing-gate/action.yml`.
  - Detail purpose: Single reusable composite action eliminating duplicated shell blocks for recording job start epochs
    and verifying job runtimes against maximum duration budgets.
  - Detail inputs:
    - `phase`: Required. `'start'` writes `CI_JOB_START_EPOCH` to `$GITHUB_ENV`; `'check'` invokes the runtime budget
      checker script.
    - `max-seconds`: Optional (default: `'300'`). Maximum allowed runtime threshold in seconds.
  - Document ordering prerequisite: `actions/checkout` must execute before invoking `.github/actions/ci-timing-gate`
    with `phase: start`.
  - Provide example YAML snippet demonstrating job invocation pattern.

### Dependencies & Criticality

- **Dependencies:** Step 1, Step 3, Step 4
- **Is bottleneck:** No

### Safety & Constraint Considerations

- **Relevant rules:** Australian English spelling, clean Markdown formatting passing Prettier.
- **Failure modes:** Broken markdown syntax or outdated documentation links.
- **Guardrails:** Format with Prettier before committing.

### Success & Discard Criteria

- **Success:** `.github/workflows/README.md` clearly describes `.github/actions/ci-timing-gate` and adheres to
  repository documentation conventions.
- **Discard:** Discard if Prettier formatting checks fail.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.99  |
| entropy_pred        | 0.20  |
| impact_pred         | 7.00  |
| cost_pred           | 0.10  |
| learning_value_pred | 1.00  |
| ev_pred             | 7.27  |

### Step Metrics Rationale

- $\text{EV} = 0.99 \times 7.00 + 0.5 \times 1.00 - 0.3 \times 0.20 - 0.10 = 6.93 + 0.50 - 0.06 - 0.10 = 7.27$.
  Straightforward documentation update.

---

## Step 6: Comprehensive Verification and Quality Gates

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Validate that all modified YAML workflow files and Python scripts parse correctly, all pre-existing
  tests pass without regressions, and linting/formatting checks are 100% green.
- **Step type:** verification
- **Exploration level:** 0.00
- **Git branch:** `I-1793325144-coherence-ci-timing-gate-composite-action`

### Implementation Details

- **Test Suite Execution:**
  - Execute `uv run pytest tests/test_ci_timing_gate.py` to confirm timing gate unit test suite remains 100% passing.
  - Execute full test suite via `uv run pytest` (or `uv run task test`) to guarantee zero regressions.
- **Workflow & Action YAML Validation:**
  - Verify syntax and schema of `.github/actions/ci-timing-gate/action.yml` and all 5 edited workflow files
    (`docker-build.yml`, `make.yml`, `test-hygiene.yml`, `test-integration.yml`, `test-unit.yml`).
- **Formatting and Linting Checks:**
  - Run `uv run ruff check .` and `uv run ruff format --check .` to ensure Python code cleanliness.
  - Run `npx prettier --check "**/*.md"` to verify Markdown formatting compliance.
- **Git State Hygiene:**
  - Squash commits into a single logical commit on the feature branch.
  - Ensure zero unstaged artifacts or temporary files are tracked.

### Dependencies & Criticality

- **Dependencies:** Step 1, Step 2, Step 3, Step 4, Step 5
- **Is bottleneck:** Yes — Final gate before merge readiness.

### Safety & Constraint Considerations

- **Relevant rules:** §3 Testing Constraints in world ruleset (hermetic isolation, zero unstaged regressions).
- **Failure modes:** Uncaught YAML indentation errors or broken pytest fixtures.
- **Guardrails:** Automated test and linter validation commands run locally.

### Success & Discard Criteria

- **Success:** 100% test pass rate across all suites, zero Ruff errors, zero Prettier formatting errors, clean git
  status.
- **Discard:** Discard commit if any pre-existing test fails.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.98  |
| entropy_pred        | 0.70  |
| impact_pred         | 8.00  |
| cost_pred           | 0.10  |
| learning_value_pred | 1.00  |
| ev_pred             | 8.03  |

### Step Metrics Rationale

- $\text{EV} = 0.98 \times 8.00 + 0.5 \times 1.00 - 0.3 \times 0.70 - 0.10 = 7.84 + 0.50 - 0.21 - 0.10 = 8.03$. High
  verification rigor guarantees deliverable integrity.

---

## Strategy Rationale

The overall plan metrics are computed using the physics-driven Expected Value (EV) formula:

$$\text{EV} = P(\text{success}) \times \text{Impact} + \mu \times \text{LearningValue} - \lambda \times \Delta S_{\text{intent}} - \text{Cost}$$

Using baseline calibration constants $\lambda = 0.3$ and $\mu = 0.5$:

$$\text{EV} = (0.95 \times 8.00) + (0.5 \times 2.00) - (0.3 \times 2.40) - 0.80 = 7.60 + 1.00 - 0.72 - 0.80 = 7.08$$

- **$P(\text{success})$ (0.95):** The problem is deterministic and strictly bounded within GitHub Actions composite
  actions and workflow YAML syntax.
- **$\text{Impact}$ (8.00):** Consolidates 10 duplicated steps across 5 CI workflows into a single canonical composite
  action, improving workflow maintainability and eliminating drift.
- **$\mu \times \text{LearningValue}$ ($0.5 \times 2.00 = 1.00$):** Establishes a reusable local composite action
  pattern for modular GitHub Actions within the repository.
- **$\lambda \times \Delta S\_{\text{intent}}$ ($0.3 \times 2.40 = 0.72$):** Bounded entropy across 7 target files in
  scope.
- **$\text{Cost}$ (0.80):** Low execution cost involving straightforward file authoring, YAML step replacements, and
  standard test runs.

---

## Planner Autonomy Summary

- **Intent handling:** `ACCEPT_AS_IS`
- **Reframed intent (if applicable):** NONE
- **Exploration stance:** Exploitation-dominant (0.05 exploration). The requirements are concrete, deterministic, and
  fully specified in the raw intent specification. Composite actions and GitHub Actions workflows are well-understood
  declarative mechanisms.
- **Safety priority level:** `standard`
- **Priority Justification:** Changes are confined to CI workflow files (`.github/workflows/*.yml`), local composite
  actions (`.github/actions/ci-timing-gate/action.yml`), and documentation (`.github/workflows/README.md`). No runtime
  proxy interception code in `src/holon_coherence/` or security keys are modified.

---

## Exploration

- **Proportion of steps that are exploratory:** 0.05
- **Justification:** The implementation mechanics of GitHub Actions composite actions and YAML workflow steps are well
  established. A minimal exploratory allowance (0.05) accounts for verifying runner-local path resolution of
  `./.github/actions/ci-timing-gate` relative to repository checkout.

---

## Safety & Constraint Alignment

- **Key world ruleset constraints that affect this plan:**
  - `holon-config/world/ruleset.md`: Runtime compatibility with Python 3.13, execution of tests strictly via
    `uv run pytest`, zero Ruff lint/format errors.
  - Testing constraints: Hermetic test isolation, zero unstaged regressions across all existing test suites
    (`tests/test_ci_timing_gate.py` and unit tests).
  - Code hygiene and documentation standards: Australian English spelling across docstrings, documentation, and error
    messages; Prettier markdown formatting (`npx prettier --check "**/*.md"`).
  - Sandbox containment: Tool actions remain strictly within the workspace boundaries.
- **Potential violations or edge cases:**
  - Ordering hazard: If `.github/actions/ci-timing-gate` is invoked before `actions/checkout`, the runner fails
    immediately because the composite action file does not exist on disk yet.
  - Phase parameter typo: An invalid phase could silently pass or fail unpredictably if not validated.
  - Step failure masking: If a job fails in an earlier step, the timing check must still run to record metrics or report
    summaries.
- **Mitigations built into the plan:**
  - Strict step reordering: All 5 workflows are updated to execute `actions/checkout` as step 1 prior to calling the
    timing gate composite action with `phase: start`.
  - Explicit phase validation: The composite action includes an initial step checking
    `inputs.phase != 'start' && inputs.phase != 'check'` and failing immediately with a clear error annotation.
  - Execution condition preservation: The check step explicitly preserves `if: always()` so runtime budgets are
    evaluated regardless of preceding step outcomes.
- **Allocated Entropy Budget:** 15.0
- **Predicted Plan Entropy:** 2.40 (sum of step entropies: $0.40 + 0.30 + 0.40 + 0.40 + 0.20 + 0.70 = 2.40$)
- **Budget Compliance:** Full compliance ($2.40 \le 15.00$).

---

## Plan Description & Strategy

1. **Step 1: Author Composite Action `.github/actions/ci-timing-gate/action.yml`**: Define the reusable composite action
   with required input `phase` (`start` or `check`), optional input `max-seconds` (default `'300'`), input phase
   validation, epoch timestamp recording for `phase: start`, and runtime budget execution for `phase: check`.
2. **Step 2: Runtime Budget Verification Bridge & Script Alignment**: Ensure `scripts/check_ci_runtime_budget.py` is
   present with CLI flags `--start-epoch`, `--max-seconds`, and `--step-summary` to evaluate elapsed runtime against
   budget thresholds cleanly.
3. **Step 3: Refactor `docker-build.yml` and `make.yml` to Use Composite Action**: Reorder checkout first, replace
   inline timing gate start and check steps with `uses: ./.github/actions/ci-timing-gate`, and preserve `if: always()`.
4. **Step 4: Refactor `test-hygiene.yml`, `test-integration.yml`, and `test-unit.yml`**: Standardise timing gate
   invocations across the remaining three test workflows with checkout preceding `phase: start` and `phase: check` at
   the end.
5. **Step 5: Document Composite Action in `.github/workflows/README.md`**: Add documentation for
   `.github/actions/ci-timing-gate` detailing inputs, checkout ordering prerequisites, and example usage snippets.
6. **Step 6: Comprehensive Verification and Quality Gates**: Execute `uv run pytest tests/test_ci_timing_gate.py`, full
   `uv run pytest`, Ruff linting, Prettier markdown formatting checks, and commit hygiene validation.
