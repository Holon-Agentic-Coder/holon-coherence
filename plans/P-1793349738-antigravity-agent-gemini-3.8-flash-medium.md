# Plan for I-1793349723-coherence-split-mitm-addon-into-proxy-package

- **Plan ID:** P-1793349738-antigravity-agent-gemini-3.8-flash-medium
- **Parent Intent ID:** NONE
- **Agent:** antigravity-agent (version: 1.4.10)
- **Created At:** 2026-10-30T08:42:18.762Z

---

## Overall Plan Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.96  |
| entropy_pred        | 3.30  |
| impact_pred         | 8.50  |
| cost_pred           | 0.85  |
| learning_value_pred | 2.00  |
| ev_pred             | 7.32  |

---

## Step 1: Foundation Package Layout & Utility Extractions (`scrubbing.py`, `wire_log.py`, `timing.py`)

### Step Intent & Git Integration

- **Sub-intent recommendation:** none (monolithic execution within intent scope)
- **Reasoning:** Initialize the `src/holon_coherence/proxy/` package structure and extract leaf utility modules (`scrubbing.py`, `wire_log.py`, and `timing.py`) that have zero dependencies on the proxy interceptor or addon lifecycle, establishing a clean foundation for subsequent migrations.
- **Step type:** implementation
- **Exploration level:** 0.05
- **Git branch:** `I-1793349723-coherence-split-mitm-addon-into-proxy-package`

### Implementation Details

1. **Initialize Package Structure**:
   - Create directories:
     - `src/holon_coherence/proxy/`
     - `src/holon_coherence/proxy/translation/`
     - `src/holon_coherence/proxy/normalise/`
   - Create initial `src/holon_coherence/proxy/__init__.py`, `src/holon_coherence/proxy/translation/__init__.py`, and `src/holon_coherence/proxy/normalise/__init__.py`.

2. **Extract `src/holon_coherence/proxy/scrubbing.py`**:
   - Move secret scrubbing constants and functions directly from `mitm_addon.py`:
     - Constants: `_SECRET_HEADER_NAMES`, `_URL_QUERY_SECRET_PATTERN`, `_BODY_SECRET_PATTERNS`, `_SECRET_DICT_KEY_PATTERN`.
     - Functions: `scrub_string(text: str) -> str`, `scrub_headers(headers: Any) -> dict[str, str]`, `scrub_payload(data: Any, max_depth: int = 50) -> Any`.
   - Ensure explicit `__all__` list: `["scrub_string", "scrub_headers", "scrub_payload"]`.
   - Preserve exact docstrings, type annotations, and logic without any behavioural alteration.

3. **Extract `src/holon_coherence/proxy/wire_log.py`**:
   - Move wire logging infrastructure from `mitm_addon.py`:
     - Global constants & locks: `WIRE_LOG_DIR`, `_wire_log_executor`, `_pending_wire_log_futures`, `_wire_log_lock`.
     - Functions: `is_wire_logging_enabled() -> bool`, `is_passive_monitoring() -> bool`, `is_flow_passive(flow: Any, default_passive: bool | None = None) -> bool`, `_get_wire_log_executor() -> concurrent.futures.ThreadPoolExecutor`, `_write_transaction_sync(record: dict[str, Any], wire_log_dir: str) -> None`, `dump_wire_transaction(record: dict[str, Any], wire_log_dir: str | None = None) -> concurrent.futures.Future`, `_discard_pending_future(future: concurrent.futures.Future) -> None`, `flush_wire_logs(timeout: float = 5.0) -> None`, `shutdown_wire_logs(wait: bool = True, timeout: float = 5.0) -> None`, `log_telemetry(msg: str) -> None`.
     - Register `atexit.register(shutdown_wire_logs)`.
   - Import `DEFAULT_WIRE_LOG_DIR` from `holon_coherence.metrics_math`.
   - Define `__all__` containing all exported symbols.

4. **Extract `src/holon_coherence/proxy/timing.py`**:
   - Move transaction timing primitives from `mitm_addon.py`:
     - Dataclass `FlowTiming(frozen=True)` with fields `ttft_sec`, `total_sec`, `generation_sec`, `streaming` and method `decode_reason() -> str`.
     - Helper `_wall_clock_seconds(*values: Any) -> float | None`.
     - Function `resolve_flow_timing(flow: Any, completed_at: float | None = None) -> FlowTiming`.
     - Header and turn ID extractors: `get_header_case_insensitive(headers: Any, target_header: str) -> str | None`, `derive_turn_id(headers: Any, payload: dict[str, Any] | None, fallback_id: int = 1) -> int | str`.
   - Import `positive_seconds` from `holon_coherence.metrics_math`.
   - Define `__all__` containing `["FlowTiming", "resolve_flow_timing", "get_header_case_insensitive", "derive_turn_id"]`.

### Dependencies & Criticality

- **Dependencies:** None
- **Is bottleneck:** Yes — Creates the `proxy/` package and extracts independent modules required by metrics and interceptor logic.

### Safety & Constraint Considerations

- **Relevant rules:** §2 Coding Conventions & Standards (PEP 8, docstring preservation, Ruff cleanliness), Rule 1 (Zero Synthetic / Mock Data for Benchmarking).
- **Failure modes:** Circular dependencies between `wire_log.py` and downstream modules; accidental loss of `atexit` registration for un-flushed transaction dumps.
- **Guardrails:** Keep `wire_log.py`, `scrubbing.py`, and `timing.py` free of imports from `addon.py` or `interceptor`.

### Success & Discard Criteria

- **Success:** `src/holon_coherence/proxy/` initialized, `scrubbing.py`, `wire_log.py`, and `timing.py` created with identical AST signatures to original implementations, and importable without error.
- **Discard:** Discard if circular dependencies or syntax/import errors arise.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.99  |
| entropy_pred        | 0.50  |
| impact_pred         | 7.50  |
| cost_pred           | 0.12  |
| learning_value_pred | 1.00  |
| ev_pred             | 8.23  |

### Step Metrics Rationale

- $\text{EV} = 0.99 \times 7.50 + 0.5 \times 1.00 - 0.3 \times 0.50 - 0.12 = 7.425 + 0.50 - 0.15 - 0.12 = 7.655 \approx 7.66$. Extracting pure utility and timing components with zero circular dependencies has very high probability of success and minimal risk.

---

## Step 2: Extract Metrics, Routing, and Dashboard (`metrics.py`, `routing.py`, `dashboard.py`)

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Separate stateful telemetry accumulation (`metrics.py`), network target routing heuristics (`routing.py`), and the live web dashboard HTML rendering (`dashboard.py`) into dedicated proxy modules.
- **Step type:** implementation
- **Exploration level:** 0.05
- **Git branch:** `I-1793349723-coherence-split-mitm-addon-into-proxy-package`

### Implementation Details

1. **Extract `src/holon_coherence/proxy/metrics.py`**:
   - Move `CumulativeMetrics` dataclass from `mitm_addon.py`.
   - Imports:
     - `dataclass`, `field`, `threading`, `Any` from standard library.
     - `average` from `holon_coherence.metrics_math`.
   - Methods:
     - `record_request(self) -> None`
     - `record_cleaner(self, clean_res: Any) -> None`
     - `record_cache_hit(self) -> None`
     - `record_response(self, ...) -> None` (preserving `# noqa: PLR0913` for 10 arguments)
     - `to_dict(self) -> dict[str, Any]`
   - Preserve thread-locking behaviour (`_lock: threading.Lock = field(default_factory=threading.Lock)`).
   - Define `__all__ = ["CumulativeMetrics"]`.

2. **Extract `src/holon_coherence/proxy/routing.py`**:
   - Move network destination routing checks and mock HTTP response creation:
     - `_make_http_response(flow: Any, status_code: int, content: bytes, headers: dict[str, str]) -> Any`
     - `is_local_target(flow: Any) -> bool`
   - Imports:
     - `urllib.parse.urlparse`, `typing.Any`.
     - Optional `mitmproxy.http` with graceful fallback (`try: from mitmproxy import http except ImportError: http = None`).
     - Host-local utilities from `holon_coherence.host_local` (`GATEWAY_HOSTNAME`, `targets_from_env`).
   - Define `__all__ = ["is_local_target", "_make_http_response"]`.

3. **Extract `src/holon_coherence/proxy/dashboard.py`**:
   - Move `render_dashboard_html() -> str` from `mitm_addon.py`.
   - Contains the self-contained HTML/CSS/JavaScript dashboard served at `/holon/` that polls `/holon/api/metrics`.
   - Preserves exact HTML text, styles, IDs, and client-side formatting logic.
   - Define `__all__ = ["render_dashboard_html"]`.

### Dependencies & Criticality

- **Dependencies:** Step 1
- **Is bottleneck:** No — Modular components consumed by `addon.py`.

### Safety & Constraint Considerations

- **Relevant rules:** §2 Coding Conventions & Standards, Rule 6 (Live Telemetry & Metrics Verification).
- **Failure modes:** Missing `http` import fallback breaking environments where `mitmproxy` is not installed during unit tests; dashboard template corruption.
- **Guardrails:** Keep graceful `try...except ImportError` for `mitmproxy.http`. Verify template string completeness via AST string comparison.

### Success & Discard Criteria

- **Success:** `metrics.py`, `routing.py`, and `dashboard.py` created with identical class/function AST structures; imports resolve cleanly.
- **Discard:** Discard if method signatures or dataclass field defaults are altered.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.98  |
| entropy_pred        | 0.50  |
| impact_pred         | 7.50  |
| cost_pred           | 0.12  |
| learning_value_pred | 1.00  |
| ev_pred             | 8.13  |

### Step Metrics Rationale

- $\text{EV} = 0.98 \times 7.50 + 0.5 \times 1.00 - 0.3 \times 0.50 - 0.12 = 7.35 + 0.50 - 0.15 - 0.12 = 7.58 \approx 7.58$. Metrics, routing, and dashboard extraction involves well-defined boundaries and zero state leakage.

---

## Step 3: Extract Protocol Adapters (`translation/gemini_openai.py`, `normalise/anthropic.py`)

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Decouple protocol translation and payload normalization logic into dedicated subpackages under `proxy/`, preserving all existing transformation rules, error-handling heuristics, and inline noqa complexity annotations.
- **Step type:** implementation
- **Exploration level:** 0.05
- **Git branch:** `I-1793349723-coherence-split-mitm-addon-into-proxy-package`

### Implementation Details

1. **Extract `src/holon_coherence/proxy/normalise/anthropic.py`**:
   - Move `normalize_anthropic_request`:
     ```python
     def normalize_anthropic_request(  # noqa: C901, PLR0912
         flow: Any,
         data: dict[str, Any],
         is_local: bool | None = None,
     ) -> tuple[dict[str, Any], bool]: ...
     ```
   - Import `is_local_target` from `holon_coherence.proxy.routing`.
   - Strips `thinking`, `output_config`, `context_management`, `cache_control` blocks, and `anthropic-beta` headers when targeting host-local inference endpoints.
   - Re-export in `src/holon_coherence/proxy/normalise/__init__.py`.

2. **Extract `src/holon_coherence/proxy/translation/gemini_openai.py`**:
   - Move Gemini $\leftrightarrow$ OpenAI bidirectional translation functions:
     - `translate_gemini_to_openai_request(gemini_req: dict[str, Any], model: str | None = None) -> dict[str, Any]` (`# noqa: C901, PLR0912, PLR0915`)
     - `translate_openai_to_gemini_response(openai_resp: dict[str, Any]) -> dict[str, Any]` (`# noqa: C901, PLR0912`)
     - `translate_openai_sse_chunk_to_gemini(chunk_str: str, stream_state: dict[str, Any] | None = None) -> str` (`# noqa: C901, PLR0912, PLR0915`)
   - Preserve all tool call mapping, ID generation (`call_<fn_name>`), SSE stream accumulation, and finish reason mappings (`STOP`, `MAX_TOKENS`).
   - Re-export in `src/holon_coherence/proxy/translation/__init__.py`.

3. **Verify Complexity Annotations**:
   - Verify that all inline `# noqa` comments (`C901`, `PLR0912`, `PLR0915`) are migrated verbatim with the functions so that `tests/test_complexity_baseline.py` ratchet count does not drift unexpectedly.

### Dependencies & Criticality

- **Dependencies:** Step 1, Step 2
- **Is bottleneck:** Yes — Required by `MITMProxyInterceptor` and `MitmproxyAddon`.

### Safety & Constraint Considerations

- **Relevant rules:** §2 Coding Conventions & Standards, Bean 0186 Complexity Limits, Rule 3 (Coding Agent Runners & Automated Proxy).
- **Failure modes:** Subtle translation regressions in SSE chunk assembly or argument parsing for tool calls; loss of `# noqa` comments causing ratchet test failure.
- **Guardrails:** Move functions without modifying AST expressions. Ensure inline `# noqa` annotations are preserved line-for-line.

### Success & Discard Criteria

- **Success:** `anthropic.py` and `gemini_openai.py` compile cleanly, export all translation/normalization utilities, and maintain exact function ASTs.
- **Discard:** Discard if any translation logic or streaming parser logic is altered.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.97  |
| entropy_pred        | 0.50  |
| impact_pred         | 8.00  |
| cost_pred           | 0.12  |
| learning_value_pred | 1.00  |
| ev_pred             | 8.09  |

### Step Metrics Rationale

- $\text{EV} = 0.97 \times 8.00 + 0.5 \times 1.00 - 0.3 \times 0.50 - 0.12 = 7.76 + 0.50 - 0.15 - 0.12 = 7.99 \approx 8.00$. Isolating complex protocol translation logic into dedicated subpackages significantly reduces cognitive overhead while keeping transformation logic 100% intact.

---

## Step 4: Extract Core Interceptor & Addon Engine (`proxy/addon.py`), Backward-Compatible Facade (`mitm_addon.py`), and AST Verification

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Migrate `MITMProxyInterceptor` and `MitmproxyAddon` into `src/holon_coherence/proxy/addon.py`, configure `src/holon_coherence/proxy/__init__.py`, turn `src/holon_coherence/mitm_addon.py` into a thin backward-compatible entry point re-exporting all public symbols and `addons = [MitmproxyAddon()]`, and execute programmatic AST parity validation.
- **Step type:** implementation
- **Exploration level:** 0.05
- **Git branch:** `I-1793349723-coherence-split-mitm-addon-into-proxy-package`

### Implementation Details

1. **Extract `src/holon_coherence/proxy/addon.py`**:
   - Move:
     - `DEFAULT_PROXY_LISTEN_PORT = 8080`
     - `_MAX_SSE_BUFFER_BYTES = 50 * 1024 * 1024`
     - `class MITMProxyInterceptor`
     - `class MitmproxyAddon`
     - `addons = [MitmproxyAddon()]`
   - Wire internal imports from sibling proxy modules:
     ```python
     from holon_coherence.proxy.dashboard import render_dashboard_html
     from holon_coherence.proxy.metrics import CumulativeMetrics
     from holon_coherence.proxy.normalise.anthropic import normalize_anthropic_request
     from holon_coherence.proxy.routing import _make_http_response, is_local_target
     from holon_coherence.proxy.scrubbing import scrub_headers, scrub_payload, scrub_string
     from holon_coherence.proxy.timing import FlowTiming, derive_turn_id, get_header_case_insensitive, resolve_flow_timing
     from holon_coherence.proxy.translation.gemini_openai import (
         translate_gemini_to_openai_request,
         translate_openai_sse_chunk_to_gemini,
         translate_openai_to_gemini_response,
     )
     from holon_coherence.proxy.wire_log import (
         WIRE_LOG_DIR,
         _get_wire_log_executor,
         _write_transaction_sync,
         dump_wire_transaction,
         flush_wire_logs,
         is_flow_passive,
         is_passive_monitoring,
         is_wire_logging_enabled,
         log_telemetry,
         shutdown_wire_logs,
     )
     ```
   - Retain imports from external modules (`hybrid_cache`, `parsers`, `payload_cleaner`, `host_local`, `metrics_math`).

2. **Configure `src/holon_coherence/proxy/__init__.py`**:
   - Re-export primary classes and functions for top-level `holon_coherence.proxy` consumption:
     `MitmproxyAddon`, `MITMProxyInterceptor`, `CumulativeMetrics`, `FlowTiming`, `resolve_flow_timing`, `scrub_string`, `scrub_headers`, `scrub_payload`, `is_local_target`, `render_dashboard_html`, etc.

3. **Refactor `src/holon_coherence/mitm_addon.py` as Backward-Compatible Facade**:
   - Re-export all items listed in `__all__`:

     ```python
     """Backward-compatible entry point re-exporting proxy components."""

     from holon_coherence.proxy.addon import (
         DEFAULT_PROXY_LISTEN_PORT,
         _MAX_SSE_BUFFER_BYTES,
         MITMProxyInterceptor,
         MitmproxyAddon,
         addons,
     )
     from holon_coherence.proxy.dashboard import render_dashboard_html
     from holon_coherence.proxy.metrics import CumulativeMetrics
     from holon_coherence.proxy.normalise.anthropic import normalize_anthropic_request
     from holon_coherence.proxy.routing import _make_http_response, is_local_target
     from holon_coherence.proxy.scrubbing import (
         _BODY_SECRET_PATTERNS,
         _SECRET_DICT_KEY_PATTERN,
         _SECRET_HEADER_NAMES,
         _URL_QUERY_SECRET_PATTERN,
         scrub_headers,
         scrub_payload,
         scrub_string,
     )
     from holon_coherence.proxy.timing import (
         FlowTiming,
         _wall_clock_seconds,
         derive_turn_id,
         get_header_case_insensitive,
         resolve_flow_timing,
     )
     from holon_coherence.proxy.translation.gemini_openai import (
         translate_gemini_to_openai_request,
         translate_openai_sse_chunk_to_gemini,
         translate_openai_to_gemini_response,
     )
     from holon_coherence.proxy.wire_log import (
         WIRE_LOG_DIR,
         _discard_pending_future,
         _get_wire_log_executor,
         _pending_wire_log_futures,
         _wire_log_executor,
         _wire_log_lock,
         _write_transaction_sync,
         dump_wire_transaction,
         flush_wire_logs,
         is_flow_passive,
         is_passive_monitoring,
         is_wire_logging_enabled,
         log_telemetry,
         shutdown_wire_logs,
     )

     # Re-export parser helpers previously exposed on mitm_addon
     from holon_coherence.parsers import (
         TokenCounts,
         estimate_chars,
         extract_detailed_token_counts,
         extract_sse_cache_read_tokens,
         extract_sse_content,
         extract_sse_token_counts,
         extract_token_counts,
         find_nested_key,
         safe_int,
     )

     __all__ = [
         "CumulativeMetrics",
         "MITMProxyInterceptor",
         "MitmproxyAddon",
         "TokenCounts",
         "estimate_chars",
         "extract_detailed_token_counts",
         "extract_sse_cache_read_tokens",
         "extract_sse_content",
         "extract_sse_token_counts",
         "extract_token_counts",
         "find_nested_key",
         "is_flow_passive",
         "is_local_target",
         "is_passive_monitoring",
         "normalize_anthropic_request",
         "render_dashboard_html",
         "safe_int",
         "translate_gemini_to_openai_request",
         "translate_openai_sse_chunk_to_gemini",
         "translate_openai_to_gemini_response",
         "addons",
     ]
     ```

   - Ensure `addons = [MitmproxyAddon()]` remains active at module root so `mitmdump -s mitm_addon.py` continues functioning seamlessly.

4. **AST Parity Verification**:
   - Execute an AST verification check comparing the AST tree of each extracted function and class against the baseline AST nodes from `mitm_addon.py`.
   - Confirm that docstrings, argument types, decorators, and statement bodies are bit-for-bit semantically identical.

### Dependencies & Criticality

- **Dependencies:** Step 1, Step 2, Step 3
- **Is bottleneck:** Yes — Core operational logic migration.

### Safety & Constraint Considerations

- **Relevant rules:** §2 Coding Conventions & Standards, Rule 3 (Proxy Process Isolation & Addon hooks), Acceptance Criteria 2 & 3.
- **Failure modes:** Broken `mitmdump -s` entry point if `addons` is omitted; broken monkeypatch targets in tests expecting functions on `holon_coherence.mitm_addon`.
- **Guardrails:** Keep `addons = [MitmproxyAddon()]` and all historical exports in `mitm_addon.py`. Use AST verification to guarantee zero logic drift.

### Success & Discard Criteria

- **Success:** `proxy/addon.py` runs cleanly, `mitm_addon.py` re-exports all 21+ original exports, AST comparison confirms exact equivalence for all moved classes and functions.
- **Discard:** Discard if AST verification fails or `MitmproxyAddon` fails to instantiate.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.95  |
| entropy_pred        | 0.70  |
| impact_pred         | 9.00  |
| cost_pred           | 0.20  |
| learning_value_pred | 1.00  |
| ev_pred             | 8.73  |

### Step Metrics Rationale

- $\text{EV} = 0.95 \times 9.00 + 0.5 \times 1.00 - 0.3 \times 0.70 - 0.20 = 8.55 + 0.50 - 0.21 - 0.20 = 8.64 \approx 8.64$. Central refactoring step converting the 2,348-line monolith into modular architecture while preserving 100% backward compatibility.

---

## Step 5: Test Modularization & Direct Module Test Coverage

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Ensure backward-compatible tests in `tests/test_mitm_addon.py` and `tests/test_mitm_addon_sse.py` remain fully functional while adding direct test coverage for the modular components in `tests/proxy/`, satisfying Acceptance Criteria 4.
- **Step type:** testing
- **Exploration level:** 0.05
- **Git branch:** `I-1793349723-coherence-split-mitm-addon-into-proxy-package`

### Implementation Details

1. **Verify Backward Compatibility of Existing Test Suites**:
   - Run existing `tests/test_mitm_addon.py` and `tests/test_mitm_addon_sse.py` directly against the re-exported facade in `holon_coherence.mitm_addon`.
   - Confirm zero regression on mock monkeypatches and SSE event reassembly.

2. **Establish Direct Test Suites under `tests/proxy/`**:
   - Create `tests/proxy/` test suite directory with `tests/proxy/__init__.py`.
   - Implement modular unit tests that import directly from the new `holon_coherence.proxy.*` modules:
     - `test_scrubbing.py`: Direct unit tests for `scrub_string`, `scrub_headers`, and `scrub_payload` imported from `holon_coherence.proxy.scrubbing`.
     - `test_wire_log.py`: Tests for thread-safe wire log submission, sync file writing, atomic replace, and flush mechanisms imported from `holon_coherence.proxy.wire_log`.
     - `test_timing.py`: Tests for `FlowTiming`, `resolve_flow_timing`, clock domain isolation, `get_header_case_insensitive`, and `derive_turn_id` from `holon_coherence.proxy.timing`.
     - `test_metrics.py`: Direct tests for `CumulativeMetrics` thread locking, throughput calculations, and dictionary exports from `holon_coherence.proxy.metrics`.
     - `test_routing.py`: Tests for `is_local_target` and mock response generation from `holon_coherence.proxy.routing`.
     - `test_dashboard.py`: Tests for `render_dashboard_html` from `holon_coherence.proxy.dashboard`.
     - `test_translation.py`: Direct tests for Gemini $\leftrightarrow$ OpenAI request, response, and SSE streaming translation from `holon_coherence.proxy.translation.gemini_openai`.
     - `test_normalise.py`: Tests for Anthropic header and cache control stripping from `holon_coherence.proxy.normalise.anthropic`.

3. **Ensure Test Count Preservation & Isolation**:
   - Verify that test isolation rules are strictly preserved (no shared mutable state across tests, temporary directories cleaned up hermetically).
   - Verify that total test count increases and no existing tests are lost or skipped.

### Dependencies & Criticality

- **Dependencies:** Step 1, Step 2, Step 3, Step 4
- **Is bottleneck:** Yes — Validates that all new modules can be imported and tested directly without requiring the monolithic addon.

### Safety & Constraint Considerations

- **Relevant rules:** §3 Testing Constraints, Rule 1 (Zero Synthetic / Mock Data for Benchmarking — strictly unit test functional logic, no synthetic benchmark scores).
- **Failure modes:** Unintended side effects from concurrent `flush_wire_logs` or test runner thread contention.
- **Guardrails:** Use unique temporary directories (`tmp_path`) for wire logging tests.

### Success & Discard Criteria

- **Success:** All new tests under `tests/proxy/` pass, and existing tests in `test_mitm_addon.py` and `test_mitm_addon_sse.py` pass with 100% green status.
- **Discard:** Discard if any existing test fails or regressions occur.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.98  |
| entropy_pred        | 0.70  |
| impact_pred         | 8.50  |
| cost_pred           | 0.15  |
| learning_value_pred | 1.00  |
| ev_pred             | 8.47  |

### Step Metrics Rationale

- $\text{EV} = 0.98 \times 8.50 + 0.5 \times 1.00 - 0.3 \times 0.70 - 0.15 = 8.33 + 0.50 - 0.21 - 0.15 = 8.47$. Direct module testing completes test suite decomposition while ensuring complete backward-compatible safety.

---

## Step 6: Comprehensive Verification, Quality Gates & Complexity Ratchet

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Execute the complete test suite under `uv run pytest`, verify Ruff linting and formatting, validate the complexity baseline ratchet in `tests/test_complexity_baseline.py`, run Prettier formatting, and prepare a clean squashed commit.
- **Step type:** verification
- **Exploration level:** 0.00
- **Git branch:** `I-1793349723-coherence-split-mitm-addon-into-proxy-package`

### Implementation Details

1. **Pytest Verification**:
   - Run the entire test suite from the worktree root:
     ```bash
     uv run pytest
     ```
   - Verify zero errors, zero failures, and total test count greater than or equal to baseline.
   - Run proxy-specific tests:
     ```bash
     uv run pytest tests/test_mitm_addon.py tests/test_mitm_addon_sse.py tests/proxy/
     ```

2. **Complexity and Hygiene Gates**:
   - Run Ruff linter and formatter:
     ```bash
     uv run ruff check .
     uv run ruff format --check .
     ```
   - Verify the complexity baseline ratchet:
     ```bash
     uv run pytest tests/test_complexity_baseline.py
     ```
   - Confirm that the total count of `# noqa` complexity suppressions matches `BASELINE_CEILING` (or ratchet down if any legacy suppression was eliminated).

3. **Markdown and Repository Hygiene**:
   - Format all markdown documentation using Prettier:
     ```bash
     npx prettier --write "**/*.md"
     ```
   - Confirm git status is completely clean with zero untracked temporary files or residue:
     ```bash
     git status
     ```

4. **Git Commit Preparation**:
   - Ensure all feature commits are squashed into a single logical commit relative to `origin/main` according to Holon git workflow rules.

### Dependencies & Criticality

- **Dependencies:** Step 1, Step 2, Step 3, Step 4, Step 5
- **Is bottleneck:** Yes — Final gate for acceptance criteria fulfillment.

### Safety & Constraint Considerations

- **Relevant rules:** §1 Runtime & Environment Specification, §2 Coding Conventions & Standards, §3 Testing Constraints, Worktree Isolation & Squash Commits.
- **Failure modes:** Uncaught Ruff formatting differences, missing docstrings, or ratchet mismatch.
- **Guardrails:** Automated test execution via `uv run pytest` and static checks with Ruff prior to completion.

### Success & Discard Criteria

- **Success:** Full `uv run pytest` suite passes with 0 failures, Ruff checks report 0 errors, Prettier passes, and git history is squashed cleanly.
- **Discard:** Discard if any test regression or lint failure exists.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.99  |
| entropy_pred        | 0.40  |
| impact_pred         | 9.00  |
| cost_pred           | 0.09  |
| learning_value_pred | 1.00  |
| ev_pred             | 9.19  |

### Step Metrics Rationale

- $\text{EV} = 0.99 \times 9.00 + 0.5 \times 1.00 - 0.3 \times 0.40 - 0.09 = 8.91 + 0.50 - 0.12 - 0.09 = 9.20 \approx 9.19$. Final validation gate provides comprehensive verification against all acceptance criteria and quality constraints.

---

## Strategy Rationale

The overall plan metrics are computed using the physics-driven Expected Value (EV) formula:

$$\text{EV} = P(\text{success}) \times \text{Impact} + \mu \times \text{LearningValue} - \lambda \times \Delta S_{\text{intent}} - \text{Cost}$$

Using baseline calibration constants $\lambda = 0.3$ and $\mu = 0.5$:

$$\text{EV} = (0.96 \times 8.50) + (0.5 \times 2.00) - (0.3 \times 3.30) - 0.85 = 8.16 + 1.00 - 0.99 - 0.85 = 7.32$$

- **$P(\text{success})$ (0.96):** The refactoring strategy relies on pure move-only semantics verified by programmatic AST node comparisons. Preserving the public interface in `mitm_addon.py` as a facade eliminates regression risks for existing callers and CLI runners.
- **$\text{Impact}$ (8.50):** Deconstructs a 2,348-line monolithic script with 9 mixed concerns into 9 cohesive modules within a structured `src/holon_coherence/proxy/` package, establishing clean isolation between network routing, wire logging, metrics accumulation, protocol translation, and HTML dashboard rendering.
- **$\mu \times \text{LearningValue}$ ($0.5 \times 2.00 = 1.00$):** Codifies clean subpackage modularization patterns for proxy interceptors, establishes direct unit testing suites, and demonstrates AST-verified safe code migration.
- **$\lambda \times \Delta S\_{\text{intent}}$ ($0.3 \times 3.30 = 0.99$):** Bounded entropy distribution across the 6 execution steps totaling 3.30, safely below the 5.0 entropy budget.
- **$\text{Cost}$ (0.85):** Direct refactoring cost covering AST verification script creation, package wiring, test suite modularization, and multi-gate pytest/ruff execution.

---

## Planner Autonomy Summary

- **Intent handling:** `ACCEPT_AS_IS`
- **Reframed intent (if applicable):** NONE
- **Exploration stance:** Exploitation-dominant (0.05 exploration). The boundaries of the modules (`scrubbing.py`, `wire_log.py`, `timing.py`, `metrics.py`, `routing.py`, `translation/gemini_openai.py`, `normalise/anthropic.py`, `dashboard.py`, `addon.py`) are clearly defined in the intent specification. The task requires strict AST equivalence and zero semantic deviation.
- **Safety priority level:** `standard`
- **Priority Justification:** All refactoring operations are purely structural and modular. No protocol behavior, network interception logic, or CA certificate handling is changed. All public symbols remain accessible via `mitm_addon.py` for backward compatibility.

---

## Exploration

- **Proportion of steps that are exploratory:** 0.05
- **Justification:** The code locations, class signatures, and function dependencies within `src/holon_coherence/mitm_addon.py` are already well understood. Minimal exploration (0.05) is reserved for verifying internal helper imports across subpackages and confirming exact AST node equivalence.

---

## Safety & Constraint Alignment

- **Key world ruleset constraints that affect this plan:**
  - `holon-config/world/ruleset.md`: Runtime compatibility with Python 3.13, execution of tests strictly via `uv run pytest`, Ruff lint and format cleanliness, docstring and comment preservation.
  - Bean 0186 Complexity Limits: Enforce McCabe $C901 \le 10$, $PLR0911 \le 6$, $PLR0912 \le 12$, $PLR0913 \le 5$, $PLR0915 \le 50$. Verify `tests/test_complexity_baseline.py` ratchet ceiling.
  - Testing constraints: Zero test failures under `uv run pytest`, full preservation of existing test cases, and hermetic test isolation.
  - Git workflow constraints: Worktree isolation, single squashed commit relative to `main`, no autonomous remote push.
- **Potential violations or edge cases:**
  - Import cycles: Circular imports between `addon.py` and downstream modules if `addon.py` exports are imported at module level by helper modules.
  - Missing entry point for mitmproxy: Failure to expose `addons = [MitmproxyAddon()]` in `mitm_addon.py` breaking `-s mitm_addon.py` invocations.
  - Broken test mock targets: Tests patching `holon_coherence.mitm_addon.<symbol>` breaking if the facade does not re-export internal helpers.
  - Ratchet ceiling drift: Inadvertent removal or addition of `# noqa` complexity suppressions failing `test_complexity_baseline_ratchet_ceiling`.
- **Mitigations built into the plan:**
  - Strict leaf module hierarchy: `scrubbing.py`, `wire_log.py`, `timing.py`, `metrics.py`, and `routing.py` have zero imports from `addon.py`.
  - Comprehensive facade re-exports: `mitm_addon.py` re-exports all 21 public symbols in `__all__`, plus internal helpers patched by tests (`_wire_log_executor`, `_write_transaction_sync`, `_MAX_SSE_BUFFER_BYTES`, `derive_turn_id`, etc.), and retains `addons = [MitmproxyAddon()]`.
  - Programmatic AST verification: Exact node comparison confirms zero syntactic or behavioural modification during the move.
  - Ratchet verification in Step 6: Explicitly validates `BASELINE_CEILING` in `tests/test_complexity_baseline.py`.
- **Allocated Entropy Budget:** 5.0
- **Predicted Plan Entropy:** 3.30 (sum of step entropies: $0.50 + 0.50 + 0.50 + 0.70 + 0.70 + 0.40 = 3.30$)
- **Budget Compliance:** Full compliance ($3.30 \le 5.00$).

---

## Plan Description & Strategy

1. **Step 1: Foundation Package Layout & Utility Extractions (`scrubbing.py`, `wire_log.py`, `timing.py`)**:
   Create `src/holon_coherence/proxy/` package structure and extract zero-dependency utility modules: secret scrubbing (`scrubbing.py`), atomic background wire logging (`wire_log.py`), and flow timing calculations (`timing.py`).
2. **Step 2: Extract Metrics, Routing, and Dashboard (`metrics.py`, `routing.py`, `dashboard.py`)**:
   Extract `CumulativeMetrics` with thread locking into `metrics.py`, host-local routing checks and HTTP response factory into `routing.py`, and the self-contained live telemetry dashboard HTML into `dashboard.py`.
3. **Step 3: Extract Protocol Adapters (`translation/gemini_openai.py`, `normalise/anthropic.py`)**:
   Migrate Gemini $\leftrightarrow$ OpenAI bidirectional request, response, and SSE streaming translation into `proxy/translation/gemini_openai.py` and Anthropic header/cache stripping into `proxy/normalise/anthropic.py`, preserving all `# noqa` complexity annotations.
4. **Step 4: Extract Core Interceptor & Addon Engine (`proxy/addon.py`), Backward-Compatible Facade (`mitm_addon.py`), and AST Verification**:
   Migrate `MITMProxyInterceptor` and `MitmproxyAddon` into `proxy/addon.py`. Turn `mitm_addon.py` into a thin backward-compatible entry point re-exporting all symbols and `addons = [MitmproxyAddon()]`. Execute programmatic AST verification to confirm zero logic drift.
5. **Step 5: Test Modularization & Direct Module Test Coverage**:
   Verify existing suites (`tests/test_mitm_addon.py`, `tests/test_mitm_addon_sse.py`) pass cleanly through the facade. Create dedicated direct unit test suites under `tests/proxy/` testing the new modules directly.
6. **Step 6: Comprehensive Verification, Quality Gates & Complexity Ratchet**:
   Execute full test suite with `uv run pytest`, verify Ruff checks and formatting, validate the complexity baseline ratchet in `test_complexity_baseline.py`, run Prettier markdown formatting, and prepare squashed git commit.
