# Plan for I-1791108912-remove-coherence-executable-entrypoint

- **Plan ID:** P-1791108931-antigravity-agent-gemini-3.8-flash-medium
- **Parent Intent ID:** NONE
- **Agent:** antigravity-agent/gemini-3.8-flash-medium (version: 1.1.22)
- **Created At:** 2026-10-04T10:15:37Z

## Planner Autonomy Summary

- **Intent handling:** ACCEPT_AS_IS
- **Reframed intent (if applicable):** NONE
- **Exploration stance:** exploit with targeted verification of entrypoint removal, packaging metadata validity, and
  test suite execution.
- **Safety priority level:** standard
- **Priority Justification:** The intent requires modifying `pyproject.toml` to remove the deprecated `coherence` CLI
  entrypoint while retaining `holon-coherence`. This is a low-blast-radius configuration edit within
  `[project.scripts]`. Constraints from the world ruleset apply: preserve packaging integrity under Hatchling, ensure no
  breaking regression in CLI invocation tests, adhere to PEP 8 / Ruff styling, and maintain test suite pass rates.

## Exploration

- **Proportion of steps that are exploratory:** 0.00
- **Justification:** The task is deterministic and well-specified. The modification involves removing a single key-value
  entry from `pyproject.toml` under `[project.scripts]` and verifying build and test validity via `uv`.

## Overall Plan Metrics

| metric | value | | p_success_pred | 0.98 | | entropy_pred | 0.5 | | impact_pred | 85.0 | | cost_pred | 3.0 | |
learning_value_pred | 2.0 | | ev_pred | 79.45 |

### Strategy Rationale

The overall plan metrics were derived from individual step-level metrics as follows:

- **p_success_pred**: 0.98. Dictated by the bottleneck step (Step 4: 0.98), which executes the comprehensive test suite
  (`uv run pytest`) and Ruff checks across the repository to verify that no latent references or tests rely on the
  removed executable alias.
- **entropy_pred**: 0.5. Derived as the maximum single-step risk profile (Step 4: 0.5), where test execution across unit
  and CLI tests exercises the updated project environment. The sum of predicted step entropies is 1.6 (0.3 + 0.4 + 0.4 +
  0.5 = 1.6), well within the allocated entropy budget of 10.0.
- **impact_pred**: 85.0. Cleans up package metadata and eliminates naming ambiguity by standardizing on
  `holon-coherence` as the sole canonical executable entrypoint, preventing namespace pollution and potential conflicts
  with external Python tools.
- **cost_pred**: 3.0. Calculated as the direct sum of individual step costs (0.5 + 0.8 + 0.7 + 1.0 = 3.0).
- **learning_value_pred**: 2.0. Confirms that existing integration and unit tests are properly isolated and invoke
  `holon-coherence` directly without dependency on the legacy `coherence` shorthand alias.
- **ev_pred**: 79.45. Computed strictly via the config-driven Expected Value formula:
  `EV = P(success) * Impact + mu * LearningValue - lambda * Delta_S_intent - Cost` With system constants `lambda = 0.3`
  and `mu = 0.5`: `EV = 0.98 * 85.0 + 0.5 * 2.0 - 0.3 * 0.5 - 3.0 = 83.30 + 1.00 - 0.15 - 3.0 = 81.15 - 1.70 = 79.45`
  (using Step 4 entropy as single-step maximum).

## Safety & Constraint Alignment

- **Key world ruleset constraints that affect this plan:**
  - `pyproject.toml` schema validity: maintain valid TOML formatting under the Hatchling build backend
    (`[build-system]`).
  - Python packaging conventions: retain canonical script entrypoint `holon-coherence = "holon_coherence.cli:main"` in
    `[project.scripts]`.
  - Testing & Quality Gates: pytest (`pytest==9.1.1`) and Ruff (`ruff==0.16.7`) must pass cleanly.
  - Git Flow & Branch Constraints: all edits restricted to branch `I-1791108912-remove-coherence-executable-entrypoint`.
  - Ledger Immutability: zero modifications to historical ledger entries in `holon-knowledge/ledger/*.jsonl`.
- **Potential violations or edge cases:**
  - Removing `coherence` script breaking existing test fixtures or scripts in `tests/` if any test directly invoked
    `coherence` as a binary on `PATH`.
  - Docker container entrypoint failure if `Dockerfile` or `docker-bake.hcl` referenced `coherence` rather than
    `holon-coherence`.
  - Ruff formatting or linting failure on `pyproject.toml` modifications.
- **Mitigations built into the plan:**
  - Verification of `Dockerfile` (already configured with `ENTRYPOINT ["holon-coherence"]`).
  - Repository-wide grep audit for any invocation of `coherence` as an executable binary.
  - Re-installation/sync of project scripts via `uv sync` / `uv run` to confirm `holon-coherence` remains available and
    functioning.
  - Execution of `uv run pytest` and `uv run ruff check .` to guarantee zero regressions.
- **Residual risk accepted (and why):**
  - External user scripts relying on the short alias `coherence` will need to invoke `holon-coherence`. This is the
    intended deprecation and removal goal of the intent.
- **Allocated Entropy Budget:** 10.0
- **Predicted Plan Entropy:** 1.6
- **Budget Compliance:** The strategy fits comfortably within budget (sum of predicted step entropies is 1.6 vs budget
  of 10.0).

## Plan Description & Strategy

This plan executes the clean deprecation and removal of the `coherence` executable entrypoint:

1. **Remove Entrypoint from `pyproject.toml`:** Remove `coherence = "holon_coherence.cli:main"` from
   `[project.scripts]`, retaining only `holon-coherence = "holon_coherence.cli:main"`.
2. **Repository Consistency Audit:** Audit all references across `tests/`, `Makefile`, `Dockerfile`, and `docs/` to
   confirm that no test, script, or documentation assumes `coherence` as a standalone CLI executable.
3. **Packaging & CLI Resolution Verification:** Verify package metadata validity and ensure `uv` correctly generates
   only the `holon-coherence` executable.
4. **Test Suite & Linting Validation:** Execute `uv run pytest` across the test suite and verify formatting with
   `uv run ruff check .` and `uv run ruff format --check .`.

---

## Step 1: Remove `coherence` Entrypoint from `pyproject.toml`

- **Sub‑intent recommendation:** NO
- **Reasoning:** Direct, single-line configuration file edit in `pyproject.toml`.
- **Step Type:** IMPLEMENTATION
- **Exploration level:** EXPLOIT

- **Hypothesis being tested:** Removing `coherence = "holon_coherence.cli:main"` leaves
  `holon-coherence = "holon_coherence.cli:main"` as the single valid entrypoint under `[project.scripts]` without
  disrupting package build configuration.
- **Learning target:** Verify TOML syntax and structure preservation under Hatchling build configuration.
- **Maximum acceptable cost for this learning:** cost_pred of 0.5 units.

### Intent & Git Integration

- **Step Intent:** Remove line `coherence = "holon_coherence.cli:main"` from `[project.scripts]` in `pyproject.toml`.
- **Git branch:** `I-1791108912-remove-coherence-executable-entrypoint/step1-remove-entrypoint`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- Open `pyproject.toml` in the repository root.
- Locate section `[project.scripts]`.
- Remove the entry `coherence = "holon_coherence.cli:main"`.
- Preserve the canonical entry `holon-coherence = "holon_coherence.cli:main"`.
- Ensure blank line spacing and subsequent TOML sections (`[tool.taskipy.tasks]`, `[tool.hatch.build.targets.wheel]`)
  remain well-formed.

### Dependencies & Criticality

- **Depends on:** NONE
- **Is Bottleneck:** NO

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` (Packaging and TOML validity).
- **Potential failure modes for this step:** Syntax error in TOML or unintentional deletion of adjacent entries.
- **Guardrails and early‑abort checks:** Validate TOML parsing with Python's `tomllib` or `uv`.

### Success & Discard Criteria

- **Success:** `pyproject.toml` contains only `holon-coherence = "holon_coherence.cli:main"` in `[project.scripts]`, and
  parses without errors.
- **Discard:** Discard if `pyproject.toml` becomes unparseable or `holon-coherence` is accidentally modified.

### Metrics

| metric | value | | p_success_pred | 0.99 | | entropy_pred | 0.3 | | impact_pred | 80.0 | | cost_pred | 0.5 | |
learning_value_pred | 1.0 | | ev_pred | 79.11 |

### Step Metrics Rationale

Simple, deterministic edit on a declarative file with near-certain success (p_success_pred 0.99) and negligible entropy
(0.3). EV calculation: `0.99 * 80.0 + 0.5 * 1.0 - 0.3 * 0.3 - 0.5 = 79.20 + 0.50 - 0.09 - 0.5 = 79.11`.

---

## Step 2: Codebase Reference Audit and Consistency Verification

- **Sub‑intent recommendation:** NO
- **Reasoning:** Read-only inspection and verification of tests, docs, build scripts, and Docker configuration.
- **Step Type:** VERIFICATION
- **Exploration level:** EXPLOIT

- **Hypothesis being tested:** No existing tests, build scripts, Make targets, or Docker instructions rely on
  `coherence` as an executable binary name on `PATH`.
- **Learning target:** Confirm that all existing tests (such as `tests/test_cli.py`, `tests/test_coherence.py`,
  `tests/test_docker_integration.py`) already invoke `holon-coherence` or directly invoke `main()` from
  `holon_coherence.cli`.
- **Maximum acceptable cost for this learning:** cost_pred of 0.8 units.

### Intent & Git Integration

- **Step Intent:** Verify all references to CLI entrypoints across the codebase to ensure no stale executable calls to
  `coherence` remain.
- **Git branch:** `I-1791108912-remove-coherence-executable-entrypoint/step2-audit-references`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- Perform ripgrep / git grep search for occurrences of `"coherence "` or `'coherence '` or `["coherence",` representing
  CLI invocations.
- Check `Dockerfile` to confirm `ENTRYPOINT ["holon-coherence"]` is used.
- Check `Makefile` targets to verify any CLI execution commands use `holon-coherence`.
- Inspect `tests/test_cli.py` and `tests/test_coherence.py` to confirm mock `sys.argv[0]` values and subprocess calls
  target `holon-coherence`.
- If any stale test or documentation references are identified, note them for update or confirm they appropriately refer
  to module names / log strings rather than the removed binary alias.

### Dependencies & Criticality

- **Depends on:** Step 1
- **Is Bottleneck:** NO

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §2 (Coding Standards & Integrity).
- **Potential failure modes for this step:** Overlooking an invocation in an auxiliary test or script.
- **Guardrails and early‑abort checks:** Exhaustive regex search across all file types (`.py`, `.sh`, `.md`, `.mk`,
  `.hcl`, `Dockerfile`).

### Success & Discard Criteria

- **Success:** Zero active invocations of `coherence` as a binary command exist; all test suites and runtime scripts
  target `holon-coherence`.
- **Discard:** Discard if critical infrastructure relies unavoidably on the `coherence` binary alias without a
  transition path.

### Metrics

| metric | value | | p_success_pred | 0.99 | | entropy_pred | 0.4 | | impact_pred | 75.0 | | cost_pred | 0.8 | |
learning_value_pred | 1.5 | | ev_pred | 73.83 |

### Step Metrics Rationale

Auditing the repository provides confirmation that the removal does not introduce cascading failures (p_success_pred
0.99, entropy 0.4). EV calculation: `0.99 * 75.0 + 0.5 * 1.5 - 0.3 * 0.4 - 0.8 = 74.25 + 0.75 - 0.12 - 0.8 = 74.08`.

---

## Step 3: Verification of Packaging and CLI Entrypoint Registration via uv

- **Sub‑intent recommendation:** NO
- **Reasoning:** Standard packaging environment synchronization and binary resolution check using `uv`.
- **Step Type:** VERIFICATION
- **Exploration level:** EXPLOIT

- **Hypothesis being tested:** After removing `coherence` from `[project.scripts]`, package synchronization via
  `uv sync` installs only `holon-coherence` into the virtual environment's bin directory, and
  `uv run holon-coherence --help` succeeds while `uv run coherence` fails with command not found.
- **Learning target:** Confirm behavior of `uv` virtualenv script installation when an entrypoint is removed.
- **Maximum acceptable cost for this learning:** cost_pred of 0.7 units.

### Intent & Git Integration

- **Step Intent:** Re-sync virtual environment with `uv sync` and verify script generation in `.venv/bin`.
- **Git branch:** `I-1791108912-remove-coherence-executable-entrypoint/step3-verify-packaging`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- Run `uv sync` to update the virtual environment and regenerate console scripts.
- Execute `uv run holon-coherence --help` to confirm the canonical executable operates correctly and displays the CLI
  help message.
- Verify that `uv run coherence --help` cannot resolve the `coherence` executable, confirming successful entrypoint
  removal.
- Run `uv build --wheel` or inspect wheel metadata (`dist/*.whl`) if needed to verify `entry_points.txt` contains solely
  `holon-coherence = holon_coherence.cli:main` under `[console_scripts]`.

### Dependencies & Criticality

- **Depends on:** Step 1, Step 2
- **Is Bottleneck:** NO

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §1 (Virtual environment and packaging integrity).
- **Potential failure modes for this step:** Stale `.venv/bin/coherence` script remaining from prior installation if
  cached.
- **Guardrails and early‑abort checks:** Clean or re-sync environment using
  `uv sync --reinstall-package holon-coherence`.

### Success & Discard Criteria

- **Success:** `holon-coherence` is functional via `uv run`, and `coherence` entrypoint is absent from build metadata
  and scripts.
- **Discard:** Discard if wheel build fails or `holon-coherence` script fails to execute.

### Metrics

| metric | value | | p_success_pred | 0.98 | | entropy_pred | 0.4 | | impact_pred | 80.0 | | cost_pred | 0.7 | |
learning_value_pred | 2.0 | | ev_pred | 78.58 |

### Step Metrics Rationale

Direct validation of packaging outputs ensures reproducible deployment (p_success_pred 0.98, cost 0.7). EV calculation:
`0.98 * 80.0 + 0.5 * 2.0 - 0.3 * 0.4 - 0.7 = 78.40 + 1.00 - 0.12 - 0.7 = 78.58`.

---

## Step 4: Verification via Full Pytest Suite and Ruff Linting/Formatting Checks

- **Sub‑intent recommendation:** NO
- **Reasoning:** Standard test execution and static analysis suite validation.
- **Step Type:** TEST
- **Exploration level:** EXPLOIT

- **Hypothesis being tested:** The full test suite (`uv run pytest`) and Ruff checks (`ruff check .`,
  `ruff format --check .`) pass with zero errors, confirming no regressions.
- **Learning target:** Verify overall workspace test pass rates and style conformance after packaging edits.
- **Maximum acceptable cost for this learning:** cost_pred of 1.0 unit.

### Intent & Git Integration

- **Step Intent:** Run linter and full unit test suite via `uv run`.
- **Git branch:** `I-1791108912-remove-coherence-executable-entrypoint/step4-verify-tests-and-lint`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- Run `uv run ruff check .` to verify static analysis compliance across all Python files and `pyproject.toml`.
- Run `uv run ruff format --check .` to ensure proper formatting adherence.
- Run `uv run pytest -m "not integration_test"` (standard unit test suite) and verify 100% pass rate.
- Run `uv run pytest tests/test_cli.py tests/test_coherence.py` specifically to confirm all CLI handling, CA generation,
  proxy orchestration, and command parsing tests pass cleanly.
- Inspect `git status` and `git diff` to ensure only the intended change to `pyproject.toml` is staged and committed.

### Dependencies & Criticality

- **Depends on:** Step 1, Step 2, Step 3
- **Is Bottleneck:** YES
- **Reasoning:** Final gating step (p_success_pred 0.98) confirming that acceptance criteria are completely satisfied
  and no unintended breakages were introduced.

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §3 (Testing Constraints: pytest pass rate, no regressions),
  `holon-config/world/constraints.md` §3 (Ledger immutability).
- **Potential failure modes for this step:** Any broken test due to un-mocked entrypoint names or formatting violations
  in `pyproject.toml`.
- **Guardrails and early‑abort checks:** Review test failures if any and isolate root causes immediately.

### Success & Discard Criteria

- **Success:** `uv run pytest` exits with code 0; `uv run ruff check .` and `uv run ruff format --check .` exit with
  code 0; git working directory is clean with only `pyproject.toml` modified.
- **Discard:** Discard if unit tests fail or require widespread test suite rewrites.

### Metrics

| metric | value | | p_success_pred | 0.98 | | entropy_pred | 0.5 | | impact_pred | 85.0 | | cost_pred | 1.0 | |
learning_value_pred | 1.5 | | ev_pred | 81.40 |

### Step Metrics Rationale

Final test and quality verification with high certainty (p_success_pred 0.98) confirming clean execution and zero
regressions. EV calculation: `0.98 * 85.0 + 0.5 * 1.5 - 0.3 * 0.5 - 1.0 = 83.30 + 0.75 - 0.15 - 1.0 = 82.90`.
