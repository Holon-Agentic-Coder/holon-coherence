I am running the test suite to inspect baseline test results before authoring the plan.

# Plan for I-1791537698-coherence-security-and-network-hardening

- **Plan ID:** P-1791537711-antigravity-agent-gemini-3.8-flash-medium
- **Parent Intent ID:** NONE
- **Agent:** antigravity-agent (version: 1.1.22)
- **Created At:** 2026-10-09T09:21:51.296Z

## Planner Autonomy Summary

- **Intent handling:** ACCEPT_AS_IS
- **Reframed intent (if applicable):** NONE
- **Exploration stance:** exploit with targeted verification of restrictive POSIX file permissions, sensitive credential
  masking patterns, Docker port binding configurations, and unit test suites.
- **Safety priority level:** strict
- **Priority Justification:** This task addresses security hardening across PKI cryptographic material, wire logs, cache
  databases, and container network bindings to eliminate CWE-732 (Incorrect Permission Assignment for Critical Resource)
  and CWE-312 (Cleartext Storage of Sensitive Information). Strict verification guarantees no secrets leak into
  transactions or disk, and restrictive access modes are enforced deterministically without breaking proxy operations.

## Exploration

- **Proportion of steps that are exploratory:** 0.00
- **Justification:** The requirements across Beans 0070, 0073, and 0071 are concrete, unambiguous, and fully specified
  by existing codebase components. Implementation involves deterministic POSIX file mode changes, regex expansion for
  secret scrubbing, Docker argument list adjustments, documentation updates, and hermetic pytest additions.

## Overall Plan Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.98  |
| entropy_pred        | 0.3   |
| impact_pred         | 90.0  |
| cost_pred           | 3.4   |
| learning_value_pred | 3.5   |
| ev_pred             | 86.46 |

### Strategy Rationale

The overall plan metrics are derived from the individual step metrics and the system evaluation formula:

- **p_success_pred**: 0.98. Dictated by the bottleneck steps (Steps 1, 3, and 5: 0.98) which handle filesystem mode
  enforcement, regex-based recursive redaction, and container networking argument construction.
- **entropy_pred**: 0.3. Represents the maximum single-step risk profile (Steps 1, 3, 5: 0.3). The sum of individual
  step entropies is 1.6 (`0.3 + 0.2 + 0.3 + 0.2 + 0.3 + 0.2 + 0.1 = 1.6`), which remains well within the allocated
  entropy budget of 15.0.
- **impact_pred**: 90.0. Closes security vulnerabilities across Beans 0070, 0073, and 0071 by enforcing POSIX
  0o700/0o600 permissions on sensitive cryptographic keys and databases (CWE-732), expanding redaction to prevent secret
  leakage in wire logs (CWE-312), enabling container web dashboard port forwarding, and providing comprehensive test
  coverage.
- **cost_pred**: 3.4. Sum of all step execution costs (`0.6 + 0.4 + 0.6 + 0.4 + 0.5 + 0.4 + 0.5 = 3.4`).
- **learning_value_pred**: 3.5. Solidifies defensive programming patterns across the repository for filesystem security,
  credential sanitization, container host-gateway networking, and automated CLI testing.
- **ev_pred**: 86.46. Calculated using the physics-driven Expected Value formula:
  `EV = P(success) * Impact + mu * LearningValue - lambda * Delta_S_intent - Cost`. With canonical system parameters
  `lambda = 0.3` and `mu = 0.5`: `EV = 0.98 * 90.0 + 0.5 * 3.5 - 0.3 * 0.3 - 3.4 = 88.20 + 1.75 - 0.09 - 3.4 = 86.46`.

## Safety & Constraint Alignment

- **Key world ruleset constraints that affect this plan:**
  - `holon-config/world/ruleset.md` §1: Runtime & Environment Specification: Target Python `==3.13.*`, package execution
    managed strictly via `uv run` in the root `.venv`.
  - `holon-config/world/ruleset.md` §2: Coding Conventions & Standards: PEP 8 adherence, explicit static typing with
    standard library `typing`, docstring retention, and zero Ruff linting/formatting errors.
  - `holon-config/world/ruleset.md` §3: Testing Constraints: Hermetic test isolation via `uv run pytest`, zero unstaged
    regressions, and test-driven validation for all modified logic.
  - `holon-config/world/constraints.md` §1: Git Flow: Isolated branches following Holon naming conventions, clean commit
    boundaries, no direct remote push to `main`.
  - `holon-config/world/constraints.md` §2: Sandbox Containment: Operations restricted to workspace root; ephemeral
    process isolation without persistent shell environment mutations.
  - `holon-config/world/constraints.md` §3: Ledger Immutability: Zero modifications to historical ledger records in
    `holon-knowledge/ledger/*.jsonl`.
  - `AGENTS.md` Invariants: Strict repository separation (Rule 5), universal credentials `HOLON_AGENT_KEY` with native
    auth fallback (Rule 4), and process isolation (Rule 2).
- **Potential violations or edge cases:**
  - Applying `0o600` on directories instead of `0o700`, which would prevent traversal and cause `PermissionError` when
    opening files.
  - Overwriting existing directory permissions without accounting for varying umasks or pre-existing files.
  - Secret redaction regex over-matching benign keys or failing on casing variants (e.g. `Client_Secret`,
    `REFRESH_TOKEN`).
  - Redaction altering payload object types (e.g., converting tuples to lists or dropping non-string types).
  - Web dashboard port forwarding colliding with proxy listening ports or failing when `--web` is disabled.
- **Mitigations built into the plan:**
  - Explicit separation between directory permissions (`0o700`) and regular file permissions (`0o600`).
  - Pre-creating files with explicit permission modes using `os.open(path, os.O_WRONLY | os.O_CREAT | ..., 0o600)`
    combined with `os.chmod` to avoid race conditions or umask relaxation.
  - Comprehensive unit test assertions in `tests/test_coherence.py` validating octal mode masks for all sensitive
    artifacts.
  - Case-insensitive regex matching for secret keys (`(?i)`) combined with recursive traversal preserving structures.
  - Unit tests in `tests/test_cli.py` verifying Docker command flag lists with and without `--web` and `--web-port`.
- **Residual risk accepted (and why):**
  - Existing files created outside this process before execution will be updated to `0o600`/`0o700` upon next access by
    the library functions.
- **Allocated Entropy Budget:** 15.0
- **Predicted Plan Entropy:** 1.6
- **Budget Compliance:** The plan requires an entropy budget of 1.6, fitting comfortably within the allocated limit of
  15.0.

## Plan Description & Strategy

This implementation is divided into 7 sequential steps:

1. **Step 1: Harden File and Directory Permissions Across PKI, Cache, and Wire Logging (Bean 0070)**: Update
   `ca_generator.py`, `hybrid_cache.py`, `mitm_addon.py`, and `cli.py` to enforce `0o700` on directories and `0o600` on
   sensitive files (CWE-732).
2. **Step 2: Add Comprehensive Unit Tests for File and Directory Permission Hardening (Bean 0070)**: Author unit tests
   in `tests/test_coherence.py` asserting `0o700` directory modes and `0o600` file modes for Root CA keys, SQLite cache
   databases, and wire logs.
3. **Step 3: Expand Secret Redaction Patterns in `mitm_addon.py` and `payload_cleaner.py` (Bean 0073)**: Extend
   `_SECRET_DICT_KEY_PATTERN` and scrubbing routines to mask standalone `auth`, `credential`, `credentials`,
   `client_secret`, and `refresh_token` (CWE-312).
4. **Step 4: Add Unit Tests for Expanded Secret Redaction Patterns (Bean 0073)**: Author unit tests in
   `tests/test_coherence.py` validating that nested dictionaries and headers containing the new secret keys are masked
   with `[REDACTED]`.
5. **Step 5: Fix Web Dashboard Port Forwarding in CLI and Update Sidecar Documentation (Bean 0071)**: Update Docker
   command generation in `src/holon_coherence/cli.py` and document `mitmweb` usage in
   `docs/running_mitm_sidecar_guide.md`.
6. **Step 6: Add CLI Docker Command Construction Tests for Web Dashboard Port Forwarding (Bean 0071)**: Add unit tests
   in `tests/test_cli.py` validating Docker argument construction with and without `--web` and custom `--web-port`.
7. **Step 7: Full System Verification, Linting, Formatting, and Hygiene Checks**: Run test suites (`pytest`),
   lint/format checks (`ruff`), and Markdown validation (`prettier`) to ensure production readiness.

---

## Step 1: Harden File and Directory Permissions Across PKI, Cache, and Wire Logging (Bean 0070)

- **Sub‑intent recommendation:** NO
- **Reasoning:** Core module changes enforcing restrictive file and directory permissions directly within
  `src/holon_coherence/`.
- **Step Type:** IMPLEMENT
- **Exploration level:** EXPLOIT

### Intent & Git Integration

- **Step Intent:** Mitigate CWE-732 by enforcing `0o700` permissions on directories and `0o600` permissions on private
  keys, SQLite database files, and wire log JSONL files.
- **Git branch:**
  `I-1791537698-coherence-security-and-network-hardening/P-1791537711-antigravity-agent-gemini-3.8-flash-medium/E-permission-hardening/_`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- In `src/holon_coherence/ca_generator.py`:
  - Update `_ensure_root_ca`: When creating `cert_dir`, enforce `mode=0o700` in `os.makedirs` and invoke
    `os.chmod(cert_dir, 0o700)` to ensure existing directories are hardened.
  - In `_harden_key_permissions`: Verify `os.chmod(ca_key_path, 0o600)`.
  - In `_sync_mitmproxy_ca`: Ensure `mitm_ca_pem` is opened with `0o600` via `os.open` and explicitly execute
    `os.chmod(mitm_ca_pem, 0o600)` to secure combined private key material.
  - Ensure any host private keys generated are set to `0o600`.
- In `src/holon_coherence/hybrid_cache.py`:
  - In `HybridCacheStore.__init__`: Enforce `mode=0o700` in `os.makedirs(cache_dir, ...)` and execute
    `os.chmod(cache_dir, 0o700)`.
  - In `HybridCacheStore._init_db`: After database connection creation/table initialization, execute
    `os.chmod(self.db_path, 0o600)` to enforce owner read/write permissions on `llm_cache.db`.
- In `src/holon_coherence/mitm_addon.py`:
  - In `_write_transaction_sync`: Ensure `wire_log_dir` is created with `mode=0o700` and hardened with
    `os.chmod(wire_log_dir, 0o700)`.
  - For atomic transaction write files: Pre-create `tmp_filepath` with
    `os.open(tmp_filepath, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)` or apply `os.chmod(tmp_filepath, 0o600)`
    before atomic `os.replace`.
  - For `transactions.jsonl`: When opening or creating `jsonl_path`, ensure the file descriptor uses `0o600` mode (or
    apply `os.chmod(jsonl_path, 0o600)`) so wire transaction history is owner read/write only.
- In `src/holon_coherence/cli.py`:
  - In `cli.py` start command initialization: Ensure `ca_dir`, `cache_dir`, and `logs_dir` are created with `mode=0o700`
    and execute `os.chmod` to enforce `0o700` on all three host directories.

### Dependencies & Criticality

- **Depends on:** NONE
- **Is Bottleneck:** YES (Downstream unit tests depend on these permission enforcements)

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §2 (PEP 8, docstrings, type annotations).
- **Potential failure modes for this step:** Passing file modes to directories (causing traversal failures) or
  attempting `os.chmod` on non-existent paths.
- **Guardrails and early‑abort checks:** Use `stat.S_IMODE(os.stat(path).st_mode)` checks to verify exact permissions in
  local probes.

### Success & Discard Criteria

- **Success:** Directories are created and preserved with `0o700`; files containing keys, cache DB, and transaction logs
  are set to `0o600`.
- **Discard:** Discard if directory traversal fails or file permissions remain world/group readable.

### Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.98  |
| entropy_pred        | 0.3   |
| impact_pred         | 86.0  |
| cost_pred           | 0.6   |
| learning_value_pred | 1.5   |
| ev_pred             | 84.34 |

### Step Metrics Rationale

- High `p_success_pred` (0.98) as POSIX file permission mechanisms in Python standard library (`os.chmod`, `os.open`)
  are deterministic.
- Derivation: `EV = 0.98 * 86.0 + 0.5 * 1.5 - 0.3 * 0.3 - 0.6 = 84.28 + 0.75 - 0.09 - 0.6 = 84.34`.

---

## Step 2: Add Comprehensive Unit Tests for File and Directory Permission Hardening (Bean 0070)

- **Sub‑intent recommendation:** NO
- **Reasoning:** Authoring unit tests in `tests/test_coherence.py` to validate Bean 0070 implementations.
- **Step Type:** TEST
- **Exploration level:** EXPLOIT

### Intent & Git Integration

- **Step Intent:** Verify that directories and sensitive files created by `ca_generator`, `hybrid_cache`, and
  `mitm_addon` have strict `0o700` and `0o600` permissions.
- **Git branch:**
  `I-1791537698-coherence-security-and-network-hardening/P-1791537711-antigravity-agent-gemini-3.8-flash-medium/E-permission-tests/_`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- In `tests/test_coherence.py`:
  - Extend `test_ca_generator` (or add `test_ca_generator_permissions`):
    - Assert that `cert_dir` has mode `0o700` using `stat.S_IMODE(os.stat(cert_dir).st_mode) == 0o700`.
    - Assert that `ca.key` and `mitmproxy-ca.pem` have mode `0o600` using
      `stat.S_IMODE(os.stat(path).st_mode) == 0o600`.
  - Add `test_hybrid_cache_permissions`:
    - Initialize `HybridCacheStore` in a temporary directory.
    - Assert that `cache_dir` has mode `0o700`.
    - Assert that `llm_cache.db` has mode `0o600`.
  - Add `test_mitm_wire_log_permissions`:
    - Invoke `_write_transaction_sync` with a sample record into a temporary log directory.
    - Assert that the log directory has mode `0o700`.
    - Assert that generated JSON turn files and `transactions.jsonl` have mode `0o600`.
- Execute tests via `uv run pytest tests/test_coherence.py`.

### Dependencies & Criticality

- **Depends on:** Step 1
- **Is Bottleneck:** NO

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §3 (Hermetic test isolation, zero unstaged regressions).
- **Potential failure modes for this step:** Permission masks affected by system `umask` if files were not explicitly
  chmodded.
- **Guardrails and early‑abort checks:** Use `tempfile.TemporaryDirectory` to isolate all filesystem operations.

### Success & Discard Criteria

- **Success:** All permission assertion tests pass cleanly and consistently.
- **Discard:** Discard if tests fail or require root privileges to verify file modes.

### Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.99  |
| entropy_pred        | 0.2   |
| impact_pred         | 84.0  |
| cost_pred           | 0.4   |
| learning_value_pred | 1.0   |
| ev_pred             | 83.20 |

### Step Metrics Rationale

- Very high `p_success_pred` (0.99) and low entropy (0.2) as test assertions directly inspect `os.stat` mode flags.
- Derivation: `EV = 0.99 * 84.0 + 0.5 * 1.0 - 0.3 * 0.2 - 0.4 = 83.16 + 0.50 - 0.06 - 0.4 = 83.20`.

---

## Step 3: Expand Secret Redaction Patterns in `mitm_addon.py` and `payload_cleaner.py` (Bean 0073)

- **Sub‑intent recommendation:** NO
- **Reasoning:** Updating regex patterns and dictionary sanitization algorithms across token reduction and proxy
  modules.
- **Step Type:** IMPLEMENT
- **Exploration level:** EXPLOIT

### Intent & Git Integration

- **Step Intent:** Mitigate CWE-312 by expanding `_SECRET_DICT_KEY_PATTERN` and scrubbing routines to mask standalone
  `auth`, `credential`, `credentials`, `client_secret`, and `refresh_token`.
- **Git branch:**
  `I-1791537698-coherence-security-and-network-hardening/P-1791537711-antigravity-agent-gemini-3.8-flash-medium/E-secret-redaction/_`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- In `src/holon_coherence/mitm_addon.py`:
  - Locate `_SECRET_DICT_KEY_PATTERN`.
  - Expand pattern to match case-insensitively:
    - Standalone `auth`
    - Standalone `credential`
    - Standalone `credentials`
    - `client_secret` (and `client-secret`)
    - `refresh_token` (and `refresh-token`)
    - Along with existing patterns (`password`, `passwd`, `api_key`, `apikey`, `api_token`, `auth_token`,
      `access_token`, `id_token`, `secret_key`, `secret`, `private_key`, `session_token`).
  - Verify that `_SECRET_HEADER_NAMES` includes `credential`, `credentials`, and `auth` if passed as header keys.
  - Review `scrub_payload` and `scrub_headers` to ensure they recursively traverse nested dictionary keys, list
    elements, and strings, replacing matched keys and credential strings with `[REDACTED]`.
- In `src/holon_coherence/payload_cleaner.py`:
  - Align secret scrubbing and sanitization constants: Define `_SECRET_DICT_KEY_PATTERN` matching the identical expanded
    regex.
  - Ensure payload context cleaning and serialization functions scrub dictionary keys matching
    `_SECRET_DICT_KEY_PATTERN` or delegate to standard redaction logic.
  - Ensure no unintended modification of legitimate message payload fields occurs (e.g. `role`, `content`, `messages`).

### Dependencies & Criticality

- **Depends on:** NONE
- **Is Bottleneck:** YES (Downstream secret redaction tests depend on this)

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §2 (PEP 8, strict type annotations).
- **Potential failure modes for this step:** Regex catastrophic backtracking or accidental redaction of non-credential
  payload keys containing substrings (e.g. `author`, `authenticity`).
- **Guardrails and early‑abort checks:** Use strict anchors `^(?:...)$` with exact words and optional separator
  deliminators (`[-_]?`).

### Success & Discard Criteria

- **Success:** Keys `auth`, `credential`, `credentials`, `client_secret`, `refresh_token` are redacted to `[REDACTED]`,
  while keys like `author` remain unchanged.
- **Discard:** Discard if recursive dictionary traversal mutates data types or leaves secrets unmasked.

### Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.98  |
| entropy_pred        | 0.3   |
| impact_pred         | 88.0  |
| cost_pred           | 0.6   |
| learning_value_pred | 1.5   |
| ev_pred             | 86.30 |

### Step Metrics Rationale

- High `p_success_pred` (0.98) as regex pattern compilation and dictionary traversal are straightforward to verify.
- Derivation: `EV = 0.98 * 88.0 + 0.5 * 1.5 - 0.3 * 0.3 - 0.6 = 86.24 + 0.75 - 0.09 - 0.6 = 86.30`.

---

## Step 4: Add Unit Tests for Expanded Secret Redaction Patterns (Bean 0073)

- **Sub‑intent recommendation:** NO
- **Reasoning:** Adding unit tests to validate expanded secret redaction behavior across diverse payload schemas.
- **Step Type:** TEST
- **Exploration level:** EXPLOIT

### Intent & Git Integration

- **Step Intent:** Verify that `scrub_payload`, `scrub_headers`, and payload cleaners correctly mask nested secret
  structures.
- **Git branch:**
  `I-1791537698-coherence-security-and-network-hardening/P-1791537711-antigravity-agent-gemini-3.8-flash-medium/E-redaction-tests/_`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- In `tests/test_coherence.py`:
  - Add `TestSecretRedaction` test class:
    - Test standalone dictionary key masking: verify that `{"auth": "supersecret"}` becomes `{"auth": "[REDACTED]"}`.
    - Test credential keys: verify `{"credential": "xyz"}`, `{"credentials": {"sub_key": "abc"}}` become
      `{"credential": "[REDACTED]"}`, `{"credentials": "[REDACTED]"}`.
    - Test OAuth keys: verify `{"client_secret": "cs123"}`, `{"refresh_token": "rt456"}` become
      `{"client_secret": "[REDACTED]"}`, `{"refresh_token": "[REDACTED]"}`.
    - Test casing insensitivity: verify `{"Client_Secret": "...", "REFRESH_TOKEN": "...", "AUTH": "..."}` are all
      masked.
    - Test nested structures: dictionaries embedded within lists within dictionaries containing sensitive keys at
      depth >= 3.
    - Test negative cases (anti-false-positive): verify keys such as `author`, `authenticity`, and
      `authentication_status` are NOT redacted unless their values contain explicit token patterns.
    - Test `scrub_headers` with the expanded secret header names and dictionary keys.
- Run tests via `uv run pytest tests/test_coherence.py -k test_secret_redaction`.

### Dependencies & Criticality

- **Depends on:** Step 3
- **Is Bottleneck:** NO

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §3 (Hermetic test isolation).
- **Potential failure modes for this step:** Test data containing raw strings that trip static analysis security
  linters.
- **Guardrails and early‑abort checks:** Use synthetic placeholder strings (`fake_secret_token_12345`) for test
  assertions.

### Success & Discard Criteria

- **Success:** All nested secret masking assertions pass with zero false positives or unmasked credentials.
- **Discard:** Discard if false positives modify benign API keys or structures.

### Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.99  |
| entropy_pred        | 0.2   |
| impact_pred         | 85.0  |
| cost_pred           | 0.4   |
| learning_value_pred | 1.0   |
| ev_pred             | 84.19 |

### Step Metrics Rationale

- High `p_success_pred` (0.99) with deterministic dictionary equality assertions.
- Derivation: `EV = 0.99 * 85.0 + 0.5 * 1.0 - 0.3 * 0.2 - 0.4 = 84.15 + 0.50 - 0.06 - 0.4 = 84.19`.

---

## Step 5: Fix Web Dashboard Port Forwarding in CLI and Update Sidecar Documentation (Bean 0071)

- **Sub‑intent recommendation:** NO
- **Reasoning:** Modifying CLI Docker run argument assembly and updating operational markdown documentation.
- **Step Type:** IMPLEMENT
- **Exploration level:** EXPLOIT

### Intent & Git Integration

- **Step Intent:** Ensure Docker run command correctly binds web dashboard ports and verify internal container `mitmweb`
  arguments, updating user guides.
- **Git branch:**
  `I-1791537698-coherence-security-and-network-hardening/P-1791537711-antigravity-agent-gemini-3.8-flash-medium/E-web-dashboard-fix/_`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- In `src/holon_coherence/cli.py`:
  - Review `start` subcommand argument parser: verify `--web` (flag) and `--web-port` (integer default 8081).
  - In Docker run command construction for host mode:
    - When `args.web` is enabled: ensure port binding `-p 127.0.0.1:{args.web_port}:8081` (or
      `-p {args.web_port}:{args.web_port}` depending on container mapping convention) is cleanly added to `docker_cmd`.
    - Ensure container arguments append `--web --web-port 8081`.
  - In container entrypoint execution (`is_in_container()` branch):
    - When `args.web` is enabled, verify that `mitmweb` is launched with
      `--web-host 0.0.0.0 --web-port str(args.web_port)` to allow external connections from the host to reach the web
      dashboard through the mapped port.
- In `docs/running_mitm_sidecar_guide.md`:
  - Update Docker run sidecar instructions to include the web dashboard port mapping option (`-p 127.0.0.1:8081:8081`).
  - Add section describing how to enable `mitmweb` via `holon-coherence start --web --web-port 8081` and access the
    interactive web UI at `http://127.0.0.1:8081`.
  - Document that the web dashboard binds to `0.0.0.0` internally within the container while exposing `127.0.0.1` on the
    host to maintain security.

### Dependencies & Criticality

- **Depends on:** NONE
- **Is Bottleneck:** YES (Downstream CLI unit tests and doc checks depend on this)

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §2 (Docstring and formatting standards).
- **Potential failure modes for this step:** Binding web host to public interfaces on the host machine rather than
  `127.0.0.1`, exposing the web dashboard to external network access.
- **Guardrails and early‑abort checks:** Ensure host Docker port forwarding is explicitly bound to
  `127.0.0.1:{args.web_port}:8081`.

### Success & Discard Criteria

- **Success:** Docker command binds `127.0.0.1:{args.web_port}:8081` when `--web` is enabled, internal `mitmweb` listens
  on `0.0.0.0`, and documentation explains usage.
- **Discard:** Discard if dashboard binds insecurely or breaks when `--web` is omitted.

### Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.98  |
| entropy_pred        | 0.3   |
| impact_pred         | 85.0  |
| cost_pred           | 0.5   |
| learning_value_pred | 1.2   |
| ev_pred             | 83.31 |

### Step Metrics Rationale

- High `p_success_pred` (0.98) as CLI argument list construction is deterministic and easily validated.
- Derivation: `EV = 0.98 * 85.0 + 0.5 * 1.2 - 0.3 * 0.3 - 0.5 = 83.30 + 0.60 - 0.09 - 0.5 = 83.31`.

---

## Step 6: Add CLI Docker Command Construction Tests for Web Dashboard Port Forwarding (Bean 0071)

- **Sub‑intent recommendation:** NO
- **Reasoning:** Adding unit tests in `tests/test_cli.py` to assert Docker command arguments with and without web flags.
- **Step Type:** TEST
- **Exploration level:** EXPLOIT

### Intent & Git Integration

- **Step Intent:** Verify `test_cli.py` tests for `start` subcommand with `--web`, `--web-port`, and default parameters.
- **Git branch:**
  `I-1791537698-coherence-security-and-network-hardening/P-1791537711-antigravity-agent-gemini-3.8-flash-medium/E-cli-web-tests/_`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- In `tests/test_cli.py`:
  - Add `test_start_command_with_web_flag`:
    - Mock Docker daemon, container detection, and subprocess execution.
    - Invoke `main(["start", "-d", "--web"])`.
    - Inspect captured `docker run` command argument list.
    - Assert that `-p` with `127.0.0.1:8081:8081` is present.
    - Assert that container command includes `--web` and `--web-port 8081`.
  - Add `test_start_command_with_custom_web_port`:
    - Invoke `main(["start", "-d", "--web", "--web-port", "9090"])`.
    - Assert that `-p` with `127.0.0.1:9090:8081` is present in `docker run` arguments.
  - Add `test_start_command_without_web_flag_omits_web_port`:
    - Invoke `main(["start", "-d"])`.
    - Assert that no web port mapping (8081) or `--web` flag appears in the Docker command.
  - Add `test_in_container_start_with_web_passes_web_host`:
    - Mock `is_in_container` returning `True`.
    - Mock `subprocess.run` to capture command.
    - Invoke `main(["start", "--web", "--web-port", "8081"])`.
    - Assert tool is `mitmweb`.
    - Assert `--web-host 0.0.0.0` and `--web-port 8081` are in the command list.
- Run tests via `uv run pytest tests/test_cli.py -k test_start_command`.

### Dependencies & Criticality

- **Depends on:** Step 5
- **Is Bottleneck:** NO

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §3 (Test isolation, no real docker daemon calls).
- **Potential failure modes for this step:** Tests accidentally attempting to execute live Docker commands.
- **Guardrails and early‑abort checks:** Patch `check_docker_daemon`, `ensure_docker_image`, and `subprocess.run`.

### Success & Discard Criteria

- **Success:** All CLI start command tests pass and assert correct command line construction.
- **Discard:** Discard if CLI tests mock incorrectly or fail on standard start options.

### Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.99  |
| entropy_pred        | 0.2   |
| impact_pred         | 84.0  |
| cost_pred           | 0.4   |
| learning_value_pred | 1.0   |
| ev_pred             | 83.20 |

### Step Metrics Rationale

- High `p_success_pred` (0.99) as CLI argument tests use well-established mocks already present in `tests/test_cli.py`.
- Derivation: `EV = 0.99 * 84.0 + 0.5 * 1.0 - 0.3 * 0.2 - 0.4 = 83.16 + 0.50 - 0.06 - 0.4 = 83.20`.

---

## Step 7: Full System Verification, Linting, Formatting, and Hygiene Checks

- **Sub‑intent recommendation:** NO
- **Reasoning:** Comprehensive end-to-end verification across test suites, code linters, and documentation formatters.
- **Step Type:** VERIFY
- **Exploration level:** EXPLOIT

### Intent & Git Integration

- **Step Intent:** Execute `task test`, `task lint`, and `prettier` across the entire workspace to ensure zero
  regressions.
- **Git branch:**
  `I-1791537698-coherence-security-and-network-hardening/P-1791537711-antigravity-agent-gemini-3.8-flash-medium/E-system-verification/_`
- **Sub‑intent:** NONE

### Implementation Details (No code blocks, only logic/steps)

- Execute pytest suite: `uv run task test` (or `uv run pytest`). Validate 100% pass rate across all unit and integration
  tests (282+ passing).
- Execute code linting: `uv run ruff check .` and fix any formatting/import ordering issues via
  `uv run ruff check --fix .`.
- Execute code formatting: `uv run ruff format .` and verify compliance with `uv run ruff format --check .`.
- Execute Markdown formatting validation: `npx prettier --check "**/*.md"` to guarantee documentation formatting
  standards.
- Run `git status` to verify no untracked artifacts, temporary scratch files, or unwanted modifications exist.

### Dependencies & Criticality

- **Depends on:** Steps 1 through 6
- **Is Bottleneck:** NO

### Safety & Constraint Considerations

- **Relevant rules:** `holon-config/world/ruleset.md` §2 & §3, `holon-config/world/constraints.md` §3 (Ledger
  immutability).
- **Potential failure modes for this step:** Ruff formatting differences or Prettier markdown issues.
- **Guardrails and early‑abort checks:** Fix formatting issues immediately with `ruff format .` and
  `npx prettier --write` before finalizing.

### Success & Discard Criteria

- **Success:** All test suites pass cleanly, Ruff reports zero errors/warnings, Prettier checks pass, and git working
  tree is clean.
- **Discard:** Discard if any test regresses or lint checks fail.

### Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.99  |
| entropy_pred        | 0.1   |
| impact_pred         | 88.0  |
| cost_pred           | 0.5   |
| learning_value_pred | 1.0   |
| ev_pred             | 87.09 |

### Step Metrics Rationale

- High `p_success_pred` (0.99) and lowest entropy (0.1) as this is a verification and validation step.
- Derivation: `EV = 0.99 * 88.0 + 0.5 * 1.0 - 0.3 * 0.1 - 0.5 = 87.12 + 0.50 - 0.03 - 0.5 = 87.09`.
