# Plan for I-1792495073-coherence-fix-proxy-readiness-and-agent-tests

- **Plan ID:** P-1792495105-antigravity-agent-gemini-3.8-flash-medium}
- **Parent Intent ID:** NONE
- **Agent:** antigravity-agent (version: 1.4.2)
- **Created At:** 2026-10-20T11:18:25.668Z

---

## Planner Autonomy Summary

- **Intent handling:** `ACCEPT_AS_IS`
- **Reframed intent (if applicable):** NONE
- **Exploration stance:** Exploitation-dominant with targeted integration verification. The problem statement (Bean 0130) provides exact, unambiguous architectural specifications: the root cause is a TCP-level port race condition where mitmproxy's socket is open before HTTP routes are mounted and ready. The fix replaces simple port-binding checks with active HTTP polling against the metrics endpoint (`http://127.0.0.1:{port}/holon/api/metrics` or `/_holon/metrics`), with fast-failure container status checks and bounded retries.
- **Safety priority level:** standard
- **Priority Justification:** Changes touch CLI startup readiness detection and test suites. Standard priority is appropriate as changes are confined to proxy readiness synchronization, unit tests with mocked endpoints, and isolated integration tests marked with `@pytest.mark.integration_test`.

---

## Exploration

- **Proportion of steps that are exploratory:** 0.10
- **Justification:** The implementation mechanics of HTTP readiness polling in `src/holon_coherence/commands/start.py` and unit test mocking in `tests/test_cli.py` are deterministic. A minimal exploratory allowance (0.10) covers verifying the exact metrics endpoint route path compatibility (`/holon/api/metrics` vs `/_holon/metrics`) and ensuring agent CLI runners accept standard dry-run / `--help` flags cleanly during container bootstrap.

---

## Overall Plan Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.95  |
| entropy_pred        | 3.20  |
| impact_pred         | 8.50  |
| cost_pred           | 1.40  |
| learning_value_pred | 3.50  |
| ev_pred             | 7.47  |

### Strategy Rationale

Metrics are computed using the physics-driven Expected Value (EV) formula:
$$\text{EV} = P(\text{success}) \times \text{Impact} + \mu \times \text{LearningValue} - \lambda \times \Delta S_{\text{intent}} - \text{Cost}$$
with baseline parameters $\lambda = 0.3$ and $\mu = 0.5$:
$$\text{EV} = (0.95 \times 8.50) + (0.5 \times 3.50) - (0.3 \times 3.20) - 1.40 = 8.075 + 1.75 - 0.96 - 1.40 = 7.465 \approx 7.47$$

The high expected value reflects the elimination of cold-start race conditions that currently cause transient EOF and connection reset errors during agent CLI startups. Replacing shallow TCP checks with true application-layer HTTP readiness polling hardens orchestration reliability across all supported agents (`agy`, `pi`, `claude`, `codex`, `opencode`).

---

## Safety & Constraint Alignment

- **Key world ruleset constraints that affect this plan:**
  - Zero test regressions on existing test suite (`uv run pytest -m 'not integration_test'`).
  - Strict lint and formatting hygiene enforced by `uv run ruff check .` and `make lint`.
  - Non-blocking execution and bounded loops: all retry polling must use explicit timeouts (`PROXY_READY_TIMEOUT_SECONDS`) and bounded socket timeouts on HTTP requests.
  - Fail-fast semantics: readiness loops must immediately abort if the target docker container ceases running rather than hanging until timeout.
  - Test hermeticity: unit tests in `tests/test_cli.py` must mock HTTP calls and container status checks so unit suites run without requiring a running Docker daemon.
- **Potential violations or edge cases:**
  - Hanging requests if `urllib.request.urlopen` lacks an explicit connection timeout.
  - False positives if mitmproxy returns non-200 status codes (e.g., 502/503 during warmup).
  - Test suite slowdowns if integration tests run during standard unit test passes.
- **Mitigations built into the plan:**
  - Configure `urllib.request.urlopen` with a strict per-request timeout (e.g., 1.0 second).
  - Explicitly validate `response.status == 200` (or `200 <= status < 300`).
  - Add `@pytest.mark.integration_test` on all tests in `tests/test_agent_startup.py` to keep default unit runs hermetic and fast.
  - Catch all expected network exceptions (`urllib.error.URLError`, `ConnectionRefusedError`, `OSError`, `TimeoutError`, `http.client.RemoteDisconnected`).
- **Allocated Entropy Budget:** 15.0
- **Predicted Plan Entropy:** 3.20
- **Budget Compliance:** Full compliance ($3.20 \le 15.00$).

---

## Plan Description & Strategy

1. **Step 1: Refactor Proxy Readiness Polling in `src/holon_coherence/commands/start.py`**:
   Replace TCP socket connection check in `wait_for_proxy_ready` with active HTTP polling to `http://127.0.0.1:{port}/holon/api/metrics` (with fallback to `/_holon/metrics`). Ensure HTTP status 200 verification, exception catching, container exit fail-fast check, and timeout enforcement.
2. **Step 2: Update and Enhance CLI Unit Tests in `tests/test_cli.py`**:
   Update `TestWaitForProxyReady` to test: (a) immediate HTTP 200 success, (b) initial transient network errors followed by HTTP 200, (c) fail-fast when the container stops running, and (d) timeout raising `RuntimeError`/`TimeoutError` when proxy never becomes ready.
3. **Step 3: Add Agent Runner Startup Integration Tests in `tests/test_agent_startup.py`**:
   Create integration tests marked with `@pytest.mark.integration_test` executing cold-start CLI runner commands for `agy`, `pi`, `claude`, `codex`, and `opencode` with `-- --help` or dry-run, verifying container boot and clean termination without connection drop.
4. **Step 4: End-to-End Verification and Code Quality Validation**:
   Execute `make lint`, `uv run ruff check .`, and `uv run pytest -m 'not integration_test'` to guarantee clean static analysis and test passing.

---

## Step-by-Step Breakdown

### Step 1: Refactor Proxy Readiness Polling in `src/holon_coherence/commands/start.py`

- **Step Intent & Git Integration:**
  - Sub-intent recommendation: Implement HTTP metrics endpoint polling and fail-fast container monitoring in `wait_for_proxy_ready`.
  - Reasoning: Mitmproxy binds its listening port before internal python addons and routing trees are initialized. Polling HTTP `/holon/api/metrics` (or `/_holon/metrics`) ensures the proxy is fully operational and capable of handling traffic before agent processes launch.
  - Step type: implementation
  - Exploration level: 0.10
  - Git branch: `I-1792495073-coherence-fix-proxy-readiness-and-agent-tests`
- **Implementation Details:**
  - Modify `wait_for_proxy_ready(port: int, container_name: str | None = None, timeout: float = PROXY_READY_TIMEOUT_SECONDS) -> bool` in [start.py](file:///home/holon/src/holon_coherence/commands/start.py):
    1. Define the candidate health check URLs: primary `f"http://127.0.0.1:{port}/holon/api/metrics"` and fallback `f"http://127.0.0.1:{port}/_holon/metrics"`.
    2. Loop with polling interval (e.g. 0.25s) until `time.time() - start_time >= timeout`.
    3. Within loop, if `container_name` is provided, call container status check (e.g. `is_container_running(container_name)`); if False, raise `RuntimeError(f"Proxy container '{container_name}' exited prematurely.")` or fail fast.
    4. Use `urllib.request.urlopen(req, timeout=1.0)` to query the endpoint. Check `response.status == 200`. On HTTP 200, return `True`.
    5. Catch `(urllib.error.URLError, ConnectionRefusedError, OSError, TimeoutError, http.client.RemoteDisconnected)` and sleep for poll interval.
    6. If timeout expires without receiving HTTP 200, raise `TimeoutError` or return `False` as dictated by existing API contract (raising descriptive error if proxy failed to become ready).
- **Dependencies & Criticality:**
  - Dependencies: None
  - Is bottleneck: Yes
- **Safety & Constraint Considerations:**
  - Relevant rules: Non-blocking timeouts, clean resource release on socket connections (use `with urllib.request.urlopen(...)`).
  - Failure modes: Unhandled HTTP status codes (e.g. 404 or 500) hanging indefinitely.
  - Guardrails: Catch `urllib.error.HTTPError` specifically: if 404, try the alternate metrics path before retrying; if 500, log warning and retry until timeout.
- **Success & Discard Criteria:**
  - Success: `wait_for_proxy_ready` queries HTTP metrics endpoint, verifies 200 OK, detects container exit immediately, and cleanly exits loop upon success.
  - Discard: If mitmproxy intercepts or alters internal metrics routes unpredictably, verify addon route definitions in `mitm_addon.py`.
- **Step Metrics Table:**

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.96  |
| entropy_pred        | 0.90  |
| impact_pred         | 8.00  |
| cost_pred           | 0.40  |
| learning_value_pred | 3.00  |
| ev_pred             | 8.51  |

- **Step Metrics Rationale:**
  $\text{EV} = 0.96 \times 8.00 + 0.5 \times 3.00 - 0.3 \times 0.90 - 0.40 = 7.68 + 1.50 - 0.27 - 0.40 = 8.51$. High impact due to eliminating the primary cause of agent startup flakiness.

---

### Step 2: Update and Enhance CLI Unit Tests in `tests/test_cli.py`

- **Step Intent & Git Integration:**
  - Sub-intent recommendation: Update `TestWaitForProxyReady` unit test suite to validate HTTP polling behavior.
  - Reasoning: Unit tests must cover all branching paths of the newly introduced HTTP polling logic in isolation without requiring external network or container daemons.
  - Step type: implementation
  - Exploration level: 0.05
  - Git branch: `I-1792495073-coherence-fix-proxy-readiness-and-agent-tests`
- **Implementation Details:**
  - In [test_cli.py](file:///home/holon/tests/test_cli.py), update class `TestWaitForProxyReady`:
    1. `test_wait_for_proxy_ready_immediate_success`: Mock `urllib.request.urlopen` returning a MagicMock with `status=200`, verify `wait_for_proxy_ready` returns `True` on the first attempt.
    2. `test_wait_for_proxy_ready_retry_success`: Mock `urllib.request.urlopen` raising `urllib.error.URLError(ConnectionRefusedError())` twice, then returning `status=200`; verify it succeeds and retries appropriately.
    3. `test_wait_for_proxy_ready_container_exit_fail_fast`: Mock `is_container_running` returning `False` on the second poll; verify function immediately raises `RuntimeError` without waiting for the full timeout.
    4. `test_wait_for_proxy_ready_timeout`: Mock `urllib.request.urlopen` continuously raising `ConnectionRefusedError`; set short timeout (e.g. 0.2s); verify timeout handling (`TimeoutError` or `False` depending on signature contract).
    5. Mock `time.sleep` in all tests to ensure test execution runs in milliseconds without real sleep pauses.
- **Dependencies & Criticality:**
  - Dependencies: Step 1
  - Is bottleneck: No
- **Safety & Constraint Considerations:**
  - Relevant rules: Hermetic testing, fast test execution, mocking external IO.
  - Failure modes: Tests accidentally making real network calls or waiting real seconds.
  - Guardrails: Patch `urllib.request.urlopen`, `time.sleep`, and container inspection helpers.
- **Success & Discard Criteria:**
  - Success: All test cases in `TestWaitForProxyReady` pass cleanly under `pytest`.
  - Discard: If tests fail, align mock return values with exact `http.client.HTTPResponse` attributes.
- **Step Metrics Table:**

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.98  |
| entropy_pred        | 0.80  |
| impact_pred         | 7.50  |
| cost_pred           | 0.30  |
| learning_value_pred | 2.50  |
| ev_pred             | 8.06  |

- **Step Metrics Rationale:**
  $\text{EV} = 0.98 \times 7.50 + 0.5 \times 2.50 - 0.3 \times 0.80 - 0.30 = 7.35 + 1.25 - 0.24 - 0.30 = 8.06$. Ensures test coverage regressions are prevented.

---

### Step 3: Add Agent Runner Startup Integration Tests in `tests/test_agent_startup.py`

- **Step Intent & Git Integration:**
  - Sub-intent recommendation: Implement cold-start integration tests for all supported agent runners.
  - Reasoning: To verify that real cold-start orchestration works end-to-end without socket drops or premature process terminations across all supported agents (`agy`, `pi`, `claude`, `codex`, `opencode`).
  - Step type: implementation
  - Exploration level: 0.15
  - Git branch: `I-1792495073-coherence-fix-proxy-readiness-and-agent-tests`
- **Implementation Details:**
  - Create [test_agent_startup.py](file:///home/holon/tests/test_agent_startup.py):
    1. Decorate module or test classes with `@pytest.mark.integration_test`.
    2. Add parameterized test `test_agent_runner_cold_start(agent_name)` parameterized over `["agy", "pi", "claude", "codex", "opencode"]`.
    3. In each test case:
       - Invoke CLI entrypoint: `holon-coherence <agent_name> -- --help` (or equivalent dry-run / help invocation supported by runner).
       - Ensure proxy container startup is automatically triggered if not already running.
       - Assert exit code is 0 (or expected help exit code).
       - Assert no unexpected connection reset, EOFError, or unhandled tracebacks appear in stdout/stderr.
    4. Implement clean teardown fixtures to stop or clean up proxy containers if booted during integration tests.
- **Dependencies & Criticality:**
  - Dependencies: Step 1, Step 2
  - Is bottleneck: No
- **Safety & Constraint Considerations:**
  - Relevant rules: Segregation of integration tests from fast unit suites using pytest markers.
  - Failure modes: Integration tests attempting to run in CI environments without Docker privileges.
  - Guardrails: Explicit `@pytest.mark.integration_test` ensures `pytest -m 'not integration_test'` completely skips them. Add `pytest.importorskip` or `docker_available` fixture check if Docker daemon is unreachable.
- **Success & Discard Criteria:**
  - Success: Each runner boots the proxy cleanly without EOF or connection drops.
  - Discard: If an agent runner binary is not installed locally in the testing environment, support mock runner execution or skip if executable is missing (`shutil.which(agent_name) is None`).
- **Step Metrics Table:**

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.92  |
| entropy_pred        | 1.00  |
| impact_pred         | 8.50  |
| cost_pred           | 0.50  |
| learning_value_pred | 4.00  |
| ev_pred             | 9.02  |

- **Step Metrics Rationale:**
  $\text{EV} = 0.92 \times 8.50 + 0.5 \times 4.00 - 0.3 \times 1.00 - 0.50 = 7.82 + 2.00 - 0.30 - 0.50 = 9.02$. High learning value and impact by validating real-world agent startup pipelines.

---

### Step 4: End-to-End Verification and Code Quality Validation

- **Step Intent & Git Integration:**
  - Sub-intent recommendation: Run comprehensive static analysis, formatting checks, and unit test verification.
  - Reasoning: Ensure all lint rules pass, type checks succeed, and no regressions exist in the main unit test suite.
  - Step type: verification
  - Exploration level: 0.00
  - Git branch: `I-1792495073-coherence-fix-proxy-readiness-and-agent-tests`
- **Implementation Details:**
  - Execute:
    1. `make lint`
    2. `uv run ruff check .`
    3. `uv run pytest -m 'not integration_test'`
  - Verify that:
    - Zero linting errors or warnings are reported.
    - All unit tests pass cleanly without regressions.
    - Integration tests are cleanly excluded from the standard unit pass.
- **Dependencies & Criticality:**
  - Dependencies: Step 1, Step 2, Step 3
  - Is bottleneck: Yes
- **Safety & Constraint Considerations:**
  - Relevant rules: Constraint alignment requiring 100% clean lint and unit test passes.
  - Failure modes: Formatting discrepancies or lingering import errors.
  - Guardrails: Auto-fix formatting issues using `ruff format .` if necessary before final check.
- **Success & Discard Criteria:**
  - Success: `make lint` exits 0, `ruff check` exits 0, `pytest -m 'not integration_test'` passes with 100% success.
  - Discard: Revert any incidental styling or configuration changes if checks fail.
- **Step Metrics Table:**

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.99  |
| entropy_pred        | 0.50  |
| impact_pred         | 7.00  |
| cost_pred           | 0.20  |
| learning_value_pred | 1.50  |
| ev_pred             | 7.33  |

- **Step Metrics Rationale:**
  $\text{EV} = 0.99 \times 7.00 + 0.5 \times 1.50 - 0.3 \times 0.50 - 0.20 = 6.93 + 0.75 - 0.15 - 0.20 = 7.33$. Provides definitive gatekeeper verification for production deployment.
