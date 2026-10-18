# Plan for I-1792298329-coherence-make-tasks-pre-commit-and-audit

- **Plan ID:** P-1792298388-antigravity-agent-gemini-3.8-flash-medium
- **Parent Intent ID:** NONE
- **Agent:** antigravity-agent (version: 1.4.0)
- **Created At:** 2026-10-18T04:39:48.077Z

## Planner Autonomy Summary

- **Intent handling:** `ACCEPT_AS_IS`
- **Reframed intent (if applicable):** NONE
- **Exploration stance:** `conservative` — Well-specified Makefile alignment, pre-commit security hook, Australian English orthography, and audit report update.
- **Safety priority level:** `elevated`
- **Priority Justification:** Enforces credential leak prevention (Bean 0110) and build/lint hygiene parity (Bean 0116) without breaking existing CLI or proxy runtime contracts.

## Exploration

- **Proportion of steps that are exploratory:** 0.00
- **Justification:** All target behaviours and file paths are deterministic and backed by existing unit test patterns.

## Overall Plan Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.96  |
| entropy_pred        | 1.20  |
| impact_pred         | 88.00 |
| cost_pred           | 2.50  |
| learning_value_pred | 2.00  |
| ev_pred             | 82.62 |

### Strategy Rationale

Derived using `EV = P(success) * Impact + mu * LearningValue - lambda * Delta_S_intent - Cost` with `lambda = 0.3` and `mu = 0.5`:
`EV = 0.96 * 88.0 + 0.5 * 2.0 - 0.3 * 1.2 - 2.5 = 84.48 + 1.00 - 0.36 - 2.50 = 82.62`.

## Safety & Constraint Alignment

- **Key world ruleset constraints that affect this plan:** `holon-config/world/ruleset.md` and `holon-config/world/constraints.md`.
- **Potential violations or edge cases:** Prettier reformatting unrelated files or missing tool binaries on CI runners.
- **Mitigations built into the plan:** Use `--no-config` in Makefile Prettier checks and PATH stubs in unit tests.
- **Residual risk accepted (and why):** Low risk; all changes are verified by pytest and Ruff.
- **Allocated Entropy Budget:** 15.0
- **Predicted Plan Entropy:** 1.20
- **Budget Compliance:** The strategy fits within budget.

## Plan Description & Strategy

1. Align `Makefile` targets (`build-images` alias, `tools`, `lint`, `lint-json`, `lint-yaml`, `lint-shell`, `lint-md`, `pre-commit-check`) and format `.github/**/*.yml` (Bean 0116).
2. Implement `scripts/pre_commit_check.py` and `tests/test_pre_commit_check.py` to detect leaked credentials and disallowed scratch paths (Bean 0110).
3. Add `tests/test_makefile.py` testing `Makefile` targets and toolbelt inspection (Bean 0116).
4. Align documentation to Australian English (`en-AU`), update `holon-config/prompts/planner.template.md` to write plan files directly, and update `docs/audit_report.md` (Beans 0105, 0106).

---

## Step 1: Align Makefile Targets and Format Workflows (Bean 0116)

- **Sub-intent recommendation:** `NO`
- **Reasoning:** Self-contained Makefile and test update.
- **Step Type:** `IMPLEMENTATION`
- **Exploration level:** `EXPLOIT`

### Intent & Git Integration

- **Step Intent:** Add `build-images`, `tools`, `lint-*`, and `pre-commit-check` targets to `Makefile` and add `tests/test_makefile.py`.
- **Git branch:** `I-1792298329-coherence-make-tasks-pre-commit-and-audit/P-1792298388-antigravity-agent-gemini-3.8-flash-medium/_`
- **Sub-intent:** `NONE`

### Implementation Details

- Add `build-images: build-image` alias and `.PHONY` declarations in `Makefile`.
- Port `tools`, `lint`, `lint-json`, `lint-yaml`, `lint-shell`, `lint-md`, and `pre-commit-check` targets to `Makefile`.
- Format `.github/**/*.yml` with `npx prettier --no-config --write`.
- Add unit tests in `tests/test_makefile.py`.

### Dependencies & Criticality

- **Depends on:** NONE
- **Is Bottleneck:** YES

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/constraints.md`
- **Potential failure modes for this step:** Missing optional tools in CI environment.
- **Guardrails and early-abort checks:** Guard optional linters with `command -v` checks and `DRY_RUN` support.

### Success & Discard Criteria

- **Success:** `make lint` and `uv run pytest tests/test_makefile.py` pass cleanly.
- **Discard:** Cost exceeds 2x prediction.

### Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.98  |
| entropy_pred        | 0.40  |
| impact_pred         | 85.00 |
| cost_pred           | 0.80  |
| learning_value_pred | 0.50  |
| ev_pred             | 82.63 |

### Step Metrics Rationale

Deterministic Makefile target addition and unit test coverage.

---

## Step 2: Implement Pre-Commit Credential and Scratch File Detection (Bean 0110)

- **Sub-intent recommendation:** `NO`
- **Reasoning:** Standalone script and test suite.
- **Step Type:** `IMPLEMENTATION`
- **Exploration level:** `EXPLOIT`

### Intent & Git Integration

- **Step Intent:** Create `scripts/pre_commit_check.py` and `tests/test_pre_commit_check.py`.
- **Git branch:** `I-1792298329-coherence-make-tasks-pre-commit-and-audit/P-1792298388-antigravity-agent-gemini-3.8-flash-medium/_`
- **Sub-intent:** `NONE`

### Implementation Details

- Create `scripts/pre_commit_check.py` scanning staged files for Google AI, GitHub PAT, OpenAI, and Anthropic keys, and blocking `tmp/*`, `*.tmp`, `*.log`, `.index/*`.
- Create `tests/test_pre_commit_check.py` testing secret detection and disallowed path blocking.

### Dependencies & Criticality

- **Depends on:** Step 1
- **Is Bottleneck:** YES

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/constraints.md`
- **Potential failure modes for this step:** False positive regex matches on test files.
- **Guardrails and early-abort checks:** Construct test secret strings dynamically in unit tests.

### Success & Discard Criteria

- **Success:** `uv run pytest tests/test_pre_commit_check.py` passes.
- **Discard:** Cost exceeds 2x prediction.

### Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.98  |
| entropy_pred        | 0.40  |
| impact_pred         | 88.00 |
| cost_pred           | 0.90  |
| learning_value_pred | 1.00  |
| ev_pred             | 85.72 |

### Step Metrics Rationale

High security value with low implementation complexity.

---

## Step 3: Australian English Spelling and Audit Report Update (Beans 0105, 0106)

- **Sub-intent recommendation:** `NO`
- **Reasoning:** Documentation and prompt template refinement.
- **Step Type:** `DOCUMENTATION`
- **Exploration level:** `EXPLOIT`

### Intent & Git Integration

- **Step Intent:** Align docs with Australian English (`en-AU`), update `holon-config/prompts/planner.template.md`, and update `docs/audit_report.md`.
- **Git branch:** `I-1792298329-coherence-make-tasks-pre-commit-and-audit/P-1792298388-antigravity-agent-gemini-3.8-flash-medium/_`
- **Sub-intent:** `NONE`

### Implementation Details

- Update `docs/audit_report.md` and `README.md` with Australian English spelling and pre-commit documentation.
- Update `holon-config/prompts/planner.template.md` so the planner writes directly to `plans/{plan_id}.md`.

### Dependencies & Criticality

- **Depends on:** Step 2
- **Is Bottleneck:** NO

### Safety & Constraint Considerations

- **Relevant rules:** Preserve all programmatic symbols and API contracts.
- **Potential failure modes for this step:** Markdown formatting drift.
- **Guardrails and early-abort checks:** Run `make lint` and `uv run pytest`.

### Success & Discard Criteria

- **Success:** All unit tests and linters pass 100%.
- **Discard:** Cost exceeds 2x prediction.

### Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.99  |
| entropy_pred        | 0.40  |
| impact_pred         | 80.00 |
| cost_pred           | 0.80  |
| learning_value_pred | 0.50  |
| ev_pred             | 78.53 |

### Step Metrics Rationale

Low-entropy documentation and template alignment.
