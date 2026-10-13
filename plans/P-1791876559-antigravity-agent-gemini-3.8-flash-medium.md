# Plan for I-1791876536-coherence-decoupling-web-token-and-docs

- **Plan ID:** P-1791876559-antigravity-agent-gemini-3.8-flash-medium}
- **Parent Intent ID:** NONE
- **Agent:** antigravity-agent (version: 1.1.22)
- **Created At:** 2026-10-13T07:29:19.622Z

## Planner Autonomy Summary

- **Intent handling:** ACCEPT_AS_IS
- **Reframed intent (if applicable):** NONE
- **Exploration stance:** exploit with targeted empirical verification of Phase 4 module isolation, modular parser and
  command extraction boundaries, token file permission security (`0600`), mitmweb authentication forwarding, and
  backward-compatible import preservation.
- **Safety priority level:** standard
- **Priority Justification:** This plan executes a cohesive batch delivery across Beans 0075, 0042, and 0037:
  architectural decoupling of experimental Phase 4 modules, decomposition of monolithic files (`mitm_addon.py` and
  `cli.py`), secure web dashboard token generation and credential forwarding, and updating installation documentation.
  While these changes alter CLI options and directory structure, they introduce no breaking changes to proxy
  interception core logic, adhere strictly to POSIX permission sandboxing, and maintain complete backwards compatibility
  for existing imports and tests.

## Exploration

- **Proportion of steps that are exploratory:** 0.00
- **Justification:** The technical requirements across Beans 0075, 0042, and 0037 are fully specified, concrete, and
  unambiguous. Extraction target paths (`src/holon_coherence/parsers/`, `src/holon_coherence/commands/`), Phase 4 module
  decoupling boundaries, token generation routines (`secrets.token_urlsafe(16)`), permission modes (`0600`), CLI flag
  specifications (`--web-password`, `web-token`), and documentation path corrections are strictly defined. Execution
  focuses on deterministic code modularization, feature implementation, and hermetic unit testing.

## Overall Plan Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.97  |
| entropy_pred        | 0.4   |
| impact_pred         | 94.0  |
| cost_pred           | 4.6   |
| learning_value_pred | 3.5   |
| ev_pred             | 88.21 |

### Strategy Rationale

The overall plan metrics are computed directly from individual step evaluations and the config-driven Expected Value
formula:

- **p_success_pred**: 0.97. Governed by the decomposition bottleneck steps (Step 3 and Step 4: 0.97), where extracting
  CLI subcommands and container argument forwarding require ensuring seamless backward compatibility with existing tests
  and Docker invocation flows.
- **entropy_pred**: 0.4. Represents the maximum single-step risk profile (Step 3: 0.4). The cumulative predicted entropy
  across all seven steps is 1.6 (`0.2 + 0.3 + 0.4 + 0.3 + 0.2 + 0.1 + 0.1 = 1.6`), comfortably below the allocated
  entropy budget of 15.0.
- **impact_pred**: 94.0. Successfully delivers Beans 0075, 0042, and 0037 in a single coherent batch: modularizes
  `mitm_addon.py` and `cli.py`, isolates experimental Phase 4 modules with dynamic model resolution, implements secure
  token-protected mitmweb dashboard access with automated key persistence, elevates the modern `uv tool install`
  entrypoint, and cures legacy monorepo documentation drift.
- **cost_pred**: 4.6. Computed as the direct sum of step execution costs
  (`0.5 + 0.8 + 0.9 + 0.8 + 0.7 + 0.5 + 0.4 = 4.6`).
- **learning_value_pred**: 3.5. Establishes standardized subpackage patterns (`parsers/`, `commands/`), clean
  lazy/experimental module decoupling idioms, and reusable permission-sandboxed authentication patterns for Docker
  sidecar dashboards.
- **ev_pred**: 88.21. Derived using the physics-driven Expected Value formula:
  `EV = P(success) * Impact + mu * LearningValue - lambda * Delta_S_intent - Cost`. With system constants `lambda = 0.3`
  and `mu = 0.5` loaded from `holon-config/metrics/ev_config.json`:
  `EV = 0.97 * 94.0 + 0.5 * 3.5 - 0.3 * 0.4 - 4.6 = 91.18 + 1.75 - 0.12 - 4.6 = 88.21`.

## Safety & Constraint Alignment

- **Key world ruleset constraints that affect this plan:**
  - `holon-config/world/ruleset.md` §1 (Runtime & Environment Specification): Target Python `==3.13.*`, package
    execution managed strictly via `uv run` in the workspace root `.venv`.
  - `holon-config/world/ruleset.md` §2 (Coding Conventions & Standards): PEP 8 adherence, explicit static typing with
    standard library `typing`, docstring retention, and zero Ruff linting/formatting errors.
  - `holon-config/world/ruleset.md` §3 (Testing Constraints): Hermetic test isolation via `uv run pytest`, zero unstaged
    regressions across all baseline tests (`tests/test_cli.py`, `tests/test_mitm_addon_sse.py`, etc.), and test-driven
    verification for all added CLI commands and options.
  - `holon-config/world/constraints.md` §1 (Git Flow & Branch Disciplines): Isolated branches following Holon naming
    conventions (`I-.../P-.../E-.../_`), clean commit boundaries, no direct remote push to `main`.
  - `holon-config/world/constraints.md` §2 (Sandbox Containment): Operations strictly restricted to the workspace root;
    subprocess isolation without persistent shell environment mutations.
  - `holon-config/world/constraints.md` §3 (Ledger Immutability): Zero modifications to historical ledger records in
    `holon-knowledge/ledger/*.jsonl`.
  - `holon-config/world/constraints.md` §4 (Behavioral Invariants): Zero synthetic/mock data for benchmarking (Rule 1),
    universal credentials `HOLON_AGENT_KEY` (Rule 4), and strict repository separation (Rule 5).
- **Potential violations or edge cases:**
  - Breaking external imports or tests that import `MITMProxyInterceptor`, `MitmproxyAddon`, or helper functions from
    `holon_coherence.mitm_addon`.
  - Inadvertently exposing the generated web password token in world-readable files or container logs.
  - Subcommand parsing conflicts or regressions in `cli.py` during extraction into `src/holon_coherence/commands/`.
  - Path drift during monorepo documentation cleanup breaking valid internal Markdown links.
- **Mitigations built into the plan:**
  - Maintain transparent re-exports in `src/holon_coherence/mitm_addon.py` from `src/holon_coherence/parsers/` so all
    existing imports continue to function without disruption.
  - Ensure `~/.holon/web-token` is written using `os.open` with `O_CREAT | O_WRONLY | O_TRUNC` and mode `0o600`, with
    explicit file permission verification in unit tests.
  - Implement command dispatchers with clear signature conventions, routing `main()` through modular handlers while
    preserving argument parsing structure and exit code contracts.
  - Preserve relative links and verify that all updated paths in `docs/methods/` resolve directly to existing repository
    files.
- **Residual risk accepted (and why):**
  - Extracting modules creates new files; git status will show additions, which will be verified clean and properly
    tracked.
- **Allocated Entropy Budget:** 15.0
- **Predicted Plan Entropy:** 1.6
- **Budget Compliance:** The cumulative predicted plan entropy of 1.6 remains well within the allocated budget limit of
  15.0.

## Plan Description & Strategy

This implementation is divided into 7 sequential steps:

1. **Step 1: Decouple Phase 4 Experimental Modules & Parameterize Dynamic Model Resolution (Bean 0075)**: Mark
   `OpenBrainMemory`, `RAGCodebaseIndexer`, and `RingerOrchestrator` as optional experimental modules in `__init__.py`,
   and parameterize dynamic model resolution in `ringer_orchestrator.py` eliminating hardcoded model strings.
2. **Step 2: Decompose Monolithic `mitm_addon.py` into `src/holon_coherence/parsers/` (Bean 0075)**: Extract SSE stream
   reassembly, token counting, and provider heuristics into dedicated parser modules, preserving backward-compatible
   re-exports in `mitm_addon.py`.
3. **Step 3: Decompose `cli.py` into Modular Command Dispatchers in `src/holon_coherence/commands/` (Bean 0075)**:
   Extract command handlers (`start`, `stop`, `status`, `logs`, `build`, `init-ca`, `run`, `run-agent`) into
   `src/holon_coherence/commands/` while preserving top-level CLI entrypoints.
4. **Step 4: Implement Web Interface Token Management & Password Support across CLI & Container Integration
   (Bean 0042)**: Add `--web-password` flag, `HOLON_COHERENCE_WEB_PASSWORD` fallback, `secrets.token_urlsafe(16)`
   auto-generation, `~/.holon/web-token` persistence with `0600` permissions, container `--set web_password=...`
   forwarding, dashboard URL printing, and dedicated `web-token` / `web-key` CLI command.
5. **Step 5: Author Comprehensive Test Suite for Web Token & Password Functionality in `tests/test_cli.py`
   (Bean 0042)**: Add hermetic unit tests verifying password generation, file permission enforcement (`0600`),
   environment fallback, container command construction, `status` display, and `web-token` helper command execution.
6. **Step 6: Elevate Primary Git Installation & Document Shell Rehashing in `README.md`, and Fix Legacy Monorepo Path
   Drift in `docs/methods/` (Beans 0037 & 0075)**: Update `README.md` to highlight `uv tool install git+...`, reserve
   editable install for local contributors, document `rehash` / `hash -r`, and replace obsolete
   `apps/sandbox-executor/...` paths in `docs/methods/*.md`.
7. **Step 7: Full Verification: Pytest Suite, Ruff Linting, Prettier, and Workspace Hygiene Verification**: Execute the
   full test suite (`uv run pytest`), ensure clean linting and formatting (`uv run ruff check .`,
   `uv run ruff format --check .`), and verify zero regressions.

---

## Step 1: Decouple Phase 4 Experimental Modules & Parameterize Dynamic Model Resolution (Bean 0075)

- **Sub‑intent recommendation:** NO
- **Reasoning:** Core module decoupling and dynamic model parameterization within `src/holon_coherence/`.
- **Step Type:** IMPLEMENT
- **Exploration level:** EXPLOIT

### Intent & Git Integration

- **Step Intent:** Cleanly decouple Phase 4 experimental modules (`OpenBrainMemory`, `RAGCodebaseIndexer`,
  `RingerOrchestrator`) by clearly distinguishing them as optional/experimental components in
  `src/holon_coherence/__init__.py`, and eliminate hardcoded model IDs in `src/holon_coherence/ringer_orchestrator.py`
  by enabling dynamic model resolution via environment variables and runtime parameterization.
- **Git branch:**
  `I-1791876536-coherence-decoupling-web-token-and-docs/P-1791876559-antigravity-agent-gemini-3.8-flash-medium/E-phase4-decoupling/_`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- In `src/holon_coherence/__init__.py`:
  - Clearly organize `__all__` into core stable primitives (`HybridCacheStore`, `JSONContextCleaner`,
    `MITMProxyInterceptor`, `generate_root_ca`) and experimental Phase 4 modules (`OpenBrainMemory`,
    `RAGCodebaseIndexer`, `RingerOrchestrator`).
  - Add explicit module-level docstring annotations and `__experimental__` export list distinguishing Phase 4 components
    as experimental while maintaining backward-compatible imports so existing consumers do not break.
- In `src/holon_coherence/ringer_orchestrator.py`:
  - Parameterize default model resolution to query environment variables (`HOLON_ARCHITECT_MODEL` and
    `HOLON_EXECUTOR_MODEL`) before falling back to standard provider defaults.
  - Support dynamic resolution so callers or configuration objects can specify any model identifier without vendor
    hardcoding.
  - Update docstrings to reflect dynamic model resolution.
- Verify existing tests continue to pass via `uv run pytest`.

### Dependencies & Criticality

- **Depends on:** NONE
- **Is Bottleneck:** NO

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §1 & §2 (Python 3.13, PEP 8, static typing, docstrings).
- **Potential failure modes for this step:** Removing symbols from `__init__.__all__` breaking external imports.
- **Guardrails and early‑abort checks:** Ensure backward compatibility is preserved by keeping all existing exported
  symbols accessible from `holon_coherence`.

### Success & Discard Criteria

- **Success:** Phase 4 modules are documented and categorized as experimental in `__init__.py`, hardcoded model IDs in
  `ringer_orchestrator.py` are parameterized with environment variable fallbacks, and tests pass.
- **Discard:** Discard if changes introduce import cycles or break existing test imports.

### Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.99  |
| entropy_pred        | 0.2   |
| impact_pred         | 80.0  |
| cost_pred           | 0.5   |
| learning_value_pred | 1.5   |
| ev_pred             | 79.39 |

### Step Metrics Rationale

- High `p_success_pred` (0.99) and low entropy (0.2) as changes are non-destructive and preserve backward compatibility.
- Derivation: `EV = 0.99 * 80.0 + 0.5 * 1.5 - 0.3 * 0.2 - 0.5 = 79.2 + 0.75 - 0.06 - 0.5 = 79.39`.

---

## Step 2: Decompose Monolithic `mitm_addon.py` into `src/holon_coherence/parsers/` (Bean 0075)

- **Sub‑intent recommendation:** NO
- **Reasoning:** Refactoring parser routines from `mitm_addon.py` into dedicated subpackage `parsers/`.
- **Step Type:** IMPLEMENT
- **Exploration level:** EXPLOIT

### Intent & Git Integration

- **Step Intent:** Decompose `mitm_addon.py` (which currently exceeds 1300 lines) by extracting Server-Sent Events (SSE)
  stream reassembly, token counting dataclasses/heuristics, and provider payload parsers into a clean
  `src/holon_coherence/parsers/` subpackage.
- **Git branch:**
  `I-1791876536-coherence-decoupling-web-token-and-docs/P-1791876559-antigravity-agent-gemini-3.8-flash-medium/E-parsers-extraction/_`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- Create subpackage directory `src/holon_coherence/parsers/`.
- In `src/holon_coherence/parsers/sse.py`:
  - Extract SSE stream reassembly and event parsing routines: `extract_sse_content`, `extract_sse_cache_read_tokens`,
    `extract_sse_token_counts`.
  - Extract helper routines for JSON chunk extraction and fallback content decoding.
- In `src/holon_coherence/parsers/tokens.py`:
  - Extract token estimation structures: `TokenCounts` namedtuple/class, `extract_token_counts`,
    `extract_detailed_token_counts`, `estimate_chars`, and `safe_int`.
  - Extract provider-specific token count extraction logic (OpenAI, Anthropic, Gemini).
- In `src/holon_coherence/parsers/__init__.py`:
  - Re-export all extracted parser functions and classes (`extract_sse_content`, `extract_sse_token_counts`,
    `extract_sse_cache_read_tokens`, `TokenCounts`, `extract_token_counts`, `extract_detailed_token_counts`,
    `estimate_chars`, `safe_int`).
- In `src/holon_coherence/mitm_addon.py`:
  - Import the extracted symbols from `holon_coherence.parsers`.
  - Re-export them in `mitm_addon.py` so that external callers and test modules (`tests/test_mitm_addon_sse.py`)
    importing from `holon_coherence.mitm_addon` continue to work without modification.
- Execute `uv run pytest tests/test_mitm_addon_sse.py` and `uv run pytest tests/test_coherence.py` to confirm zero
  regression.

### Dependencies & Criticality

- **Depends on:** Step 1
- **Is Bottleneck:** NO

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §2 & §3 (Static typing, zero regressions).
- **Potential failure modes for this step:** Circular imports between `parsers` and `mitm_addon`, or missing symbol
  re-exports breaking `tests/test_mitm_addon_sse.py`.
- **Guardrails and early‑abort checks:** Maintain identical signatures and verify all re-exported names match previous
  definitions.

### Success & Discard Criteria

- **Success:** Parsers are isolated in `src/holon_coherence/parsers/`, `mitm_addon.py` line count is significantly
  reduced, and all tests in `tests/test_mitm_addon_sse.py` pass without alterations.
- **Discard:** Discard if parsing latency increases or if circular import issues cannot be cleanly resolved.

### Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.98  |
| entropy_pred        | 0.3   |
| impact_pred         | 88.0  |
| cost_pred           | 0.8   |
| learning_value_pred | 2.0   |
| ev_pred             | 86.35 |

### Step Metrics Rationale

- `p_success_pred` (0.98) reflects low risk due to existing test suite coverage for SSE and token parsing.
- Derivation: `EV = 0.98 * 88.0 + 0.5 * 2.0 - 0.3 * 0.3 - 0.8 = 86.24 + 1.0 - 0.09 - 0.8 = 86.35`.

---

## Step 3: Decompose `cli.py` into Modular Command Dispatchers in `src/holon_coherence/commands/` (Bean 0075)

- **Sub‑intent recommendation:** NO
- **Reasoning:** Modularizing CLI dispatcher logic in `src/holon_coherence/commands/`.
- **Step Type:** IMPLEMENT
- **Exploration level:** EXPLOIT

### Intent & Git Integration

- **Step Intent:** Decompose monolithic `cli.py` (which currently exceeds 1480 lines) by extracting command handlers and
  execution workflows into `src/holon_coherence/commands/`.
- **Git branch:**
  `I-1791876536-coherence-decoupling-web-token-and-docs/P-1791876559-antigravity-agent-gemini-3.8-flash-medium/E-cli-decomposition/_`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- Create subpackage directory `src/holon_coherence/commands/`.
- Extract command implementations into dedicated modules:
  - `src/holon_coherence/commands/ca.py`: `init-ca` command handler delegating to `generate_root_ca`.
  - `src/holon_coherence/commands/docker_ops.py`: `build`, `stop`, `status`, `logs` commands and container management
    helpers.
  - `src/holon_coherence/commands/runner.py`: `run` command handler and environment forwarding (`build_proxy_env`,
    `execute_interactive_process`).
  - `src/holon_coherence/commands/agents.py`: `run-agent` and direct agent dispatchers (`run_agent`,
    `extract_runner_flags`, help printers).
  - `src/holon_coherence/commands/start.py`: `start` command handler containing host vs container start flows, port
    checks, and Docker container argument building.
  - `src/holon_coherence/commands/__init__.py`: Clean re-exports of command dispatchers.
- In `src/holon_coherence/cli.py`:
  - Retain top-level argument parsing, CLI help formatting, and dispatch routing to the modular command handlers.
  - Re-export common utilities (`is_container_running`, `check_docker_daemon`, `stop_proxy_container`, `run_agent`,
    etc.) so existing unit tests in `tests/test_cli.py` continue importing without modification.
- Execute `uv run pytest tests/test_cli.py` to ensure all existing CLI tests pass with zero regressions.

### Dependencies & Criticality

- **Depends on:** Step 2
- **Is Bottleneck:** YES (central entrypoint touched by all CLI workflows)

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §2 & §3 (Static typing, docstrings, zero test regressions).
- **Potential failure modes for this step:** Broken imports in `tests/test_cli.py` or regression in flag passthrough
  logic.
- **Guardrails and early‑abort checks:** Ensure `cli.py` preserves all public functions as re-exports, and verify CLI
  behavior via pytest before proceeding.

### Success & Discard Criteria

- **Success:** `cli.py` is reduced to an argument parsing and dispatch coordinator, modular handlers reside in
  `src/holon_coherence/commands/`, and existing CLI tests pass.
- **Discard:** Discard if command dispatch degrades performance or breaks existing CLI argument parsing.

### Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.97  |
| entropy_pred        | 0.4   |
| impact_pred         | 90.0  |
| cost_pred           | 0.9   |
| learning_value_pred | 2.5   |
| ev_pred             | 87.53 |

### Step Metrics Rationale

- `p_success_pred` (0.97) and `entropy_pred` (0.4) reflect the structural decomposition of the primary CLI entrypoint.
- Derivation: `EV = 0.97 * 90.0 + 0.5 * 2.5 - 0.3 * 0.4 - 0.9 = 87.3 + 1.25 - 0.12 - 0.9 = 87.53`.

---

## Step 4: Implement Web Interface Token Management & Password Support across CLI & Container Integration (Bean 0042)

- **Sub‑intent recommendation:** NO
- **Reasoning:** Implementation of web token generation, security persistence, and CLI integration.
- **Step Type:** IMPLEMENT
- **Exploration level:** EXPLOIT

### Intent & Git Integration

- **Step Intent:** Add `--web-password` CLI option to `start`, support `HOLON_COHERENCE_WEB_PASSWORD` fallback,
  auto-generate secure token via `secrets.token_urlsafe(16)` when omitted, persist active token to `~/.holon/web-token`
  with strict `0600` permissions, forward to container via `--set web_password=...`, print dashboard URL with token on
  `start --web`, display in `status`, and add dedicated `web-token` / `web-key` helper command.
- **Git branch:**
  `I-1791876536-coherence-decoupling-web-token-and-docs/P-1791876559-antigravity-agent-gemini-3.8-flash-medium/E-web-token-auth/_`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- Create `src/holon_coherence/commands/web_token.py` (or helper in `commands/`):
  - Implement token resolution logic:
    1. Explicit `--web-password` CLI argument.
    2. Environment variable `HOLON_COHERENCE_WEB_PASSWORD`.
    3. Auto-generate secure token via standard library `secrets.token_urlsafe(16)`.
  - Implement token persistence:
    - Path: `os.path.expanduser("~/.holon/web-token")`.
    - Directory ensured with mode `0o700`.
    - Token written with strict `0o600` permissions using `os.open` with `O_CREAT | O_WRONLY | O_TRUNC` and
      `os.chmod(..., 0o600)`.
  - Implement helper to retrieve active token if present and still valid.
- Integrate into `start` command (`src/holon_coherence/commands/start.py` & `cli.py`):
  - Add `--web-password` argument to `start` parser.
  - When `--web` is activated:
    - Resolve web password (from CLI flag, env, or `secrets.token_urlsafe(16)`).
    - Persist token to `~/.holon/web-token` with `0600` permissions.
    - Inside container execution: append `["--set", f"web_password={password}"]` to the `mitmweb` invocation command.
    - Host Docker execution: pass `-e HOLON_COHERENCE_WEB_PASSWORD=...` or container arguments forwarding
      `--web-password` so the container instance runs with password protection enabled.
    - Output dashboard URL informing user of authentication:
      `🌐 Web dashboard exposed at http://127.0.0.1:<web_port> (Password: <token>)`.
- Integrate into `status` command:
  - If `~/.holon/web-token` exists and container is active, display the active web dashboard token and access URL.
- Add dedicated `web-token` (with alias `web-key`) command:
  - Register `web-token` and `web-key` subparsers in CLI parser.
  - Handler checks `~/.holon/web-token`:
    - If present, print current token and dashboard instructions.
    - If absent, indicate that no active web session token exists and advise starting via `holon-coherence start --web`.

### Dependencies & Criticality

- **Depends on:** Step 3
- **Is Bottleneck:** NO

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §2 (Security, POSIX file permissions, static typing).
- **Potential failure modes for this step:** Insecure file permissions allowing other local users to read the token;
  failure to pass `--set web_password=...` to `mitmweb` resulting in unprotected web access.
- **Guardrails and early‑abort checks:** Enforce `0o600` file permissions; test that token is non-empty and correctly
  formatted; verify mitmweb argument injection.

### Success & Discard Criteria

- **Success:** Web token auto-generation, environment fallback, `0600` persistence, container argument forwarding,
  `status` display, and `web-token` helper command all operate correctly.
- **Discard:** Discard if permissions cannot be enforced or if mitmweb rejects the password option.

### Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.97  |
| entropy_pred        | 0.3   |
| impact_pred         | 92.0  |
| cost_pred           | 0.8   |
| learning_value_pred | 2.5   |
| ev_pred             | 89.60 |

### Step Metrics Rationale

- High impact (92.0) as this resolves critical security requirement Bean 0042 for web interface access control.
- Derivation: `EV = 0.97 * 92.0 + 0.5 * 2.5 - 0.3 * 0.3 - 0.8 = 89.24 + 1.25 - 0.09 - 0.8 = 89.60`.

---

## Step 5: Author Comprehensive Test Suite for Web Token & Password Functionality in `tests/test_cli.py` (Bean 0042)

- **Sub‑intent recommendation:** NO
- **Reasoning:** Adding unit and regression test coverage for Bean 0042 in `tests/test_cli.py`.
- **Step Type:** TEST
- **Exploration level:** EXPLOIT

### Intent & Git Integration

- **Step Intent:** Author extensive unit tests in `tests/test_cli.py` covering token generation, environment fallback,
  file permission verification (`0600`), CLI flag `--web-password`, container command construction, `status` display,
  and the `web-token` / `web-key` helper command.
- **Git branch:**
  `I-1791876536-coherence-decoupling-web-token-and-docs/P-1791876559-antigravity-agent-gemini-3.8-flash-medium/E-test-cli-web-token/_`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- In `tests/test_cli.py`:
  - Add `test_web_token_resolution_and_generation`:
    - Test explicit `--web-password` flag value is used.
    - Test `HOLON_COHERENCE_WEB_PASSWORD` environment variable fallback when CLI flag is omitted.
    - Test auto-generation via `secrets.token_urlsafe(16)` when neither is provided.
  - Add `test_web_token_file_persistence_and_permissions`:
    - Use `tmp_path` fixture to mock `~/.holon/web-token`.
    - Verify written file content matches generated token.
    - Stat file to verify POSIX file permissions are strictly `0o600` (`stat.S_IRUSR | stat.S_IWUSR`).
  - Add `test_start_web_command_forwards_web_password`:
    - Test in-container start command appends `["--set", "web_password=<token>"]` to mitmweb invocation.
    - Test host start command forwards web password to container execution args or environment.
  - Add `test_status_command_displays_web_token`:
    - Test `status` command output includes active web token information when file exists.
  - Add `test_web_token_and_web_key_commands`:
    - Test `holon-coherence web-token` outputs existing token.
    - Test `holon-coherence web-key` alias outputs existing token.
    - Test appropriate advisory message when no active token file exists.
  - Run `uv run pytest tests/test_cli.py` to verify all tests pass cleanly.

### Dependencies & Criticality

- **Depends on:** Step 4
- **Is Bottleneck:** NO

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §3 (Hermetic test isolation, zero regressions).
- **Potential failure modes for this step:** Tests polluting actual `~/.holon/` directory on host.
- **Guardrails and early‑abort checks:** Isolate all file operations using `monkeypatch` and `tmp_path` fixtures.

### Success & Discard Criteria

- **Success:** 100% test pass rate across new and pre-existing tests in `tests/test_cli.py`.
- **Discard:** Discard if any test leaks state or fails non-deterministically.

### Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.98  |
| entropy_pred        | 0.2   |
| impact_pred         | 86.0  |
| cost_pred           | 0.7   |
| learning_value_pred | 2.0   |
| ev_pred             | 84.52 |

### Step Metrics Rationale

- High `p_success_pred` (0.98) due to standard pytest and mock patterns.
- Derivation: `EV = 0.98 * 86.0 + 0.5 * 2.0 - 0.3 * 0.2 - 0.7 = 84.28 + 1.0 - 0.06 - 0.7 = 84.52`.

---

## Step 6: Elevate Primary Git Installation & Document Shell Rehashing in `README.md`, and Fix Legacy Monorepo Path Drift in `docs/methods/` (Beans 0037 & 0075)

- **Sub‑intent recommendation:** NO
- **Reasoning:** Documentation updates across `README.md` and `docs/methods/`.
- **Step Type:** IMPLEMENT
- **Exploration level:** EXPLOIT

### Intent & Git Integration

- **Step Intent:** Elevate `uv tool install git+https://github.com/Holon-Agentic-Coder/holon-coherence.git` as the
  primary standard entrypoint in `README.md`, reserve editable install (`uv tool install --editable .`) for local
  contributors, document shell rehashing (`rehash` for zsh, `hash -r` for bash), and eliminate obsolete
  `apps/sandbox-executor/...` paths in `docs/methods/*.md`.
- **Git branch:**
  `I-1791876536-coherence-decoupling-web-token-and-docs/P-1791876559-antigravity-agent-gemini-3.8-flash-medium/E-docs-and-readme-update/_`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- In `README.md`:
  - Update Section 1 ("Install CLI Wrapper"):
    - Elevate `uv tool install git+https://github.com/Holon-Agentic-Coder/holon-coherence.git` as the primary,
      recommended standard installation command.
    - Clearly document that `uv tool install --editable .` is reserved for local contributors and developers modifying
      the repository.
    - Document shell rehashing instructions:
      - For zsh: run `rehash` to immediately update command lookup hash table.
      - For bash: run `hash -r` to reset remembered shell locations.
  - Document the new `--web-password` flag and `web-token` command in the Quick Start / Management section.
- In `docs/methods/` documentation files:
  - In `docs/methods/context_cleaning.md`:
    - Replace obsolete paths `apps/sandbox-executor/src/sandbox_executor/token_reduction/payload_cleaner.py` with
      `src/holon_coherence/payload_cleaner.py`.
    - Replace `apps/sandbox-executor/src/sandbox_executor/token_reduction/mitm_addon.py` with
      `src/holon_coherence/mitm_addon.py`.
    - Replace sys.path references `apps/sandbox-executor/src` with `src`.
  - In `docs/methods/prompt_cache_optimization.md`:
    - Replace `apps/sandbox-executor/src/sandbox_executor/token_reduction/...` with `src/holon_coherence/...`.
  - In `docs/methods/openbrain_memory.md`:
    - Replace `apps/sandbox-executor/src/sandbox_executor/token_reduction/openbrain_memory.py` with
      `src/holon_coherence/openbrain_memory.py`.
  - In `docs/methods/local_cache_layer.md`:
    - Replace `apps/sandbox-executor/src/sandbox_executor/token_reduction/hybrid_cache.py` with
      `src/holon_coherence/hybrid_cache.py`.
  - In `docs/methods/ringer_framework.md`:
    - Replace `apps/sandbox-executor/src/sandbox_executor/token_reduction/ringer_orchestrator.py` with
      `src/holon_coherence/ringer_orchestrator.py`.
  - In `docs/methods/rag_codebase_indexer.md`:
    - Replace `apps/sandbox-executor/src/sandbox_executor/token_reduction/rag_indexer.py` with
      `src/holon_coherence/rag_indexer.py`.
    - Update codebase path examples to target modern `holon-coherence` structure.
- Verify markdown formatting across all modified files.

### Dependencies & Criticality

- **Depends on:** Step 4
- **Is Bottleneck:** NO

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §2 (Documentation accuracy and formatting).
- **Potential failure modes for this step:** Broken Markdown links or residual uncorrected paths.
- **Guardrails and early‑abort checks:** Grep entire `docs/methods/` directory for `apps/sandbox-executor` to ensure
  100% removal.

### Success & Discard Criteria

- **Success:** `README.md` presents git install as primary with shell rehashing documented; zero occurrences of
  `apps/sandbox-executor` remain in `docs/methods/`.
- **Discard:** Discard if outdated instructions or dead links are introduced.

### Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.99  |
| entropy_pred        | 0.1   |
| impact_pred         | 84.0  |
| cost_pred           | 0.5   |
| learning_value_pred | 1.5   |
| ev_pred             | 83.38 |

### Step Metrics Rationale

- Very low risk (entropy 0.1, success 0.99) focused on documentation accuracy and developer onboarding alignment.
- Derivation: `EV = 0.99 * 84.0 + 0.5 * 1.5 - 0.3 * 0.1 - 0.5 = 83.16 + 0.75 - 0.03 - 0.5 = 83.38`.

---

## Step 7: Full Verification: Pytest Suite, Ruff Linting, Prettier, and Workspace Hygiene Verification

- **Sub‑intent recommendation:** NO
- **Reasoning:** Comprehensive verification across entire codebase.
- **Step Type:** VERIFY
- **Exploration level:** EXPLOIT

### Intent & Git Integration

- **Step Intent:** Verify that all unit tests in the entire test suite pass cleanly, Ruff linting and formatting checks
  succeed with zero warnings/errors, Prettier checks pass, and git status reflects clean, organized modifications.
- **Git branch:**
  `I-1791876536-coherence-decoupling-web-token-and-docs/P-1791876559-antigravity-agent-gemini-3.8-flash-medium/E-full-verification/_`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- Execute `uv run pytest -v` across all test files:
  - `tests/test_cli.py`
  - `tests/test_mitm_addon_sse.py`
  - `tests/test_hybrid_cache.py`
  - `tests/test_coherence.py`
  - `tests/test_host_local.py`
  - `tests/test_docker_integration.py`
  - `tests/test_build_image.py`
  - `tests/test_makefile.py`
- Run Ruff linter: `uv run ruff check .` to verify zero linting errors.
- Run Ruff formatter check: `uv run ruff format --check .` to verify complete PEP 8 and formatting compliance.
- Run Prettier check if installed (`npx prettier --check "README.md" "docs/**/*.md"`).
- Verify git status to confirm only intended files are modified/created and no extraneous temporary files exist.

### Dependencies & Criticality

- **Depends on:** Steps 1 through 6
- **Is Bottleneck:** NO

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §1, §2, §3 (Zero regressions, clean linting).
- **Potential failure modes for this step:** Unformatted files or lingering test failures.
- **Guardrails and early‑abort checks:** Format code with `uv run ruff format .` if any stylistic deviation is detected.

### Success & Discard Criteria

- **Success:** Full test suite passes 100%, Ruff linter and formatter report clean status, zero regressions.
- **Discard:** Discard if any test fails or linting rules are violated.

### Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.99  |
| entropy_pred        | 0.1   |
| impact_pred         | 85.0  |
| cost_pred           | 0.4   |
| learning_value_pred | 1.0   |
| ev_pred             | 84.22 |

### Step Metrics Rationale

- Final verification step ensuring deterministic readiness for merge and squash commit.
- Derivation: `EV = 0.99 * 85.0 + 0.5 * 1.0 - 0.3 * 0.1 - 0.4 = 84.15 + 0.5 - 0.03 - 0.4 = 84.22`.
