# Plan for I-1791374885-audit-holon-coherence-architecture-bugs

- **Plan ID:** P-1791374900-antigravity-agent-gemini-3.8-flash-medium
- **Parent Intent ID:** I-1791374885-audit-holon-coherence-architecture-bugs
- **Agent:** antigravity-agent/gemini-3.8-flash-medium (version: 1.1.22)
- **Created At:** 2026-10-07T12:08:25Z

## Planner Autonomy Summary

- **Intent handling:** ACCEPT_AS_IS
- **Reframed intent (if applicable):** NONE
- **Exploration stance:** balanced with targeted empirical inspection of `holon_coherence` runtime behaviors, certificate generation boundaries, MITM proxy streaming, caching serialization safety, and test suite execution without making destructive changes or violating ledger invariants.
- **Safety priority level:** elevated
- **Priority Justification:** Triggered by `holon-config/world/ruleset.md` §1 & §2 (Python runtime compliance `==3.13.*`, workspace isolation, strict PEP 8 formatting, explicit static typing with `typing` module, docstring maintenance), `holon-config/world/ruleset.md` §3 (Testing Constraints: hermetic test execution, test declared modifications), `holon-config/world/constraints.md` §1 (Git Flow: branch prefix isolation, rebase discipline), `holon-config/world/constraints.md` §2 (Sandbox containment: subprocess and filesystem containment, security boundary verification), `holon-config/world/constraints.md` §3 (Ledger Immutability: zero modifications to historical ledger entries), and Bean 0045 architectural objectives.

## Exploration

- **Proportion of steps that are exploratory:** 0.50
- **Justification:** Steps 2, 3, and 4 incorporate balanced exploration to inspect security trust boundaries (CA generation, MITM traffic handling, credential masking), uncover edge-case concurrency or deserialization bugs in hybrid caching and context reduction, and evaluate test suite gaps against real failure modes.

## Overall Plan Metrics

| metric | value |
| p_success_pred | 0.95 |
| entropy_pred | 0.8 |
| impact_pred | 92.0 |
| cost_pred | 8.0 |
| learning_value_pred | 6.0 |
| ev_pred | 82.16 |

### Strategy Rationale

The overall plan metrics were derived from individual step-level metrics as follows:

- **p_success_pred**: 0.95. Dictated by the bottleneck step (Step 3: 0.95), where complex asynchronous interactions across proxy addons, payload cleaning, and hybrid caching are audited for subtle race conditions and memory leaks.
- **entropy_pred**: 0.8. Derived as the maximum single-step risk profile (Step 3: 0.8), where runtime concurrency patterns and error handling fallbacks are scrutinized. The sum of predicted step entropies is 2.8 (`0.4 + 0.6 + 0.8 + 0.5 + 0.3 + 0.2 = 2.8`), well within the allocated entropy budget of 15.0.
- **impact_pred**: 92.0. Resolves Bean 0045 by establishing an exhaustive baseline of architectural cohesion, cryptographic and network security boundaries, latent bugs, and testing quality, producing a high-value audit artifact (`docs/audit_report.md`) and actionable follow-up bean definitions.
- **cost_pred**: 8.0. Calculated as the direct sum of individual step costs (`1.0 + 1.5 + 2.0 + 1.5 + 1.5 + 0.5 = 8.0`).
- **learning_value_pred**: 6.0. Epistemic gain from formalizing vulnerability surfaces in MITM sidecars, auditing token reduction algorithms, and isolating architectural debt across the proxy and host-local subsystems.
- **ev_pred**: 82.16. Computed strictly via the config-driven Expected Value formula:
  `EV = P(success) * Impact + mu * LearningValue - lambda * Delta_S_intent - Cost`. With system constants `lambda = 0.3` and `mu = 0.5` loaded from `holon-config/metrics/ev_config.json`:
  `EV = 0.95 * 92.0 + 0.5 * 6.0 - 0.3 * 0.8 - 8.0 = 87.40 + 3.00 - 0.24 - 8.0 = 82.16`.

## Safety & Constraint Alignment

- **Key world ruleset constraints that affect this plan:**
  - `holon-config/world/ruleset.md` §1 (Runtime & Environment Specification: Python target `==3.13.*`, workspace management via `uv`).
  - `holon-config/world/ruleset.md` §2 (Coding Conventions & Standards: PEP 8 compliance, static typing with `typing` module, docstring maintenance).
  - `holon-config/world/ruleset.md` §3 (Testing Constraints: hermetic test isolation, zero unstaged regressions).
  - `holon-config/world/constraints.md` §1 (Git Flow: isolated branches, clean commit boundaries).
  - `holon-config/world/constraints.md` §2 (Sandbox Containment: filesystem boundary protection, zero unvetted subprocess execution).
  - `holon-config/world/constraints.md` §3 (Ledger Immutability: zero edits or truncations to historical ledger entries).
  - `docs/safety.md` §1 & §2 (Git as safety boundary, sandboxing mandatory for execution).
- **Potential violations or edge cases:**
  - Executing live network calls during proxy or certificate inspection that violate sandbox isolation.
  - Modifying existing functional code during an audit step rather than keeping the intent purely focused on analysis and reporting.
  - Inadvertently writing sensitive telemetry or proxy secrets into `docs/audit_report.md`.
  - Violating ledger immutability in `holon-knowledge/ledger/`.
- **Mitigations built into the plan:**
  - Strict read-only audit posture across all source modules (`src/holon_coherence/`) and documentation files (`docs/`).
  - Run tests and static analysis exclusively through hermetic local commands (`uv run pytest`, `uv run ruff check`).
  - Explicitly sanitize all code snippets, paths, and token examples before inclusion in `docs/audit_report.md`.
  - Maintain absolute ledger immutability; do not modify historical ledger entries.
- **Residual risk accepted (and why):**
  - Static audit can identify suspected race conditions or edge cases that require dynamic benchmark stress tests to reproduce; these will be categorized as candidate follow-up beans.
- **Allocated Entropy Budget:** 15.0
- **Predicted Plan Entropy:** 2.8
- **Budget Compliance:** The strategy fits within budget (Predicted Plan Entropy sum of 2.8 is well below the 15.0 allocated budget).

## Plan Description & Strategy

This plan implements Bean 0045 by executing a structured 6-step audit across `holon-coherence`:

1. **Step 1: Architecture, Modularity & Design Pattern Audit:** Evaluate component coupling, separation of concerns, and alignment between implementation (`src/holon_coherence/`) and design specifications (`docs/token_reduction_architecture.md`, `docs/methods/*`).
2. **Step 2: Security & Trust Boundary Audit:** Audit CA generation (`ca_generator.py`), MITM interception security (`mitm_addon.py`), host subprocess execution (`host_local.py`), and credential protection across telemetry and logs.
3. **Step 3: Concurrency, Performance & Bug Detection Audit:** Scrutinize `hybrid_cache.py`, `payload_cleaner.py`, `openbrain_memory.py`, and `ringer_orchestrator.py` for race conditions, resource leaks, unhandled exceptions, and edge-case bugs.
4. **Step 4: Test Suite & Build Pipeline Quality Audit:** Assess coverage, hermeticity, and resilience across `tests/` and build configurations (`Dockerfile`, `docker-bake.hcl`, `Makefile`, `build_image.sh`).
5. **Step 5: Audit Report Synthesis & Follow-up Bean Definition:** Author `docs/audit_report.md` detailing findings with severity ratings (Critical, High, Medium, Low), concrete recommendations, and structured Bean proposals.
6. **Step 6: End-to-End Verification & Formatting Validation:** Validate Markdown formatting (`npx prettier --check docs/audit_report.md`), test suite execution, and repository cleanliness.

---

## Step 1: Architecture, Modularity & Design Pattern Audit

- **Sub‑intent recommendation:** NO
- **Reasoning:** Static analysis and architectural review of existing Python modules against documentation.
- **Step Type:** AUDIT
- **Exploration level:** EXPLOIT

### Intent & Git Integration

- **Step Intent:** Evaluate codebase architecture across `src/holon_coherence/`, analyzing modularity, abstraction boundaries, dependency injection, and consistency with `docs/token_reduction_architecture.md`.
- **Git branch:** `I-1791374885-audit-holon-coherence-architecture-bugs/P-1791374900-antigravity-agent-gemini-3.8-flash-medium/E-architecture-audit/_`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- Review `src/holon_coherence/__init__.py` and `cli.py` for clean CLI dispatch, entrypoint coupling, and configuration propagation.
- Analyze the relationship between `mitm_addon.py`, `payload_cleaner.py`, and `hybrid_cache.py` to check for tight coupling, circular imports, or leaked responsibilities.
- Cross-reference component implementations with architecture documentation in `docs/token_reduction_architecture.md`, `docs/methods/context_cleaning.md`, `docs/methods/local_cache_layer.md`, `docs/methods/prompt_cache_optimization.md`, and `docs/methods/ringer_framework.md`.
- Inspect `openbrain_memory.py` and `rag_indexer.py` for architectural coherence with the token reduction pipeline.
- Identify design smells: global mutable state, duplicated logic between CLI and library code, and rigid hardcoded parameters.

### Dependencies & Criticality

- **Depends on:** NONE
- **Is Bottleneck:** NO

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §1 & §2, `docs/safety.md` §1.
- **Potential failure modes for this step:** Misidentifying intentional architectural tradeoffs as anti-patterns.
- **Guardrails and early‑abort checks:** Validate architectural rationale against documented design decisions in `docs/methods/`.

### Success & Discard Criteria

- **Success:** Complete architectural evaluation documenting module coupling, cohesion, design patterns, and documentation divergence.
- **Discard:** Discard findings that contradict explicitly documented design requirements without architectural merit.

### Metrics

| metric | value |
| p_success_pred | 0.98 |
| entropy_pred | 0.4 |
| impact_pred | 80.0 |
| cost_pred | 1.0 |
| learning_value_pred | 4.0 |
| ev_pred | 79.28 |

### Step Metrics Rationale

- High `p_success_pred` (0.98) and low `entropy_pred` (0.4) as this is a non-invasive analytical step.
- Derivation: `EV = 0.98 * 80.0 + 0.5 * 4.0 - 0.3 * 0.4 - 1.0 = 78.40 + 2.00 - 0.12 - 1.0 = 79.28`.

---

## Step 2: Security & Trust Boundary Audit

- **Sub‑intent recommendation:** NO
- **Reasoning:** Critical security review focusing on PKI, network interception, subprocesses, and data redaction.
- **Step Type:** AUDIT
- **Exploration level:** BALANCED

- **Hypothesis being tested:** The MITM proxy and CA generator may leak private keys, store CA certificates with overly permissive filesystem permissions, or fail to sanitize API credentials in telemetry streams.
- **Learning target:** Identify specific security boundary breaches in `ca_generator.py`, `mitm_addon.py`, `host_local.py`, and telemetry plans.
- **Maximum acceptable cost for this learning:** 2.0

### Intent & Git Integration

- **Step Intent:** Conduct a deep-dive security audit of CA certificate generation, TLS interception, subprocess execution, credential redaction, and data persistence.
- **Git branch:** `I-1791374885-audit-holon-coherence-architecture-bugs/P-1791374900-antigravity-agent-gemini-3.8-flash-medium/E-security-audit/_`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- In `src/holon_coherence/ca_generator.py`, inspect private key generation, key size/curve algorithms, file permissions (ensuring `0600` for keys), certificate expiration, and CA trust store installation routines.
- In `src/holon_coherence/mitm_addon.py`, inspect upstream TLS certificate verification (`ssl_insecure` flags), request/response body interception, streaming vs buffering security, and header logging.
- In `src/holon_coherence/host_local.py`, inspect subprocess spawning commands, shell execution (`shell=True` hazards), input sanitization, environment variable propagation, and privilege containment.
- In `src/holon_coherence/payload_cleaner.py` and `docs/mitm_telemetry_metrics_plan.md`, check for credential exposure (Authorization headers, API keys, Bearer tokens) in logged metrics or cached entries.
- Review file persistence in `hybrid_cache.py` and `openbrain_memory.py` for insecure serialization (e.g. raw `pickle` vulnerabilities, path traversal risks).

### Dependencies & Criticality

- **Depends on:** Step 1
- **Is Bottleneck:** NO

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/constraints.md` §2 (Sandbox containment), `docs/safety.md` §2.
- **Potential failure modes for this step:** Incomplete coverage of custom serialization or insecure subprocess invocations.
- **Guardrails and early‑abort checks:** Trace every external process call and file write to confirm strict permission masks and sanitized arguments.

### Success & Discard Criteria

- **Success:** Detailed security assessment identifying all vulnerabilities, severity scores (CVSS/CWE alignment where relevant), and remediation guidance.
- **Discard:** Discard if security analysis relies on unverified theoretical concerns without code backing.

### Metrics

| metric | value |
| p_success_pred | 0.96 |
| entropy_pred | 0.6 |
| impact_pred | 95.0 |
| cost_pred | 1.5 |
| learning_value_pred | 5.5 |
| ev_pred | 91.77 |

### Step Metrics Rationale

- High impact (95.0) as security vulnerabilities in MITM proxies and CA handling directly affect host system integrity.
- Derivation: `EV = 0.96 * 95.0 + 0.5 * 5.5 - 0.3 * 0.6 - 1.5 = 91.20 + 2.75 - 0.18 - 1.5 = 91.77`.

---

## Step 3: Concurrency, Performance & Bug Detection Audit

- **Sub‑intent recommendation:** NO
- **Reasoning:** In-depth bug detection across asynchronous and stateful cache/proxy components.
- **Step Type:** AUDIT
- **Exploration level:** BALANCED

- **Hypothesis being tested:** Concurrency bottlenecks, race conditions in hybrid cache eviction, unhandled streaming errors in mitmproxy hooks, and memory leaks in payload cleaning exist in core modules.
- **Learning target:** Uncover latent bugs, deadlocks, race conditions, and unhandled edge cases across async workflows.
- **Maximum acceptable cost for this learning:** 2.5

### Intent & Git Integration

- **Step Intent:** Detect operational bugs, concurrency flaws, memory/socket leaks, and performance bottlenecks across `src/holon_coherence/`.
- **Git branch:** `I-1791374885-audit-holon-coherence-architecture-bugs/P-1791374900-antigravity-agent-gemini-3.8-flash-medium/E-bug-audit/_`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- In `src/holon_coherence/hybrid_cache.py`, inspect cache key collision vectors, lock contention, multi-threaded access safety, TTL expiration races, and disk eviction handling.
- In `src/holon_coherence/payload_cleaner.py`, audit regex compilation efficiency, regex catastrophic backtracking (ReDoS) vulnerabilities, and handling of malformed JSON or binary streaming chunks.
- In `src/holon_coherence/ringer_orchestrator.py`, analyze state transitions, retry loops, unhandled timeout exceptions, process lifecycles, and zombie child cleanup.
- In `src/holon_coherence/openbrain_memory.py` and `rag_indexer.py`, check index consistency under concurrent read/write, embedding model connection management, and memory consumption.
- Verify error handling and logging across all functions to ensure exceptions do not silently suppress failures or crash the proxy addon.

### Dependencies & Criticality

- **Depends on:** Step 1, Step 2
- **Is Bottleneck:** YES

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §2, `docs/safety.md` §1.
- **Potential failure modes for this step:** Concurrency analysis missing subtle race conditions without stress profiling.
- **Guardrails and early‑abort checks:** Inspect thread locks, asyncio loop assumptions, and resource release blocks (`finally` clauses, context managers).

### Success & Discard Criteria

- **Success:** Catalogue of functional bugs, concurrency risks, resource leak vectors, and performance bottlenecks with code references.
- **Discard:** Discard speculative issues that are already guarded by language primitives or framework guarantees.

### Metrics

| metric | value |
| p_success_pred | 0.95 |
| entropy_pred | 0.8 |
| impact_pred | 90.0 |
| cost_pred | 2.0 |
| learning_value_pred | 6.0 |
| ev_pred | 86.26 |

### Step Metrics Rationale

- Bottleneck step with `p_success_pred` of 0.95 and `entropy_pred` of 0.8 due to complex asynchronous code paths.
- Derivation: `EV = 0.95 * 90.0 + 0.5 * 6.0 - 0.3 * 0.8 - 2.0 = 85.50 + 3.00 - 0.24 - 2.0 = 86.26`.

---

## Step 4: Test Suite & Build Pipeline Quality Audit

- **Sub‑intent recommendation:** NO
- **Reasoning:** Evaluation of test quality, code coverage gaps, containerization, and build scripts.
- **Step Type:** AUDIT
- **Exploration level:** BALANCED

- **Hypothesis being tested:** Existing unit and integration tests miss critical error paths, mock out genuine failure points, or suffer from non-hermetic assumptions in container builds.
- **Learning target:** Map test coverage gaps against audited components and evaluate build reliability across `Makefile`, `Dockerfile`, and `docker-bake.hcl`.
- **Maximum acceptable cost for this learning:** 2.0

### Intent & Git Integration

- **Step Intent:** Audit testing hygiene, assertion coverage, test flakiness risks, and container build configuration across `tests/` and project build tooling.
- **Git branch:** `I-1791374885-audit-holon-coherence-architecture-bugs/P-1791374900-antigravity-agent-gemini-3.8-flash-medium/E-test-pipeline-audit/_`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- Review `tests/test_coherence.py`, `tests/test_cli.py`, and `tests/test_host_local.py` to identify uncovered modules, unexercised error handlers, and over-mocked dependencies.
- Inspect `tests/test_docker_integration.py`, `tests/test_build_image.py`, and `tests/test_makefile.py` for fixture isolation, environment contamination, and platform assumptions.
- Audit `Dockerfile`, `docker-bake.hcl`, `build_image.sh`, and `environment.yml` for multi-stage caching, security best practices (non-root user, minimal base image), reproducibility, and dependency lock enforcement.
- Run `uv run pytest` to inspect test suite execution times, warnings, deprecations, and test markers.
- Identify missing regression test categories: fuzzing, network disconnect simulation, and cache corruptions.

### Dependencies & Criticality

- **Depends on:** Step 1, Step 3
- **Is Bottleneck:** NO

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §3 (Testing Constraints), `apps/sandbox-executor/docs/hermetic_testing.md`.
- **Potential failure modes for this step:** Docker tests attempting to connect to external registries or uncontained Docker daemons.
- **Guardrails and early‑abort checks:** Ensure test inspection uses hermetic static analysis and local test execution flags.

### Success & Discard Criteria

- **Success:** Detailed test matrix detailing coverage gaps, mock fidelity risks, containerization audit findings, and CI pipeline recommendations.
- **Discard:** Discard if build analysis is based on obsolete container specs.

### Metrics

| metric | value |
| p_success_pred | 0.97 |
| entropy_pred | 0.5 |
| impact_pred | 85.0 |
| cost_pred | 1.5 |
| learning_value_pred | 4.5 |
| ev_pred | 83.05 |

### Step Metrics Rationale

- High `p_success_pred` (0.97) and moderate impact (85.0) for standard test suite and build tooling inspection.
- Derivation: `EV = 0.97 * 85.0 + 0.5 * 4.5 - 0.3 * 0.5 - 1.5 = 82.45 + 2.25 - 0.15 - 1.5 = 83.05`.

---

## Step 5: Audit Report Synthesis & Follow-up Bean Definition

- **Sub‑intent recommendation:** NO
- **Reasoning:** Direct synthesis of all audit findings into `docs/audit_report.md` and structured bean proposals.
- **Step Type:** DOCS
- **Exploration level:** EXPLOIT

### Intent & Git Integration

- **Step Intent:** Author the comprehensive audit report in `docs/audit_report.md` synthesizing architectural, security, bug, and quality findings, and defining actionable follow-up beans.
- **Git branch:** `I-1791374885-audit-holon-coherence-architecture-bugs/P-1791374900-antigravity-agent-gemini-3.8-flash-medium/E-report-synthesis/_`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- Create `docs/audit_report.md` following standard technical audit report structure:
  - Executive Summary & Scope Overview.
  - Architectural Assessment (modularity, coupling, adherence to specifications in `docs/`).
  - Security & Trust Boundary Review (PKI/CA, TLS MITM, subprocesses, credentials, data at rest).
  - Bug, Concurrency & Reliability Findings (classified by severity: Critical, High, Medium, Low).
  - Test Suite, Build & CI Quality Assessment (coverage gaps, containerization, test hermeticity).
  - Actionable Remediation Roadmap & Candidate Bean Proposals (e.g., Bean: CA Permission Hardening, Bean: Cache Concurrency Hardening, Bean: Integration Test Expansion).
- Ensure all findings include precise file links, symbol references, impact explanations, and concrete remediation steps.
- Review document for clarity, actionable recommendations, and absence of leaked secrets.

### Dependencies & Criticality

- **Depends on:** Steps 1, 2, 3, 4
- **Is Bottleneck:** NO

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §2, `docs/safety.md` §1.
- **Potential failure modes for this step:** Incomplete report structure or missing actionable follow-up bean definitions.
- **Guardrails and early‑abort checks:** Validate that each finding has an unambiguous severity rating and concrete remediation instructions.

### Success & Discard Criteria

- **Success:** `docs/audit_report.md` is fully drafted, well-structured, comprehensive, and includes clear candidate bean specifications.
- **Discard:** Discard if report lacks specificity or omits key audited components.

### Metrics

| metric | value |
| p_success_pred | 0.98 |
| entropy_pred | 0.3 |
| impact_pred | 92.0 |
| cost_pred | 1.5 |
| learning_value_pred | 5.0 |
| ev_pred | 90.07 |

### Step Metrics Rationale

- Very high `p_success_pred` (0.98) and impact (92.0) for delivering the primary requested deliverable.
- Derivation: `EV = 0.98 * 92.0 + 0.5 * 5.0 - 0.3 * 0.3 - 1.5 = 90.16 + 2.50 - 0.09 - 1.5 = 90.07`.

---

## Step 6: End-to-End Verification & Formatting Validation

- **Sub‑intent recommendation:** NO
- **Reasoning:** Validation phase ensuring markdown hygiene, test suite pass status, and clean git state.
- **Step Type:** TEST
- **Exploration level:** EXPLOIT

### Intent & Git Integration

- **Step Intent:** Execute markdown formatting validation on `docs/audit_report.md`, run repository test suite to confirm zero regressions, and verify working directory cleanliness.
- **Git branch:** `I-1791374885-audit-holon-coherence-architecture-bugs/P-1791374900-antigravity-agent-gemini-3.8-flash-medium/E-verification/_`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- Run markdown hygiene check: `npx prettier --check docs/audit_report.md` (and format if needed via `npx prettier --write docs/audit_report.md`).
- Run code quality checks: `uv run ruff check .` and `uv run ruff format --check .`.
- Run pytest suite: `uv run pytest`.
- Verify `git status` to confirm only the expected report file `docs/audit_report.md` and planned changes are staged.

### Dependencies & Criticality

- **Depends on:** Step 5
- **Is Bottleneck:** NO

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §1, §2, §3, `docs/safety.md` §1.
- **Potential failure modes for this step:** Prettier formatting discrepancies in markdown tables or bulleted lists.
- **Guardrails and early‑abort checks:** Re-format markdown via prettier if validation flags formatting divergence.

### Success & Discard Criteria

- **Success:** Markdown validation passes, all tests exit with return code 0, and repository state is clean.
- **Discard:** Discard if unstaged or unrelated modifications remain in the workspace.

### Metrics

| metric | value |
| p_success_pred | 0.99 |
| entropy_pred | 0.2 |
| impact_pred | 88.0 |
| cost_pred | 0.5 |
| learning_value_pred | 3.0 |
| ev_pred | 88.06 |

### Step Metrics Rationale

- High `p_success_pred` (0.99) and low `cost_pred` (0.5) for straightforward automated validation.
- Derivation: `EV = 0.99 * 88.0 + 0.5 * 3.0 - 0.3 * 0.2 - 0.5 = 87.12 + 1.50 - 0.06 - 0.5 = 88.06`.