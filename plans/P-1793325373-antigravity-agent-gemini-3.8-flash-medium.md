# Plan for I-1793325153-coherence-ab-test-docs-background-proxy-and-metrics

- **Plan ID:** P-1793325373-antigravity-agent-gemini-3.8-flash-medium
- **Parent Intent ID:** NONE
- **Agent:** antigravity-agent (version: 1.4.10)
- **Created At:** 2026-10-30T01:56:14.357Z

---

## Overall Plan Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.98  |
| entropy_pred        | 1.20  |
| impact_pred         | 7.50  |
| cost_pred           | 0.30  |
| learning_value_pred | 2.00  |
| ev_pred             | 7.69  |

---

## Step 1: Update Live Command A/B Testing Recipe in `docs/methods/README.md`

- **Step Intent & Git Integration:**
  - Sub-intent recommendation: Refactor manual host `mitmdump` execution instructions in `docs/methods/README.md` to prevent foreground terminal blocking and premature `set_proxy_mode()` execution.
  - Reasoning: In `docs/methods/README.md` (lines 29-35), `uv run mitmdump` was documented as a synchronous foreground command immediately preceding `holon-coherence ab-test --command`. In a single terminal shell, this blocks execution indefinitely. Furthermore, spawning mitmdump with a bare `&` introduces a socket readiness race where `set_proxy_mode()` silently returns `False` if the port or HTTP endpoints are not yet listening. Providing explicit two-terminal instructions or backgrounding with a readiness wait loop polling `http://127.0.0.1:8080/__holon__/health` (or `~/.holon/control/status`) ensures reliable command execution.
  - Step type: implementation
  - Exploration level: 0.00
  - Git branch: `I-1793325153-coherence-ab-test-docs-background-proxy-and-metrics`
- **Implementation Details:**
  - Edit [docs/methods/README.md](file:///home/holon/.holon-sandbox/workspace/docs/methods/README.md) lines 29-35:
    1. Update the code snippet for running host-side mitmdump before `holon-coherence ab-test --command`:
       - Show mitmdump started in a dedicated terminal or started in the background with an explicit readiness loop (e.g. `until curl -s -f http://127.0.0.1:8080/__holon__/health >/dev/null 2>&1; do sleep 0.2; done`).
       - Clarify why readiness synchronization is required (avoiding silent mode switch failures in `set_proxy_mode()`).
    2. Maintain Australian English (`optimised`, `behaviour`).
    3. Ensure Markdown formatting adheres to Prettier standards.
- **Dependencies & Criticality:**
  - Dependencies: None
  - Is bottleneck: No
- **Safety & Constraint Considerations:**
  - Relevant rules: Strictly scoped documentation change; zero modifications to source code (`src/`), `pyproject.toml`, or workflows.
  - Failure modes: Unchecked readiness check syntax or broken bash loops.
  - Guardrails: Use standard POSIX-compliant curl polling loop.
- **Success & Discard Criteria:**
  - Success: `docs/methods/README.md` contains clear, runnable instructions for starting mitmdump without shell blocking and with readiness verification.
  - Discard: If any source code files are touched, revert immediately.
- **Step Metrics Table:**

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.98  |
| entropy_pred        | 0.40  |
| impact_pred         | 7.00  |
| cost_pred           | 0.10  |
| learning_value_pred | 1.50  |
| ev_pred             | 7.39  |

- **Step Metrics Rationale:**
  $$\text{EV} = (0.98 \times 7.00) + (0.5 \times 1.50) - (0.3 \times 0.40) - 0.10 = 6.86 + 0.75 - 0.12 - 0.10 = 7.39$$
  Directly addresses documentation failure mode where users copy-paste blocking commands.

---

## Step 2: Update Live Command Recipe and Cumulative Metrics Clarification in `docs/token_reduction_ab_testing.md`

- **Step Intent & Git Integration:**
  - Sub-intent recommendation: Clarify in-memory proxy metrics reset behaviour across restarts in Tier 3, and update Tier 4 host-side mitmdump invocation with backgrounding/readiness polling.
  - Reasoning: In Tier 3 of [docs/token_reduction_ab_testing.md](file:///home/holon/.holon-sandbox/workspace/docs/token_reduction_ab_testing.md), `holon-coherence metrics --json` is executed after restarting the proxy (`holon-coherence stop && holon-coherence start -d`). Operators frequently misunderstand this output because `CumulativeMetrics` is an in-memory counter that clears on process restart; thus, post-restart inspection only reflects the second (optimised) pass. Clarifying this caveat and pointing to `holon-coherence ab-test --trace-file ~/.holon/logs/transactions.jsonl` provides the comprehensive two-pass paired scorecard. In Tier 4, mitmdump must similarly be updated to use backgrounding with readiness polling or separate terminal execution to prevent command blocking.
  - Step type: implementation
  - Exploration level: 0.00
  - Git branch: `I-1793325153-coherence-ab-test-docs-background-proxy-and-metrics`
- **Implementation Details:**
  - Edit [docs/token_reduction_ab_testing.md](file:///home/holon/.holon-sandbox/workspace/docs/token_reduction_ab_testing.md):
    1. Around lines 105-115 (Tier 3 step 5 / live cumulative totals inspection):
       - Explicitly explain that `CumulativeMetrics` resides in memory and resets whenever the proxy container restarts.
       - Note that `holon-coherence metrics --json` run after `holon-coherence stop && holon-coherence start -d` reports only the second (optimised) pass unless captured prior to the restart.
       - Direct readers to `holon-coherence ab-test --trace-file ~/.holon/logs/transactions.jsonl` to generate the authentic paired baseline-vs-optimised scorecard reading across both passes from the append-only JSONL log.
    2. Around lines 120-130 (Tier 4 / Option 2 live command execution):
       - Update the host-side `mitmdump` snippet to run in a separate terminal or backgrounded with a readiness wait loop polling `http://127.0.0.1:8080/__holon__/health` or `~/.holon/control/status` prior to invoking `holon-coherence ab-test --command`.
    3. Ensure spelling adheres to Australian English (`optimised`, `prioritised`).
- **Dependencies & Criticality:**
  - Dependencies: Step 1
  - Is bottleneck: No
- **Safety & Constraint Considerations:**
  - Relevant rules: Preserves authentic telemetry invariants (Rule 1); no synthetic benchmarking data introduced.
  - Failure modes: Inaccurate explanation of `CumulativeMetrics` lifecycle.
  - Guardrails: Cross-check against `src/holon_coherence/mitm_addon.py` where `self.metrics = CumulativeMetrics()` is instanced anew on addon initialisation.
- **Success & Discard Criteria:**
  - Success: Tier 3 and Tier 4 documentation recipes in `docs/token_reduction_ab_testing.md` accurately convey process restart metrics semantics and provide non-blocking proxy readiness patterns.
  - Discard: If edits deviate into code changes or non-en-AU phrasing.
- **Step Metrics Table:**

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.98  |
| entropy_pred        | 0.50  |
| impact_pred         | 7.50  |
| cost_pred           | 0.10  |
| learning_value_pred | 2.00  |
| ev_pred             | 8.10  |

- **Step Metrics Rationale:**
  $$\text{EV} = (0.98 \times 7.50) + (0.5 \times 2.00) - (0.3 \times 0.50) - 0.10 = 7.35 + 1.00 - 0.15 - 0.10 = 8.10$$
  High impact and learning value by clarifying telemetry data provenance and preventing user confusion regarding in-memory metrics vs trace-file logs.

---

## Step 3: Verification, Prettier Formatting, and Scope Validation

- **Step Intent & Git Integration:**
  - Sub-intent recommendation: Validate formatting hygiene, run markdown linters, execute pytest test suite, and ensure strict file scope isolation.
  - Reasoning: Acceptance criteria require passing `uv run pytest` and `npx prettier --check`, with changes strictly limited to `docs/methods/README.md` and `docs/token_reduction_ab_testing.md`.
  - Step type: verification
  - Exploration level: 0.00
  - Git branch: `I-1793325153-coherence-ab-test-docs-background-proxy-and-metrics`
- **Implementation Details:**
  - Execute:
    1. `npx prettier --write "docs/**/*.md"` and `npx prettier --check "docs/**/*.md"` to ensure markdown complies with repository formatting rules.
    2. `uv run pytest` to ensure no regression in documentation tests or repository hygiene checks (`tests/test_repo_hygiene.py`).
    3. `git diff --stat` to verify that ONLY `docs/methods/README.md` and `docs/token_reduction_ab_testing.md` (and the plan file) were modified.
- **Dependencies & Criticality:**
  - Dependencies: Step 1, Step 2
  - Is bottleneck: Yes
- **Safety & Constraint Considerations:**
  - Relevant rules: Zero modification to `pyproject.toml`, `src/`, or `.github/` workflows.
  - Failure modes: Formatting mismatches flagged by Prettier CI gate.
  - Guardrails: Run Prettier formatter directly before committing.
- **Success & Discard Criteria:**
  - Success: Pytest passes cleanly, Prettier check passes with zero warnings/errors, git diff is strictly confined to target documentation files.
  - Discard: If unexpected files are touched, revert non-scoped changes.
- **Step Metrics Table:**

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.99  |
| entropy_pred        | 0.30  |
| impact_pred         | 6.50  |
| cost_pred           | 0.10  |
| learning_value_pred | 1.00  |
| ev_pred             | 6.75  |

- **Step Metrics Rationale:**
  $$\text{EV} = (0.99 \times 6.50) + (0.5 \times 1.00) - (0.3 \times 0.30) - 0.10 = 6.435 + 0.50 - 0.09 - 0.10 = 6.745 \approx 6.75$$
  Standard verification gate providing deterministic confirmation of acceptance criteria.

---

## Strategy Rationale

Overall plan metrics are computed using the physics-driven Expected Value (EV) formula:
$$\text{EV} = P(\text{success}) \times \text{Impact} + \mu \times \text{LearningValue} - \lambda \times \Delta S_{\text{intent}} - \text{Cost}$$

With baseline framework parameters $\lambda = 0.3$ and $\mu = 0.5$:
$$\text{EV} = (0.98 \times 7.50) + (0.5 \times 2.00) - (0.3 \times 1.20) - 0.30 = 7.35 + 1.00 - 0.36 - 0.30 = 7.69$$

The high expected value ($7.69$) reflects immediate operator impact with negligible execution cost and risk. By addressing the blocking foreground invocation of `mitmdump` and adding explicit readiness verification, copy-paste execution of the live command A/B test recipe becomes reliable. Furthermore, clarifying the lifecycle of in-memory `CumulativeMetrics` prevents erroneous evaluation of optimization results, steering operators towards the authoritative append-only `transactions.jsonl` trace scorecard.

---

## Planner Autonomy Summary

- **Intent handling:** `ACCEPT_AS_IS`
- **Reframed intent (if applicable):** NONE
- **Exploration stance:** Pure exploitation. The issue diagnosis and required updates are fully deterministic, bounded to two documentation files (`docs/methods/README.md` and `docs/token_reduction_ab_testing.md`). No speculative architecture or codebase refactoring is necessary.
- **Safety priority level:** standard
- **Priority Justification:** Changes are exclusively documentation edits with zero risk of breaking runtime proxy functionality or existing unit/integration test suites.

---

## Exploration

- **Proportion of steps that are exploratory:** 0.00
- **Justification:** The operational behaviour of `mitmdump`, `set_proxy_mode()`, readiness endpoints (`/__holon__/health`, `~/.holon/control/status`), and `CumulativeMetrics` lifecycle in `mitm_addon.py` is well-characterized in the codebase. No exploratory steps are required.

---

## Safety & Constraint Alignment

- **Key world ruleset constraints that affect this plan:**
  - Rule 1 (Zero Synthetic / Mock Data): Documentation examples must use real CLI commands and authentic trace logs (`~/.holon/logs/transactions.jsonl`), preserving strict telemetry invariants.
  - Strict Repository Scope: Do not modify `pyproject.toml`, `src/`, or `.github/` workflows.
  - Australian English (en-AU): All documentation additions and modifications must use en-AU spelling (e.g. `optimised`, `behaviour`).
  - Linting & Prettier Formatting: All markdown files must pass `npx prettier --check` and `uv run pytest`.
- **Potential violations or edge cases:**
  - Introducing non-standard curl or shell polling syntax that fails in non-bash POSIX shells.
  - Accidental formatting drift or trailing whitespace across untargeted sections of the documentation files.
- **Mitigations built into the plan:**
  - Use standard POSIX-compatible loop constructs (`until curl -s -f ...; do sleep 0.2; done`).
  - Run Prettier check and review `git diff` before finalizing.
- **Residual risk accepted (and why):**
  - Zero residual runtime risk, as no executable application code is modified.
- **Allocated Entropy Budget:** 15.0
- **Predicted Plan Entropy:** 1.20
- **Budget Compliance:** Full compliance ($1.20 \le 15.0$).

---

## Plan Description & Strategy

1. **Step 1: Update Live Command A/B Testing Recipe in `docs/methods/README.md`**:
   Update lines 29-39 in `docs/methods/README.md` so that the manual `mitmdump` command is either shown in a separate terminal or backgrounded with a readiness wait loop before `holon-coherence ab-test --command` executes.
2. **Step 2: Update Live Command Recipe and Cumulative Metrics Clarification in `docs/token_reduction_ab_testing.md`**:
   Update lines 105-115 to clarify that `CumulativeMetrics` resets on proxy restart and point to `ab-test --trace-file` for paired scorecards. Update lines 120-130 to use non-blocking/readiness-checked `mitmdump` startup.
3. **Step 3: Verification, Prettier Formatting, and Scope Validation**:
   Format markdown with Prettier, run repository test suites with pytest, and verify strict diff scope.
