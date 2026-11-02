# Plan for I-1793438378-coherence-proxy-lifecycle-class-for-start

- **Plan ID:** P-1793438393-antigravity-agent-gemini-3.8-flash-medium
- **Parent Intent ID:** NONE
- **Agent:** antigravity-agent (version: 1.4.12)
- **Created At:** 2026-10-31T09:19:54.371Z

---

## Overall Plan Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.98  |
| entropy_pred        | 3.40  |
| impact_pred         | 8.90  |
| cost_pred           | 0.75  |
| learning_value_pred | 2.20  |
| ev_pred             | 8.05  |

## Step 1: Create ProxyLifecycle Domain Class (`src/holon_coherence/proxy/lifecycle.py`)

### Step Intent & Git Integration

- **Sub-intent recommendation:** none (monolithic execution within intent scope)
- **Reasoning:** Establish the domain class `ProxyLifecycle` in `src/holon_coherence/proxy/lifecycle.py` that encapsulates all proxy container lifecycle, CA certificate management, readiness polling, and teardown across Docker and host-local execution modes. Decompose monolithic logic currently embedded in `commands/start.py` into small, cohesive, single-purpose helper functions strictly conforming to Bean 0186 complexity thresholds ($C901 \le 10$, $PLR0911 \le 6$, $PLR0912 \le 12$, $PLR0913 \le 5$, $PLR0915 \le 50$) with zero `# noqa` suppressions.
- **Step type:** implementation
- **Exploration level:** 0.05
- **Git branch:** `I-1793438378-coherence-proxy-lifecycle-class-for-start`

### Implementation Details

1. **Lifecycle Configuration & Domain Models**:
   - Define dataclass `ProxyLifecycleConfig`:
     - `port: int = 8080`
     - `web_port: int | None = None`
     - `container_name: str | None = None`
     - `image: str = "holon-coherence:latest"`
     - `host_local_spec: str = ""`
     - `passive: bool = False`
     - `web_password: str | None = None`
     - `ca_dir: str = "~/.holon/proxy-ca"`
     - `cache_dir: str = "~/.holon/cache"`
     - `logs_dir: str = "~/.holon/logs"`
     - `detach: bool = True`

2. **Core `ProxyLifecycle` Domain Class**:
   - `ensure_ca(ca_dir: str | None = None) -> tuple[str, str]`:
     - Creates `ca_dir`, `cache_dir`, `logs_dir` with secure permissions (`0o700`).
     - Checks existence of `mitmproxy-ca-cert.pem` and `mitmproxy-ca.pem`.
     - Invokes `generate_root_ca(output_dir=...)` if missing and sets file permissions (`0o600`).
     - Returns paths `(ca_cert_path, ca_pem_path)`.
   - `wait_until_ready(timeout_seconds: float = 15.0, poll_interval: float = 0.2) -> bool`:
     - Performs HTTP health polling against the proxy listening port using non-proxied requests (`_urlopen_no_proxy`).
     - Checks container running status (`is_container_running`) on each iteration to fail fast if container stops unexpectedly.
     - Returns `True` if HTTP 200/healthy received within `timeout_seconds`, `False` otherwise.
   - `start(recreate_if_mismatch: bool = True) -> bool`:
     - Dispatches between container mode (`is_in_container()`) and host Docker mode.
     - In container mode: invokes `mitmweb` or `mitmdump` process with appropriate flags and addon path.
     - In host Docker mode:
       - Validates Docker daemon status via `check_docker_daemon()`.
       - Manages port conflict and container reuse/recreation if `host_local_spec` has changed (`host_local_covered`).
       - Executes `ensure_ca()` and `ensure_docker_image()`.
       - Formulates `docker run` command via modular helper `_build_docker_run_args()`.
       - Launches container, executes `wait_until_ready()`, and handles startup failures with automatic cleanup.
   - `stop(container_name: str | None = None) -> bool`:
     - Stops and removes running container via `docker rm -f`.
     - Returns `True` on clean teardown or if no active container was found.

3. **Modular Helper Decomposition**:
   - `_prepare_proxy_directories(ca_dir: str, cache_dir: str, logs_dir: str) -> None`: isolates path expansion and directory permissions.
   - `_build_docker_run_args(config: ProxyLifecycleConfig, actual_port: int, actual_web_port: int | None) -> list[str]`: builds Docker CLI arguments without exceeding branching or statement limits.
   - `_verify_container_health(container_name: str, port: int, timeout: float) -> bool`: isolates readiness polling and diagnostic log retrieval.
   - All helper functions and methods designed to strictly enforce McCabe complexity $\le 10$, $\le 5$ arguments, and $\le 50$ statements.

### Dependencies & Criticality

- **Dependencies:** `holon_coherence.ca_generator`, `holon_coherence.commands.docker_ops`, `holon_coherence.host_local`
- **Is bottleneck:** Yes — Establishes the decoupled domain foundation for proxy lifecycle management before CLI handlers are refactored.

### Safety & Constraint Considerations

- **Relevant rules:** §2 Coding Conventions & Standards, Bean 0186 Complexity Limits, Invariant 1 (Zero Synthetic Data), Invariant 4 (Universal Credentials).
- **Failure modes:** Port collision race conditions, permission errors when mounting CA directories, container restart loops.
- **Guardrails:** Preserve identical port probing logic (`is_port_in_use`), Docker argument formatting, environment variable bindings (`COHERENCE_TOKEN_REDUCTION`, `HOLON_PASSIVE_MONITORING`), and volume mappings.

### Success & Discard Criteria

- **Success:** `src/holon_coherence/proxy/lifecycle.py` exists, exposes `ProxyLifecycle` and `ProxyLifecycleConfig`, implements `ensure_ca()`, `start()`, `wait_until_ready()`, and `stop()`, with 0 `# noqa` suppressions and 100% compliance with Bean 0186 complexity thresholds.
- **Discard:** Discard if lifecycle behavior diverges from existing container startup/teardown mechanics or if complexity rules are violated.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.99  |
| entropy_pred        | 0.70  |
| impact_pred         | 8.80  |
| cost_pred           | 0.15  |
| learning_value_pred | 1.50  |
| ev_pred             | 9.10  |

### Step Metrics Rationale

- $\text{EV} = 0.99 \times 8.80 + 0.5 \times 1.50 - 0.3 \times 0.70 - 0.15 = 8.712 + 0.75 - 0.21 - 0.15 = 9.102 \approx 9.10$. Encapsulating proxy container orchestration and CA lifecycle in a cohesive domain class directly addresses architectural debt and removes two high-complexity monolithic functions.

## Step 2: Refactor Start Command (`src/holon_coherence/commands/start.py`) to Delegate to `ProxyLifecycle`

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Refactor `src/holon_coherence/commands/start.py` to eliminate monolithic functions (`handle_start` 202 lines CC 33, `ensure_proxy_running` 171 lines CC 30). Delegate all container startup, CA verification, and readiness polling to `ProxyLifecycle`. Eliminate both `# noqa: C901, PLR0912, PLR0915` suppressions, reducing the module to a clean CLI argument parser and lifecycle dispatcher.
- **Step type:** implementation
- **Exploration level:** 0.05
- **Git branch:** `I-1793438378-coherence-proxy-lifecycle-class-for-start`

### Implementation Details

1. **Facade & Backward Compatibility Retention**:
   - Retain public function signatures `ensure_proxy_running(...)` and `wait_for_proxy_ready(...)` in `commands/start.py`.
   - Update `ensure_proxy_running` to construct a `ProxyLifecycle` instance and delegate to `lifecycle.ensure_running()` / `lifecycle.start()`.
   - Update `wait_for_proxy_ready` to delegate directly to `ProxyLifecycle.wait_until_ready()` or a dedicated static helper.

2. **Decomposition of `handle_start`**:
   - Split `handle_start` into focused, single-responsibility sub-routines:
     - `_resolve_start_local_llm(args: Any, initial_spec: str) -> tuple[str, LocalLlmRoute | None]`: Validates and plans `--local-llm-base` route.
     - `_resolve_start_ports(args: Any, route: LocalLlmRoute | None, web_enabled: bool) -> tuple[int, int | None, str | None]`: Handles port conflict detection and inspector fallback mapping.
     - `_dispatch_proxy_lifecycle(args: Any, proxy_port: int, web_port: int | None, web_password: str | None, host_local_spec: str) -> None`: Constructs `ProxyLifecycleConfig` and executes `ProxyLifecycle.start()`.
   - Streamline `handle_start` into an orchestrator function with CC $\le 6$, no branches exceeding limits, and zero `# noqa` suppressions.

3. **Decomposition of `ensure_proxy_running`**:
   - Refactor `ensure_proxy_running` to delegate container reuse checks, host-local spec coverage comparison, and startup polling directly to `ProxyLifecycle`.
   - Remove `# noqa: C901, PLR0912, PLR0915` from `ensure_proxy_running`.

### Dependencies & Criticality

- **Dependencies:** Step 1 (`src/holon_coherence/proxy/lifecycle.py`)
- **Is bottleneck:** Yes — Core requirement of intent acceptance criteria.

### Safety & Constraint Considerations

- **Relevant rules:** §2 Coding Conventions & Standards, Bean 0186 Complexity Limits, CLI argument preservation.
- **Failure modes:** Breakage of CLI flags (`--port`, `--web`, `--detach`, `--passive`, `--local-llm-base`), or discrepancies in terminal status messages expected by integration tests.
- **Guardrails:** Keep console log messages and endpoint output formatting (`print_endpoints`) identical to baseline.

### Success & Discard Criteria

- **Success:** `src/holon_coherence/commands/start.py` delegates to `ProxyLifecycle`, passes all complexity checks with zero `# noqa` suppressions, and passes all existing tests in `tests/commands/test_start.py`.
- **Discard:** Discard if any start command arguments fail or tests in `tests/commands/test_start.py` fail.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.98  |
| entropy_pred        | 0.70  |
| impact_pred         | 8.70  |
| cost_pred           | 0.15  |
| learning_value_pred | 1.40  |
| ev_pred             | 8.87  |

### Step Metrics Rationale

- $\text{EV} = 0.98 \times 8.70 + 0.5 \times 1.40 - 0.3 \times 0.70 - 0.15 = 8.526 + 0.70 - 0.21 - 0.15 = 8.866 \approx 8.87$. Refactoring `start.py` eliminates 2 high-complexity legacy suppressions and transforms a 813-line file into a clean CLI translation layer.

## Step 3: Implement Dedicated Stop Command (`src/holon_coherence/commands/stop.py`) and Refactor Teardown Delegation

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Establish `src/holon_coherence/commands/stop.py` as a dedicated CLI module for proxy teardown, decoupling the `stop` command from `docker_ops.py`. Delegate container teardown to `ProxyLifecycle.stop()` while maintaining full backwards compatibility for `handle_stop` and `stop_proxy_container` across `cli.py`, `commands/docker_ops.py`, and `commands/__init__.py`.
- **Step type:** implementation
- **Exploration level:** 0.05
- **Git branch:** `I-1793438378-coherence-proxy-lifecycle-class-for-start`

### Implementation Details

1. **Dedicated Module Implementation (`src/holon_coherence/commands/stop.py`)**:
   - Create `src/holon_coherence/commands/stop.py` with:
     - `register(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser`: Registers the `stop` sub-parser with `--name` argument.
     - `handle_stop(args: Any = None, *, stopper_fn: Callable[[str | None], None] | None = None) -> int`: Delegates stopping to `stopper_fn` or `ProxyLifecycle.stop()`.
     - `handle(args: Any) -> int`: Standard command entry point delegating to `handle_stop(args)`.

2. **Integration & Compatibility Wiring**:
   - Update `src/holon_coherence/commands/docker_ops.py` to import `handle_stop` from `holon_coherence.commands.stop` or delegate its `handle_stop` implementation to `ProxyLifecycle.stop()`.
   - Update `src/holon_coherence/commands/__init__.py` and `src/holon_coherence/cli.py` to expose `stop` module in `COMMAND_MODULES`.
   - Ensure `stop_proxy_container` in `docker_ops.py` delegates cleanly to `ProxyLifecycle.stop()`.

### Dependencies & Criticality

- **Dependencies:** Step 1 (`src/holon_coherence/proxy/lifecycle.py`)
- **Is bottleneck:** No — Parallelizable with Step 2, provides clean separation of concerns for proxy lifecycle commands.

### Safety & Constraint Considerations

- **Relevant rules:** §2 Coding Conventions & Standards, Backward compatibility of CLI subcommands and exports.
- **Failure modes:** Breaking CLI sub-parser registration order or altering `holon-coherence stop --name <container>` exit status codes.
- **Guardrails:** Retain registration ordering in `COMMAND_MODULES` so `--help` output remains identical.

### Success & Discard Criteria

- **Success:** `src/holon_coherence/commands/stop.py` is established, cleanly dispatches teardown through `ProxyLifecycle`, and all tests in `tests/commands/test_docker_ops.py` pass cleanly.
- **Discard:** Discard if CLI stop invocation fails or container teardown errors occur.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.99  |
| entropy_pred        | 0.50  |
| impact_pred         | 8.50  |
| cost_pred           | 0.10  |
| learning_value_pred | 1.20  |
| ev_pred             | 8.77  |

### Step Metrics Rationale

- $\text{EV} = 0.99 \times 8.50 + 0.5 \times 1.20 - 0.3 \times 0.50 - 0.10 = 8.415 + 0.60 - 0.15 - 0.10 = 8.765 \approx 8.77$. Dedicated `stop.py` command module completes the CLI symmetry with `start.py`, encapsulating lifecycle invocation.

## Step 4: Decompose Runner Flag and Environment Construction in `commands/agents.py`

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Decompose the runner flag parsing (`extract_runner_flags`) and agent process environment construction (`build_agent_env`, `run_agent`) in `src/holon_coherence/commands/agents.py` into modular helpers. Eliminate all 3 legacy `# noqa` complexity suppressions in `commands/agents.py`, ensuring strict compliance with Bean 0186 complexity thresholds ($C901 \le 10$, $PLR0911 \le 6$, $PLR0912 \le 12$, $PLR0913 \le 5$, $PLR0915 \le 50$).
- **Step type:** implementation
- **Exploration level:** 0.05
- **Git branch:** `I-1793438378-coherence-proxy-lifecycle-class-for-start`

### Implementation Details

1. **Decomposition of `extract_runner_flags`**:
   - Extract argument parsing routines for option values and integer ports:
     - `_parse_flag_value(argv: list[str], idx: int, flag_name: str) -> tuple[str, int]`: Handles both `--flag value` and `--flag=value` formats.
     - `_parse_port_flag(argv: list[str], idx: int, arg: str) -> tuple[int, int]`: Validates port integer range (1-65535) and returns `(parsed_port, new_index)`.
   - Implement an accumulator state container `_RunnerFlagAccumulator` or clean loop runner to keep statement count $\le 50$, branches $\le 12$, and complexity $\le 10$.
   - Eliminate `# noqa: C901, PLR0912, PLR0915` from `extract_runner_flags`.

2. **Decomposition of `build_agent_env`**:
   - Decompose environment injection into provider-specific and mode-specific subroutines:
     - `_apply_proxy_and_ca_env(env: dict[str, str], port: int, drop_no_proxy: tuple[str, ...], env_builder: Callable[..., dict[str, str]]) -> None`: Handles HTTP proxy URLs and CA cert environment scrubbing.
     - `_apply_local_llm_env(env: dict[str, str], agent_name: str, port: int, model: str | None, holon_key: str | None) -> None`: Sets endpoint URLs (`ANTHROPIC_BASE_URL`, `AGY_GATEWAY_URL`, `OPENAI_BASE_URL`) and model overrides when `--local-llm-base` is active.
     - `_apply_auth_key_env(env: dict[str, str], agent_name: str, holon_key: str | None) -> None`: Injects universal `HOLON_AGENT_KEY` into agent-specific environment variables (`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc.).
   - Refactor `build_agent_env` to orchestrate these helpers without exceeding parameter limits ($PLR0913 \le 5$) or statement limits.
   - Eliminate `# noqa: C901, PLR0912, PLR0913` from `build_agent_env`.

3. **Decomposition of `run_agent`**:
   - Decompose `run_agent` into:
     - `_resolve_agent_port(port: int | None) -> tuple[int, int | None]`: Validates and resolves CLI/environment proxy port.
     - `_setup_agent_local_route(...)`: Orchestrates route planning, reachability probing, and pruning reports.
     - `_execute_agent_with_cleanup(...)`: Manages ephemeral proxy lifecycle teardown via `ProxyLifecycle.stop()`.
   - Eliminate `# noqa: C901, PLR0912, PLR0913, PLR0915` from `run_agent`.

### Dependencies & Criticality

- **Dependencies:** Step 1 (`src/holon_coherence/proxy/lifecycle.py`)
- **Is bottleneck:** No — Refactors agent execution orchestration to use `ProxyLifecycle` and modular helpers.

### Safety & Constraint Considerations

- **Relevant rules:** §2 Coding Conventions & Standards, Bean 0186 Complexity Limits, Invariant 4 (Universal Credentials & Native Auth Fallback).
- **Failure modes:** Breaking flag parsing order or altering agent environment variables (`AGY_GATEWAY_URL`, `ANTHROPIC_BASE_URL`, `OPENAI_BASE_URL`).
- **Guardrails:** Keep exact environment variable mappings and fallback logic intact as validated by `tests/commands/test_agents.py`.

### Success & Discard Criteria

- **Success:** All 3 `# noqa` suppressions in `commands/agents.py` are eliminated, complexity is strictly $\le 10$, and all agent runner tests in `tests/commands/test_agents.py` pass cleanly.
- **Discard:** Discard if any agent flag parsing fails or environment injection deviates from baseline.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.98  |
| entropy_pred        | 0.60  |
| impact_pred         | 8.80  |
| cost_pred           | 0.15  |
| learning_value_pred | 1.60  |
| ev_pred             | 9.09  |

### Step Metrics Rationale

- $\text{EV} = 0.98 \times 8.80 + 0.5 \times 1.60 - 0.3 \times 0.60 - 0.15 = 8.624 + 0.80 - 0.18 - 0.15 = 9.094 \approx 9.09$. Eliminates 3 legacy complexity suppressions in `commands/agents.py`, cleanly modularizing command-line flag extraction and multi-agent environment construction.

## Step 5: Expand Unit and CLI Tests (`tests/test_proxy_lifecycle.py` and `tests/commands/test_start.py`)

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Author a comprehensive unit test suite in `tests/test_proxy_lifecycle.py` targeting all public methods of `ProxyLifecycle` (`ensure_ca`, `start`, `wait_until_ready`, `stop`). Update `tests/commands/test_start.py` to verify delegation pathways while ensuring 100% test pass rate and backward compatibility.
- **Step type:** testing
- **Exploration level:** 0.05
- **Git branch:** `I-1793438378-coherence-proxy-lifecycle-class-for-start`

### Implementation Details

1. **New Lifecycle Test Suite (`tests/test_proxy_lifecycle.py`)**:
   - `TestProxyLifecycleCA`:
     - Test directory creation and `0o700` permission configuration.
     - Test skipping CA generation when `mitmproxy-ca-cert.pem` and `mitmproxy-ca.pem` exist.
     - Test invoking `generate_root_ca` when cert files are absent.
   - `TestProxyLifecycleWaitUntilReady`:
     - Test immediate HTTP 200 readiness response.
     - Test fast-fail when the container stops during polling.
     - Test retry behavior on transient `URLError` up to deadline.
   - `TestProxyLifecycleStart`:
     - Test in-container dispatch to `mitmdump` and `mitmweb`.
     - Test Docker daemon unavailability reporting and early exit.
     - Test port conflict detection and container recreation when `host_local_spec` changes.
     - Test container launch failure and automatic log dump/cleanup.
   - `TestProxyLifecycleStop`:
     - Test clean invocation of `docker rm -f`.
     - Test graceful handling of non-existent container errors.

2. **Refactor and Extend `tests/commands/test_start.py`**:
   - Verify `commands/start.py` functions `ensure_proxy_running` and `wait_for_proxy_ready` delegate cleanly to `ProxyLifecycle`.
   - Ensure all pre-existing tests in `TestWaitForProxyReadySuite`, `TestPlanAndReportLocalLlmRouteSuite`, and `TestEnsureProxyRunningSuite` pass without regression.

### Dependencies & Criticality

- **Dependencies:** Step 1, Step 2, Step 3, Step 4
- **Is bottleneck:** Yes — Validates behavioral parity and guarantees regression-free lifecycle operations.

### Safety & Constraint Considerations

- **Relevant rules:** §3 Testing Constraints, Rule 1 (Hermetic, non-synthetic tests).
- **Failure modes:** Mocking discrepancies between unit tests and underlying Docker CLI commands.
- **Guardrails:** Use standardized `unittest.mock.patch` for subprocess, socket, and urllib calls, validating exact command arguments and return codes.

### Success & Discard Criteria

- **Success:** `tests/test_proxy_lifecycle.py` provides high-coverage hermetic tests for `ProxyLifecycle`, and all tests in `tests/commands/test_start.py` pass cleanly.
- **Discard:** Discard if any test failure or unhandled lifecycle edge case occurs.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.99  |
| entropy_pred        | 0.50  |
| impact_pred         | 8.60  |
| cost_pred           | 0.10  |
| learning_value_pred | 1.40  |
| ev_pred             | 8.96  |

### Step Metrics Rationale

- $\text{EV} = 0.99 \times 8.60 + 0.5 \times 1.40 - 0.3 \times 0.50 - 0.10 = 8.514 + 0.70 - 0.15 - 0.10 = 8.964 \approx 8.96$. Comprehensive unit testing of the isolated domain lifecycle class guarantees stability across host-local and Docker modes.

## Step 6: Complexity Ratchet Audit, Baseline Ceiling Reduction & Full Gate Verification

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Audit the removal of 5 legacy inline `# noqa` complexity suppressions across `commands/start.py` (2) and `commands/agents.py` (3). Permanently ratchet down `BASELINE_CEILING` in `tests/test_complexity_baseline.py` from 16 to 11. Execute all static checks, full pytest suite, and code formatting to ensure flawless repository hygiene.
- **Step type:** verification
- **Exploration level:** 0.00
- **Git branch:** `I-1793438378-coherence-proxy-lifecycle-class-for-start`

### Implementation Details

1. **Inline Suppression Audit & Ceiling Reduction**:
   - Audit that no new `# noqa` suppressions were introduced anywhere in `src/holon_coherence/`.
   - Verify that 5 legacy `# noqa` suppressions have been eliminated:
     - `src/holon_coherence/commands/start.py`: `ensure_proxy_running` (1), `handle_start` (1)
     - `src/holon_coherence/commands/agents.py`: `extract_runner_flags` (1), `build_agent_env` (1), `run_agent` (1)
   - Update `BASELINE_CEILING = 11` in `tests/test_complexity_baseline.py`.
   - Verify `test_complexity_baseline_ratchet_ceiling` passes and confirms exact count of remaining legacy suppressions (11).

2. **Full Multi-Tool Gate Verification**:
   - Execute full test suite: `uv run pytest`.
   - Execute Ruff lint check: `uv run ruff check .`.
   - Execute Ruff format check: `uv run ruff format --check .`.
   - Execute Prettier formatting on markdown files: `npx prettier --write "**/*.md"`.
   - Verify clean git worktree status and squash commit history into a single logical commit relative to `main`.

### Dependencies & Criticality

- **Dependencies:** Step 1 through Step 5
- **Is bottleneck:** Yes — Final quality and complexity ratchet gate before merge.

### Safety & Constraint Considerations

- **Relevant rules:** §2 Coding Conventions & Standards, Bean 0186 Complexity Limits, AGENTS.md (Squash Commits, Worktree Isolation).
- **Failure modes:** Hidden complexity violations, unformatted code, or mismatched ratchet counts.
- **Guardrails:** Automated test assertion `total_count == BASELINE_CEILING` strictly enforces ratchet integrity.

### Success & Discard Criteria

- **Success:** `BASELINE_CEILING` updated to 11, `test_complexity_baseline.py` passes, all unit/CLI tests pass cleanly, Ruff reports 0 errors, Prettier formatting passes cleanly, and commit history is squashed.
- **Discard:** Discard if any test fails or if complexity exceeds limits.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.99  |
| entropy_pred        | 0.40  |
| impact_pred         | 8.90  |
| cost_pred           | 0.10  |
| learning_value_pred | 1.20  |
| ev_pred             | 9.19  |

### Step Metrics Rationale

- $\text{EV} = 0.99 \times 8.90 + 0.5 \times 1.20 - 0.3 \times 0.40 - 0.10 = 8.811 + 0.60 - 0.12 - 0.10 = 9.191 \approx 9.19$. Ratcheting the baseline complexity ceiling down from 16 to 11 enforces permanent codebase quality improvements and locks in the decoupled architecture.

---

## Strategy Rationale

The overall plan metrics are computed using the physics-driven Expected Value (EV) formula:

$$\text{EV} = P(\text{success}) \times \text{Impact} + \mu \times \text{LearningValue} - \lambda \times \Delta S_{\text{intent}} - \text{Cost}$$

Using baseline calibration constants $\lambda = 0.3$ and $\mu = 0.5$:

$$\text{EV} = (0.98 \times 8.90) + (0.5 \times 2.20) - (0.3 \times 3.40) - 0.75 = 8.722 + 1.10 - 1.02 - 0.75 = 8.052 \approx 8.05$$

- **$P(\text{success})$ (0.98):** High probability of success grounded in well-defined domain boundaries, existing end-to-end tests in `tests/commands/test_start.py` and `tests/commands/test_agents.py`, and clear delegation patterns that preserve existing CLI and socket behaviors.
- **$\text{Impact}$ (8.90):** Encapsulates proxy lifecycle orchestration into a cohesive domain class (`ProxyLifecycle`), introduces a dedicated `stop.py` command module, eliminates 5 legacy inline `# noqa` complexity suppressions across `commands/start.py` and `commands/agents.py`, and ratchets the baseline complexity ceiling in `tests/test_complexity_baseline.py` from 16 to 11.
- **$\mu \times \text{LearningValue}$ ($0.5 \times 2.20 = 1.10$):** Demonstrates modular patterns for decomposing high-complexity subprocess orchestration, argument parsing loops, and environment variable builders into testable, single-responsibility functions conforming to Bean 0186.
- **$\lambda \times \Delta S\_{\text{intent}}$ ($0.3 \times 3.40 = 1.02$):** Well-controlled entropy distribution across 6 sequential steps totaling 3.40, remaining safely below the allocated 5.0 entropy budget.
- **$\text{Cost}$ (0.75):** Implementation effort covering domain class extraction, CLI command refactoring, helper decomposition, test suite expansion, and multi-tool gate verification.

---

## Planner Autonomy Summary

- **Intent handling:** `ACCEPT_AS_IS`
- **Reframed intent (if applicable):** NONE
- **Exploration stance:** Exploitation-dominant (0.05 exploration). The architectural boundaries for `src/holon_coherence/proxy/lifecycle.py`, the required methods (`ensure_ca`, `start`, `wait_until_ready`, `stop`), and the targets for complexity reduction in `commands/start.py` and `commands/agents.py` are explicitly defined. The execution is structural refactoring with 100% behavioral parity.
- **Safety priority level:** `standard`
- **Priority Justification:** Refactoring is confined to internal lifecycle management, command argument delegation, and environment construction. No network wire protocols, translation formats, or security credentials are being modified.

---

## Exploration

- **Proportion of steps that are exploratory:** 0.05
- **Justification:** Existing startup, CA generation, readiness polling, and agent environment construction routines are fully operational in the codebase and covered by automated tests. Minimal exploration (0.05) is allocated for validating backward-compatible re-exports and ensuring no circular dependency cycles between `proxy/lifecycle.py` and `commands/`.

---

## Safety & Constraint Alignment

- **Key world ruleset constraints that affect this plan:**
  - `holon-config/world/ruleset.md`: Runtime compatibility with Python 3.13, execution of tests strictly via `uv run pytest` from worktree root, Ruff lint and format cleanliness, docstring and comment preservation.
  - Bean 0186 Complexity Limits: Enforce McCabe $C901 \le 10$, $PLR0911 \le 6$, $PLR0912 \le 12$, $PLR0913 \le 5$, $PLR0915 \le 50$. Update and ratchet down `BASELINE_CEILING` in `tests/test_complexity_baseline.py`.
  - Testing constraints: Zero test failures under `uv run pytest`, 100% preservation of existing test cases, and authentic non-synthetic test fixtures (Rule 1).
  - Git workflow constraints: Dedicated worktree branching off `origin/main`, single squashed commit relative to `main`, no autonomous remote push.
- **Potential violations or edge cases:**
  - Circular import cycles: Potential cycles between `holon_coherence.proxy.lifecycle` and `holon_coherence.commands.docker_ops` / `commands.start`. Mitigated by having `lifecycle.py` depend only on low-level primitives (`ca_generator`, `host_local`) and moving core container operations into `lifecycle.py`.
  - Port collision or race condition: Proxy container failing to bind during rapid restart. Mitigated by retaining the exact polling loop and fallback port assignment logic.
  - In-container vs. host execution divergence: Mitigated by testing both `is_in_container()` paths in `ProxyLifecycle` unit tests.
  - Ratchet test failure: Removing `# noqa` comments without updating `BASELINE_CEILING`. Mitigated by ratcheting the ceiling down to 11 in Step 6.
- **Mitigations built into the plan:**
  - Backward-compatible facades: Re-exporting all moved functions (`ensure_proxy_running`, `wait_for_proxy_ready`, `handle_stop`, `stop_proxy_container`) across `start.py`, `stop.py`, and `docker_ops.py`.
  - Modular helper decomposition: Designing accumulator models and granular subroutines to keep cyclomatic complexity $\le 10$ and argument counts $\le 5$.
  - End-to-end regression testing: Running the full test suite to guarantee 0 regressions across unit, CLI, and integration tests.
- **Allocated Entropy Budget:** 5.0
- **Predicted Plan Entropy:** 3.40 (sum of step entropies: $0.70 + 0.70 + 0.50 + 0.60 + 0.50 + 0.40 = 3.40$)
- **Budget Compliance:** Full compliance ($3.40 \le 5.00$).

---

## Plan Description & Strategy

1. **Step 1: Create ProxyLifecycle Domain Class (`src/holon_coherence/proxy/lifecycle.py`)**:
   Establish `src/holon_coherence/proxy/lifecycle.py` with `ProxyLifecycle` class and `ProxyLifecycleConfig` dataclass. Encapsulate CA generation (`ensure_ca`), readiness polling (`wait_until_ready`), container startup across Docker and host-local execution modes (`start`), and container removal (`stop`), with zero `# noqa` suppressions adhering to Bean 0186.
2. **Step 2: Refactor Start Command (`src/holon_coherence/commands/start.py`) to Delegate to `ProxyLifecycle`**:
   Refactor `handle_start` and `ensure_proxy_running` in `commands/start.py` to delegate container startup, CA checks, and readiness polling to `ProxyLifecycle`. Eliminate both legacy `# noqa` complexity suppressions while maintaining backward-compatible facade functions.
3. **Step 3: Implement Dedicated Stop Command (`src/holon_coherence/commands/stop.py`) and Refactor Teardown Delegation**:
   Establish `commands/stop.py` as a dedicated CLI module for proxy teardown, delegating to `ProxyLifecycle.stop()`. Re-export `handle_stop` and `stop_proxy_container` for backward compatibility across `docker_ops.py`, `cli.py`, and `commands/__init__.py`.
4. **Step 4: Decompose Runner Flag and Environment Construction in `commands/agents.py`**:
   Decompose `extract_runner_flags`, `build_agent_env`, and `run_agent` in `commands/agents.py` into modular helpers. Eliminate all 3 legacy `# noqa` complexity suppressions while preserving 100% parameter and environment compatibility.
5. **Step 5: Expand Unit and CLI Tests (`tests/test_proxy_lifecycle.py` and `tests/commands/test_start.py`)**:
   Create a dedicated unit test suite `tests/test_proxy_lifecycle.py` verifying all `ProxyLifecycle` operations (`ensure_ca`, `start`, `wait_until_ready`, `stop`). Refactor and verify existing tests in `tests/commands/test_start.py` and `tests/commands/test_docker_ops.py`.
6. **Step 6: Complexity Ratchet Audit, Baseline Ceiling Reduction & Full Gate Verification**:
   Verify elimination of 5 legacy `# noqa` complexity suppressions, ratchet `BASELINE_CEILING` down from 16 to 11 in `tests/test_complexity_baseline.py`, run `uv run pytest`, execute Ruff checks, apply Prettier formatting, and prepare squashed git commit.
