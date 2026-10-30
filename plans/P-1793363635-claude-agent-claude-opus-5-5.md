# Plan for I-1793355582-coherence-decompose-addon-hooks

- **Plan ID:** P-1793363635-claude-agent-claude-opus-5-5
- **Parent Intent ID:** NONE
- **Agent:** claude-agent (version: 2.1.302)
- **Created At:** 2026-10-30T12:33:55.647Z

## Overall Plan Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.82  |
| entropy_pred        | 1.65  |
| impact_pred         | 6.0   |
| cost_pred           | 0.40  |
| learning_value_pred | 1.0   |
| ev_pred             | 4.53  |

## Planner Autonomy Summary

- **Intent handling:** `REFRAME`
- **Reframed intent (if applicable):** Decompose `MitmproxyAddon.request`, `MitmproxyAddon.response` and
  `_dump_flow_transaction` (plus the small `responseheaders` SSE tap) in `src/holon_coherence/proxy/addon.py` into an
  ordered pipeline of single-responsibility step functions in `src/holon_coherence/proxy/steps/`. The five named steps
  (`serve_dashboard`, `route_local_target`, `apply_cache`, `clean_payload`, `record_metrics`) are kept as the backbone,
  with a few extra steps that the current code needs (`identify_provider`, `adapt_local_protocol`, `load_exchange`,
  `wire_record`). The passive-monitoring gate and the per-pipeline error policy live once, in the pipeline runner. The
  `BASELINE_CEILING` constant in `tests/test_complexity_baseline.py` is also lowered (one line outside the declared
  scope). The ratchet test asserts exact equality, so removing the `noqa` suppressions without changing that constant
  would fail the suite (acceptance criterion 5).
- **Exploration stance:** mostly exploitation. The target code is fully readable and the order of side effects can be
  derived line by line. The one exploratory part is a characterization (parity) test suite. It is written _before_ the
  refactor against the current code, so "100% wire-level preservation" becomes something we can check rather than
  something we assume.
- **Safety priority level:** elevated
- **Priority Justification:** `addon.py` sits on the live wire path for every agent run through the proxy. A silent
  change to the order of side effects (counter increments, `set_text` calls, header injection, wire-log records, SSE
  chunk handling) would corrupt the A/B telemetry and the `transactions.jsonl` evidence that Rule 1 depends on. Nothing
  here is destructive or outward-facing, so `strict` is not justified.

## Exploration

- **Proportion of steps that are exploratory:** 0.13
- **Justification:** One step in eight (Step 1, the characterization suite) is exploratory. It finds the quirks the
  refactor must preserve: mode endpoint fall-through for methods other than GET/POST, exceptions from the Gemini bridge
  propagating while the clean/cache stage logs and swallows them, two different error policies for 200 and non-200
  responses, and late-bound test seams in `holon_coherence.mitm_addon`. Everything else is mechanical extraction once
  those are pinned.

## Plan Description & Strategy

Observed facts that drive the design (from `src/holon_coherence/proxy/addon.py` on `main`):

- `request` (lines 509–717, `# noqa: C901, PLR0912, PLR0915`), `response` (767–953, same suppressions),
  `_dump_flow_transaction` (399–507, `# noqa: PLR0913`), `responseheaders` (719–765, `# noqa: C901`).
- `tests/test_complexity_baseline.py` counts complexity-`noqa` _lines_ under `src/` and asserts
  `count == BASELINE_CEILING` (currently 42). Removing the four addon suppressions gives **38**.
- Tests monkeypatch `holon_coherence.mitm_addon.{in_container, resolve_gateway_address, log_telemetry, ctx,
is_local_target, WIRE_LOG_DIR}`. The `_get_*()` late-binding shims must therefore still be called _at call time_ from
  inside every step.
- Tests call `addon._dump_flow_transaction(flow, resp_data=..., status_code=..., is_hit=..., ttft=..., total_time=...)`
  directly, so the method name and its keyword interface must survive.
- Error semantics differ by segment. Dashboard serving, own-port rewrite, provider detection and local protocol
  adaptation run **unguarded**: an exception propagates to mitmproxy. Snapshot, clean and cache run inside a single
  `try` that sends `JSONDecodeError` to `logger.debug` and anything else to `logger.exception`. For responses, the 200
  path uses `logger.debug`/`logger.exception`. The non-200 path logs a warning and a telemetry line first, then records
  inside a `try` that only calls `logger.debug`.

High-level sequence:

1. Create the worktree and record a baseline: test suite, ruff, the complexity report, and a characterization suite
   that pins current wire behaviour.
2. Scaffold `proxy/steps/`: context dataclasses, `StepSpec`, the pipeline runner with its passive gate and error
   policies, and the compat shims.
3. Extract the request prelude steps: `serve_dashboard`, `route_local_target`, `parse_request_body`,
   `identify_provider`, `adapt_local_protocol`.
4. Extract the guarded request steps (`snapshot_request`, passive passthrough, `clean_payload`, `apply_cache`), and
   turn `request` into a slim dispatcher.
5. Extract the response pipeline (`load_exchange`, `apply_cache.store_response`, `record_metrics.*`) and the
   `wire_record` builder, and turn `response` and `_dump_flow_transaction` into slim dispatchers.
6. Move the `responseheaders` SSE tap into `steps/sse_tap.py`, keeping the wrapper body the same.
7. Add per-step unit tests and pipeline-order tests, and lower the ratchet ceiling 42 → 38.
8. Run the full verification gates (pytest, ruff, prettier), compare against the baseline, and squash to one commit.

## Step 1: Worktree, baseline and characterization (parity) suite

### Step Intent & Git Integration

- **Sub-intent recommendation:** none (inline)
- **Reasoning:** Wire-level parity is the main acceptance risk. Pinning it before any code moves turns the whole
  refactor into "keep this suite green".
- **Step type:** exploration / verification scaffolding
- **Exploration level:** high
- **Git branch:** execution branch per §1 constraints, e.g.
  `I-1793355582-coherence-decompose-addon-hooks/P-1793363635-claude-agent-claude-opus-5-5/E-<ts>-claude-agent-claude-opus-5-5/_`,
  in a dedicated worktree created with
  `git worktree add --no-track -b <branch> ../<dir> origin/main` (never on the `main` worktree).

### Implementation Details

1. Run `git fetch origin main` and create the worktree. Run `uv sync` from the worktree root so `.venv` is local to
   it.
2. Baseline: `uv run pytest -q` (record pass/skip counts), `uv run ruff check .`, and
   `uv run ruff check --select C901,PLR0911,PLR0912,PLR0913,PLR0915 --config lint.mccabe.max-complexity=0 src/holon_coherence/proxy/addon.py --output-format concise`
   (or `radon cc` through `uvx`) to record per-function complexity. Save these numbers for the execution report.
3. Add `tests/proxy/test_addon_pipeline_parity.py`. It drives a real `MitmproxyAddon` (with `tmp_path` cache and wire
   log dirs, and `HOLON_WIRE_LOG=1` or whatever `is_wire_logging_enabled` reads, set through `monkeypatch.setenv`)
   using the existing `MockFlow` / `MockRequest` / `MockResponse` shapes from `tests/test_mitm_addon_sse.py`. Move them
   into a `tests/proxy/conftest.py` fixture module only if that can be done without editing the existing test file;
   otherwise duplicate them minimally. Each scenario asserts the observable outcome: `flow.response` status, body and
   headers (timing header _values_ are excluded; their presence and formatting class are asserted); flow attributes
   (`provider`, `req_data`, `raw_request_data`, `cleaner_result`, `is_cached`, `is_gemini_bridged`, request
   host/port/scheme/path/text); `addon.total_requests` / `cache_hits`; `addon.metrics.to_dict()` counters; the parsed
   wire-log record with `timestamp` and `timing.*_ms` values masked; and `log_telemetry` calls captured through
   `monkeypatch.setattr("holon_coherence.mitm_addon.log_telemetry", ...)`, with numeric timing masked by regex.
   Scenarios:
   - `GET /holon/api/metrics`, `GET /_holon/metrics`, `POST /holon/api/metrics` (falls through to proxy logic).
   - `POST /holon/api/mode` with baseline / optimized / `wire_log_dir` / invalid JSON (400).
     `GET /holon/api/mode`. `PUT /holon/api/mode` (falls through).
   - `GET /holon` and `GET /holon/` (dashboard HTML).
   - Own-port reverse rewrite with and without `HOLON_HOST_LOCAL_HOSTS` targets, in and out of the container.
   - Unknown provider (no counters touched), and non-JSON body for a known provider.
   - Gemini → OpenAI bridge for a local target (`:streamGenerateContent` sets `stream`, model taken from env and from
     the path), and Anthropic local normalisation.
   - Passive flow (header and `default_passive`): no cleaning, `req_data is data`, `cleaner_result is None`, and no
     cache store on response.
   - Active miss followed by an identical active request, which gives a cache HIT with zeroed `X-Holon-*` headers and a
     `cache_action: HIT` wire record.
   - `intercept_request_with_stats` raising (logged and swallowed, counters already incremented).
   - SSE response through `responseheaders` + chunk wrapper + `response` (no cache store, `streaming: true`), and a
     bridged Gemini SSE.
   - Non-200 response (warning, telemetry line, wire record with `total_ms`, zeroed `record_response`).
   - `response` with `flow.response.get_text` raising.
4. Run the new suite against **unmodified** `addon.py`; it must pass. If a scenario shows behaviour that looks like a
   bug, pin it as it is anyway and note it in the execution report. Do not fix it here; this intent is preservation
   only.

### Dependencies & Criticality

- **Dependencies:** none.
- **Is bottleneck:** yes. Every later step is judged against this suite.

### Safety & Constraint Considerations

- **Relevant rules:** §1 worktree isolation; Rule 1. These fixtures are functional regression inputs only. No
  token-reduction efficacy, scorecard or benchmark number is derived from them, which is the use Rule 1 restricts.
  State this in a module docstring. Rule 2: no persistent `export`; env goes through `monkeypatch`.
- **Failure modes:** flaky timing-sensitive assertions; global wire-log executor state leaking between tests.
- **Guardrails:** mask all timing values. Call `flush_wire_logs()` before reading `transactions.jsonl`, as the existing
  tests do. Isolate the env with `monkeypatch`.

### Success & Discard Criteria

- **Success:** the parity suite passes on unmodified code three runs in a row (`uv run pytest tests/proxy -p no:randomly`
  if that plugin is present).
- **Discard:** if a scenario cannot be made deterministic, drop that scenario (not the suite) and rely on the existing
  `tests/test_mitm_addon*.py` coverage for it.

### Step Metrics

| metric    | value |
| :-------- | :---- |
| p_success | 0.92  |
| entropy   | 0.15  |
| impact    | 0.30  |
| cost      | 0.08  |
| learning  | 0.60  |

**Step Metrics Rationale:** this is test-only code against a known API. It has the highest learning value because it
finds the hidden branches before they can be broken.

## Step 2: Scaffold `proxy/steps/` — contexts, `StepSpec`, runner, compat shims

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** One small runner gives the "passive short-circuit and error handling expressed once" criterion a
  single home.
- **Step type:** implementation
- **Exploration level:** low
- **Git branch:** same execution branch

### Implementation Details

Create these files:

- `src/holon_coherence/proxy/steps/_compat.py`: move the `_get_in_container`, `_get_resolve_gateway_address`,
  `_get_log_telemetry`, `_get_ctx` and `_get_is_local_target` shims here unchanged. They still resolve through
  `sys.modules["holon_coherence.mitm_addon"]` first. Add `resolve_response_cls(flow)`, which reproduces
  `getattr(http, "Response", None) or getattr(flow, "Response", None) or <addon module globals>.get("Response")`.
  `http` is imported with the same `try/except ImportError` guard. `addon.py` re-imports the `_get_*` names, so its
  `server_connect` and `_proxy_own_ports` are untouched and any external import keeps working.
- `src/holon_coherence/proxy/steps/base.py`:
  - `class Outcome(Enum): CONTINUE, HALT`.
  - `@dataclass class RequestContext`: `addon`, `flow`, `url`, `path_clean`, `method`, `data=None`,
    `provider="unknown"`, `is_local=False`, `cached_resp=None`, `clean_res=None`. Add a lazily evaluated `passive`
    property that calls `is_flow_passive(flow, default_passive=getattr(addon, "default_passive", None))` once, on first
    access. This keeps the current evaluation point: only after a parsed body exists, inside the guarded segment.
  - `@dataclass class ResponseContext`: `addon`, `flow`, `url`, `status_code`, `provider`, `req_data=None`,
    `resp_data=None`, `is_sse=False`, `telemetry: Telemetry | None = None`, plus the same lazy `passive`.
  - `@dataclass(frozen=True) class StepSpec`: `name: str`, `fn: Callable[[Ctx], Outcome]`,
    `mode: Literal["always", "active", "passive"] = "always"`.
  - `@dataclass(frozen=True) class ErrorPolicy`: `json_message: str | None`, `exception_message: str | None`,
    `exception_level: Literal["exception", "debug"]`.
  - `run_steps(steps, ctx) -> Outcome`: loops in order. For `mode != "always"` it skips the step when
    `ctx.passive != (mode == "passive")`. It stops on `HALT`. This passive gate is the only place passive-mode
    branching happens.
  - `run_guarded(steps, ctx, policy) -> None`: `try: run_steps(...)`. On `json.JSONDecodeError`, if
    `policy.json_message` is set, it logs `logger.debug(policy.json_message, ctx.url, exc)`. On `Exception` it logs at
    the policy's level. It uses the **same logger name** as today (`logging.getLogger("holon_coherence.proxy.addon")`
    or whatever `addon.py`'s `logger` resolves to; check with `grep -n "logger =" addon.py`), so log-capturing tests
    and operators see identical records.
- `src/holon_coherence/proxy/steps/__init__.py`: exports `REQUEST_PRELUDE`, `REQUEST_GUARDED`, `RESPONSE_SUCCESS`,
  `RESPONSE_FAILURE`, the policies, `run_steps` and `run_guarded`. Pipelines are module-level tuples, so the order is
  data that can be inspected and tested.

Hatchling ships `src/holon_coherence` as a whole, so the new subpackage needs no `pyproject.toml` change. Confirm by
running `uv build` (or by importing the package from the installed `.venv`) in Step 8.

### Dependencies & Criticality

- **Dependencies:** Step 1.
- **Is bottleneck:** yes (Steps 3–6 import it).

### Safety & Constraint Considerations

- **Failure modes:** an import cycle (`steps` → `addon` → `steps`); a different logger name changes log routing.
- **Guardrails:** `steps/*` must never import `proxy.addon` at module level. Only `_compat` touches it, lazily through
  `sys.modules`. Steps receive the addon instance through the context.

### Success & Discard Criteria

- **Success:** `python -c "import holon_coherence.mitm_addon"` works. The full suite is still green, since nothing is
  wired yet. `ruff check` is clean.
- **Discard:** if `Enum`/dataclass contexts cause measurable per-flow overhead (>5 µs median per hook in a quick
  `timeit` against the Step 1 flows), switch to plain functions with `__slots__` classes. The structure stays the same.

### Step Metrics

| metric    | value |
| :-------- | :---- |
| p_success | 0.95  |
| entropy   | 0.20  |
| impact    | 0.40  |
| cost      | 0.05  |
| learning  | 0.10  |

**Step Metrics Rationale:** new code with no behaviour yet. The risk is limited to import topology.

## Step 3: Request prelude steps (unguarded)

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Separates control-plane endpoints and routing from payload work.
- **Step type:** implementation (refactor)
- **Exploration level:** low
- **Git branch:** same

### Implementation Details

- `steps/serve_dashboard.py`:
  - `serve_metrics(ctx)`: `GET` and path in `("/holon/api/metrics", "/_holon/metrics")`.
  - `serve_mode(ctx)`: path in `("/holon/api/mode", "/_holon/mode")`. Dispatches `POST` to `_mode_post` (with its own
    `try/except Exception → 400`) and `GET` to `_mode_get`. Any other method returns `CONTINUE`. This preserves the
    fall-through.
  - `serve_html(ctx)`: `GET /holon`.
  - `serve_dashboard(ctx)` runs those three in that order and returns `HALT` on the first that sets `flow.response`.
    Response bytes, headers (including `Access-Control-Allow-Origin` only on metrics) and JSON `indent` stay byte-for-byte
    the same.
- `steps/route_local_target.py`:
  - `route_local_target(ctx)`: the own-port reverse rewrite (host set in `("127.0.0.1", "localhost",
"127.0.0.1.nip.io", "localhost.nip.io")` and `port in ctx.addon._proxy_own_ports()`). It recomputes `ctx.url` from
    `pretty_url` after the rewrite.
  - `adapt_local_protocol(ctx)`: the Gemini bridge (split out `_bridge_target_model(flow, url)`) followed by the
    Anthropic local normaliser. The conditions `provider == ... and is_local and data is not None` and the
    `set_text(json.dumps(data))` calls are unchanged, and `ctx.data` is updated.
- `steps/identify_provider.py`:
  - `parse_request_body(ctx)`: the existing `try/except Exception → logger.debug("Non-JSON or unparseable request body …")`.
  - `identify_provider(ctx)`: `detect_provider`. If the result is `"unknown"` it returns `HALT`. Otherwise it sets
    `flow.provider`, sets `flow.request_start_time = time.perf_counter()`, increments `total_requests`, calls
    `metrics.record_request()`, and sets `ctx.is_local = _get_is_local_target()(flow)`.
- `REQUEST_PRELUDE = (serve_dashboard, route_local_target, parse_request_body, identify_provider, adapt_local_protocol)`.
  All steps use `mode="always"`, and the prelude runs through `run_steps` (unguarded). This matches today, where these
  lines sit outside the `try`.

### Dependencies & Criticality

- **Dependencies:** Step 2.
- **Is bottleneck:** no.

### Safety & Constraint Considerations

- **Failure modes:** the `url` used for provider detection is computed before the rewrite instead of after; `raw_path`
  is derived differently; an exception in the bridge is accidentally swallowed.
- **Guardrails:** `RequestContext` is built in `request()` with the same `url` / `raw_path` / `path_clean` / `method`
  expressions, moved verbatim. Parity scenarios for the own-port rewrite and the Gemini bridge, plus an explicit
  `pytest.raises` parity test that a bridge exception still propagates.

### Success & Discard Criteria

- **Success:** parity suite and `tests/test_mitm_addon*.py` green with the prelude wired in (temporary hybrid
  `request`).
- **Discard:** none expected. If the hybrid wiring breaks parity, revert this step's diff and re-extract one function at
  a time.

### Step Metrics

| metric    | value |
| :-------- | :---- |
| p_success | 0.90  |
| entropy   | 0.30  |
| impact    | 0.70  |
| cost      | 0.07  |
| learning  | 0.10  |

**Step Metrics Rationale:** mechanical moves with several branches. The quirks found in Step 1 bound the risk.

## Step 4: Guarded request steps, passive short-circuit, slim `request`

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** This is the payload core: cleaning and caching, with the passive bypass handled by the runner gate.
- **Step type:** implementation (refactor)
- **Exploration level:** low
- **Git branch:** same

### Implementation Details

- `steps/clean_payload.py`:
  - `snapshot_request(ctx)`: `HALT` if `ctx.data is None`; otherwise `flow.raw_request_data = copy.deepcopy(ctx.data)`.
  - `passthrough_payload(ctx)` (`mode="passive"`): `flow.cleaner_result = None`, `flow.req_data = ctx.data`, then
    `HALT`.
  - `clean_payload(ctx)` (`mode="active"`): the `intercept_request_with_stats` / `intercept_request` `hasattr` fallback
    (as `_intercept(interceptor, url, data)`), the local fixup (`cache_control_injected = 0` + re-normalise), the flow
    assignments, `set_text`, `metrics.record_cleaner` and `_log_cleaner(clean_res)` (only when one of the four counters
    is > 0). Stores `ctx.cached_resp` and `ctx.clean_res`.
- `steps/apply_cache.py`:
  - `serve_cached(ctx)` (`mode="active"`): `CONTINUE` if there is no `ctx.cached_resp`. Otherwise it increments
    counters, sets `flow.is_cached = True`, builds the response with `resolve_response_cls(flow).make(...)` when
    available, and calls `_inject_hit_headers(flow, hit_rate)` (the same seven headers and values, and the same
    four-part `hasattr` guard, factored as `steps/_headers.py::writable_headers(flow) -> headers | None`). It then logs
    the HIT telemetry line and calls `ctx.addon._dump_flow_transaction(flow, resp_data=cached_resp, status_code=200,
is_hit=True)`.
- `REQUEST_GUARDED = (snapshot_request, passthrough_payload[passive], clean_payload[active], serve_cached[active])`.
- `REQUEST_POLICY = ErrorPolicy(json_message="Non-JSON request body for endpoint %s: %s",
exception_message="Mitmproxy request intercept error for endpoint: %s", exception_level="exception")`.
- `MitmproxyAddon.request` becomes about 10 lines:
  ```python
  def request(self, flow: Any) -> None:
      """Mitmproxy request callback: run the ordered request pipeline."""
      if getattr(flow, "request", None) is None:
          return
      ctx = RequestContext.from_flow(self, flow)
      if run_steps(REQUEST_PRELUDE, ctx) is Outcome.HALT:
          return
      run_guarded(REQUEST_GUARDED, ctx, REQUEST_POLICY)
  ```
  Remove `# noqa: C901, PLR0912, PLR0915` from it.

### Dependencies & Criticality

- **Dependencies:** Steps 2–3.
- **Is bottleneck:** yes (this is where the request-side acceptance criterion is met).

### Safety & Constraint Considerations

- **Failure modes:** `passive` evaluated before `data is None` is checked (an extra call, and a different exception
  domain); `set_text` order changed relative to `record_cleaner`; `hit_rate` computed before `cache_hits += 1`; the
  telemetry dump on HIT runs outside the guarded segment.
- **Guardrails:** the lazy `passive` property and the step order above match the source exactly. Parity HIT scenario
  asserts the `X-Holon-Cache-Hit-Rate` value. Parity test for the "interceptor raises" case asserts
  `logger.exception` through `caplog` and that `total_requests` is incremented.

### Success & Discard Criteria

- **Success:** all request-side parity and existing tests green. `ruff check` reports no complexity violations in
  `addon.py::request` or any `steps/*` function.
- **Discard:** if an exact-parity behaviour cannot be met by the gate design, express that case as an explicit step
  rather than adding a special case to the runner.

### Step Metrics

| metric    | value |
| :-------- | :---- |
| p_success | 0.88  |
| entropy   | 0.30  |
| impact    | 0.80  |
| cost      | 0.07  |
| learning  | 0.10  |

**Step Metrics Rationale:** this is the densest side-effect sequence on the request side, and parity tests cover it
directly.

## Step 5: Response pipeline, `wire_record` builder, slim `response` and `_dump_flow_transaction`

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** This is the second hook and the 109-line wire-record builder (CC 28).
- **Step type:** implementation (refactor)
- **Exploration level:** low
- **Git branch:** same

### Implementation Details

- `steps/load_exchange.py`:
  - `load_request(ctx)`: `flow.req_data`, or parse `get_text()`. A `JSONDecodeError` propagates to the policy, as
    today.
  - `load_response(ctx)`: SSE join, or JSON plus the bridged Gemini translation with its own inner
    `try/except → logger.debug`.
  - `require_payloads(ctx)`: `HALT` unless `req_data is not None and resp_data`.
- `steps/apply_cache.py::store_response(ctx)` (`mode="active"`): if not `ctx.is_sse`, call
  `interceptor.intercept_response(url, req_data, resp_data, status_code=...)`. The existing comment about SSE bypass
  moves with it.
- `steps/record_metrics.py`:
  - `@dataclass(frozen=True) class Telemetry`: token fields, `ttft`, `total_time`, `generation_time`, `prefill_tps`,
    `tail_prefill_tps`, `output_tps`, `hit_rate` and `timing`.
  - `compute_telemetry(ctx)`: `extract_token_counts`, then `resolve_flow_timing(flow, completed_at=time.perf_counter())`
    and the three `compute_*` calls. The clock-domain comment is kept.
  - `inject_miss_headers(ctx)`: the eight `X-Holon-*` headers through `writable_headers`.
  - `log_miss_telemetry(ctx)`: the label builders split into `_ttft_label`, `_total_label`, `_output_label`; the
    message string is unchanged.
  - `dump_miss_transaction(ctx)`: calls `addon._dump_flow_transaction(...)` with the same kwargs.
  - `record_response_metrics(ctx)`: calls `metrics.record_response(...)`.
  - Failure path: `log_failure(ctx)` (warning + `⚠️` telemetry, computes `elapsed_ms`; runs **outside** the guard), then
    `record_failure(ctx)` (best-effort `req_data` / `resp_data` decode helpers `_best_effort_json(text)`, dump, zeroed
    `record_response`) under
    `FAILURE_POLICY = ErrorPolicy(json_message=None, exception_message="Failed to record non-200 wire transaction: %s",
exception_level="debug")`. The policy formats with `exc`, matching the current message arguments; check against
    the source and make `ErrorPolicy` carry a formatter callable if the two log signatures differ.
  - `RESPONSE_SUCCESS = (load_request, load_response, require_payloads, store_response[active], compute_telemetry,
inject_miss_headers, log_miss_telemetry, dump_miss_transaction, record_response_metrics)`, with
    `SUCCESS_POLICY = ErrorPolicy("Non-JSON request/response body for endpoint %s: %s",
"Mitmproxy response intercept error for endpoint: %s", "exception")`.
- `steps/wire_record.py`:
  - `@dataclass(frozen=True) class WireTransaction`: `is_hit=False`, `is_sse=False`, `ttft`, `total_time`,
    `prefill_tps`, `tail_prefill_tps`, `decode_tps`, `generation_time`, all `None` by default.
  - `build_wire_record(addon, flow, resp_data, status_code, tx) -> dict`. It composes `_identity(flow, headers)`,
    `_delta(raw_req, cleaned_req, clean_res)`, `_usage(...)`, `_content(resp_data, provider, is_sse)` and
    `_timing(tx)`. Each stays under CC 10. The `_timing` dict has many ternaries, so it uses a tiny
    `_ms(v)` / `_round(v)` helper pair. Exact rounding is kept (`round(x * 1000, 2)`; the `ttft_ms` HIT special case is
    `0.0`, and `total_ms` defaults to `0.0`). Key order in the record dict is unchanged so the JSONL output stays
    byte-compatible.
- `MitmproxyAddon._dump_flow_transaction(self, flow, resp_data, status_code=200, **fields)`: returns early when
  `is_wire_logging_enabled()` is false, then `try: dump_wire_transaction(build_wire_record(self, flow, resp_data,
status_code, WireTransaction(**fields)), self.wire_log_dir) except Exception: logger.debug(...)`. That is four
  parameters, so the `PLR0913` noqa is removed, and the keyword interface the tests use is preserved. An unknown
  keyword raises `TypeError` inside the `try` and is logged. That matches today's tolerance less strictly, which is
  fine because only internal callers exist; `grep -rn _dump_flow_transaction src tests` confirms this.
- `MitmproxyAddon.response` becomes:
  ```python
  def response(self, flow: Any) -> None:
      """Mitmproxy response callback: run the ordered response pipeline."""
      ctx = ResponseContext.from_flow(self, flow)
      if ctx is None:  # no request/response, unknown provider, or served from cache
          return
      if ctx.status_code == 200:
          run_guarded(RESPONSE_SUCCESS, ctx, SUCCESS_POLICY)
      else:
          log_failure(ctx)
          run_guarded(RESPONSE_FAILURE, ctx, FAILURE_POLICY)
  ```
  Remove `# noqa: C901, PLR0912, PLR0915` from it.

### Dependencies & Criticality

- **Dependencies:** Steps 2 and 4 (shared `_headers`, `apply_cache`).
- **Is bottleneck:** yes.

### Safety & Constraint Considerations

- **Relevant rules:** Rule 1 and Rule 6. `transactions.jsonl` and `holon-coherence metrics` are the system of record,
  so the record schema and key order must not drift.
- **Failure modes:** a scrub call is dropped (secret leak to the wire log); `getattr` defaults change; the `mode` field
  stops honouring `default_passive`; `elapsed_ms` is computed after the dump instead of before.
- **Guardrails:** the existing `test_dump_flow_transaction_structure` (redaction assertions), the parity wire-record
  comparison (masked timing), and `tests/proxy/test_scrubbing.py` and `test_wire_log.py` all stay green. A dedicated
  test asserts that the `json.dumps(record)` key sequence is identical to a frozen list.

### Success & Discard Criteria

- **Success:** all suites green. `response`, `_dump_flow_transaction` and every new function are clean under ruff with
  no `noqa`.
- **Discard:** if the byte-compatible key order cannot be kept with the helper split, build the dict in a single
  function that only _assembles_ the helper outputs. Order then lives in one place.

### Step Metrics

| metric    | value |
| :-------- | :---- |
| p_success | 0.86  |
| entropy   | 0.35  |
| impact    | 0.80  |
| cost      | 0.09  |
| learning  | 0.10  |

**Step Metrics Rationale:** this is the largest surface, with two error policies and schema-sensitive output, so it
carries the highest step entropy.

## Step 6: Extract the `responseheaders` SSE tap

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** `responseheaders` is a pipeline-adjacent hook with a `# noqa: C901`. A small, low-risk extraction
  removes the last complexity suppression in the touched module (excluding `detect_provider`, which is outside this
  intent).
- **Step type:** implementation (refactor)
- **Exploration level:** low
- **Git branch:** same

### Implementation Details

- `steps/sse_tap.py`:
  - `response_content_type(headers) -> str`: the `.get` / dict loop.
  - `install_sse_tap(flow, response) -> None`: initialises `sse_chunks`, `sse_bytes` and `_sse_stream_state`, captures
    `existing_stream`, defines the **identical** `sse_stream_wrapper` closure (same statements, same
    `_MAX_SSE_BUFFER_BYTES` import from `addon`'s value; move the constant to `steps/sse_tap.py` and re-export it from
    `addon.py` and `mitm_addon.py` under the same name), and assigns `response.stream`.
- `responseheaders` keeps the provider check and timing stamps, then calls `install_sse_tap` when the content type
  contains `text/event-stream`. Remove `# noqa: C901`.

### Dependencies & Criticality

- **Dependencies:** Step 2.
- **Is bottleneck:** no (optional for the core criteria; it decides the ratchet value).

### Safety & Constraint Considerations

- **Failure modes:** SSE chunk ordering, buffering cap or passthrough of a non-callable `existing_stream` changes;
  `_MAX_SSE_BUFFER_BYTES` monkeypatching in tests stops taking effect.
- **Guardrails:** `grep -rn _MAX_SSE_BUFFER_BYTES tests`. If a test patches it on `mitm_addon`/`addon`, the wrapper
  reads it through a `_compat` getter at call time. All 119 tests in `tests/test_mitm_addon_sse.py` must pass.

### Success & Discard Criteria

- **Success:** SSE suites green, and the hook is clean under ruff.
- **Discard:** if any SSE test regresses and the cause is not obvious within one iteration, revert this step entirely.
  Keep the `noqa` and set the ratchet to **39** instead of 38.

### Step Metrics

| metric    | value |
| :-------- | :---- |
| p_success | 0.90  |
| entropy   | 0.15  |
| impact    | 0.20  |
| cost      | 0.03  |
| learning  | 0.05  |

**Step Metrics Rationale:** a small extraction with an explicit fallback.

## Step 7: Step unit tests, pipeline-order tests, ratchet update

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Locks the new architecture in place so it does not quietly grow back into one big hook.
- **Step type:** verification
- **Exploration level:** low
- **Git branch:** same

### Implementation Details

- `tests/proxy/test_steps.py`:
  - Pipeline order: assert `[s.name for s in REQUEST_PRELUDE + REQUEST_GUARDED]` and the response tuples equal the
    frozen lists.
  - Runner: the passive gate skips `active` steps and runs `passive` ones (and the reverse); `HALT` stops the run;
    `passive` is evaluated at most once and not when `snapshot_request` halts; each `ErrorPolicy` routes
    `JSONDecodeError` vs `Exception` to the right level (checked with `caplog`).
  - One focused test per step: `serve_mode` fall-through for `PUT`; `route_local_target` without targets is a no-op;
    `identify_provider` unknown → `HALT` with no counter change; `clean_payload` local fixup;
    `serve_cached` without a cached response → `CONTINUE`; `store_response` skipped for SSE; `build_wire_record` helpers
    (`_delta` with and without `clean_res`, `_content` for SSE/dict/str, `_timing` rounding).
- `tests/test_complexity_baseline.py`: `BASELINE_CEILING = 42` → `38` (or `39` if Step 6 was discarded). Update the
  comment only if one exists that names the addon functions. This is a one-line, justified change outside the declared
  scope, required because the test asserts exact equality.

### Dependencies & Criticality

- **Dependencies:** Steps 4–6.
- **Is bottleneck:** no.

### Safety & Constraint Considerations

- **Failure modes:** the ratchet constant is wrong because other `noqa` lines changed on `main` meanwhile.
- **Guardrails:** compute the value from the test's own regex over `src/` after rebasing onto the latest
  `origin/main`. Do not hard-code it.

### Success & Discard Criteria

- **Success:** the new tests pass; `test_complexity_baseline.py` passes, including `test_ruff_check_clean`.
- **Discard:** n/a.

### Step Metrics

| metric    | value |
| :-------- | :---- |
| p_success | 0.95  |
| entropy   | 0.10  |
| impact    | 0.40  |
| cost      | 0.05  |
| learning  | 0.05  |

**Step Metrics Rationale:** test code only, with a deterministic expected value.

## Step 8: Verification gates and squash

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Acceptance criteria 3–5 and the repository hygiene rules.
- **Step type:** verification / integration
- **Exploration level:** none
- **Git branch:** same; squash to a single commit relative to `main`. **No push** unless the user explicitly instructs
  it.

### Implementation Details

1. `uv run ruff format .` then `uv run ruff check .` (must be clean with **no new** `noqa` anywhere).
2. `uv run ruff check --select C901,PLR0911,PLR0912,PLR0913,PLR0915 src/holon_coherence/proxy` → zero findings.
   Re-run the Step 1 complexity report and record the before/after numbers (expect `request`/`response` CC ≤ 3, and
   every step ≤ 8).
3. `uv run pytest` (and `uv run task test`). The pass count must be ≥ the baseline plus the new tests, with zero new
   failures or skips.
4. `uv build` (or `uv run python -c "import holon_coherence.proxy.steps"`) to confirm the subpackage ships.
5. Line count of `addon.py`: expect about 956 → about 450 lines. Confirm that `mitm_addon.py` re-exports still resolve
   (`tests/test_mitm_addon.py` covers this).
6. `npx prettier --write "**/*.md"` (no markdown should change apart from this plan, which is already formatted).
7. `git rebase origin/main`, squash, then commit with the message
   `refactor(proxy): decompose MitmproxyAddon hooks into ordered step pipeline` and the required `Co-Authored-By`
   trailer.

### Dependencies & Criticality

- **Dependencies:** Steps 1–7.
- **Is bottleneck:** yes (final gate).

### Safety & Constraint Considerations

- **Relevant rules:** §1 squash and no-push rules; §3 ledger immutability (do not touch `holon-knowledge/ledger/*`
  unless the execution protocol says to append); Rule 5 (run everything inside the worktree).
- **Failure modes:** `test_docker_integration` or other environment-dependent tests skip differently from the
  baseline.
- **Guardrails:** compare the skip list against the Step 1 baseline, not against zero.

### Success & Discard Criteria

- **Success:** every acceptance criterion is met, with evidence recorded in the execution report.
- **Discard:** if parity cannot be kept for some segment, ship only the segments that pass. For example, keep
  `response` on the new pipeline and revert `request`, set the ratchet to match, and report the result as a partial
  success.

### Step Metrics

| metric    | value |
| :-------- | :---- |
| p_success | 0.95  |
| entropy   | 0.10  |
| impact    | 0.30  |
| cost      | 0.06  |
| learning  | 0.05  |

**Step Metrics Rationale:** these are deterministic gates; any surprises have already surfaced in earlier steps.

## Strategy Rationale

The EV formula is `EV = P(success) * Impact + mu * LearningValue - lambda * Delta_S_intent - Cost` with lambda = 0.3 and
mu = 0.5 (from `holon-config/metrics/ev_config.json`).

- **P(success) = 0.82:** the product of the step probabilities is about 0.48. But the steps are not independent: the
  Step 1 parity suite turns most failures into fast, local fix-and-retry loops inside the same execution, and Steps 6
  and 8 have explicit partial-success fallbacks. The residual risk is concentrated in Step 5 (two error policies and
  byte-compatible wire records), plus edge-case behaviour that the existing tests and the parity suite might both miss.
- **Impact = 6.0** (0–10 scale): it removes the four worst complexity hotspots on the proxy's hottest path (CC 65 and
  CC 43 hooks) and turns every future proxy feature into "add a step" rather than "add a branch". It does not change
  product behaviour, so it scores below a feature.
- **LearningValue = 1.0:** a reusable characterization harness for the addon, and a validated pipeline pattern that
  other high-CC modules (for example `detect_provider`, `cli.py`) can follow.
- **Delta_S_intent = 1.65:** the sum of the step entropies (0.15 + 0.20 + 0.30 + 0.30 + 0.35 + 0.15 + 0.10 + 0.10).
- **Cost = 0.40:** the step costs sum to 0.50 of a normalised execution budget, discounted because Steps 3–5 share the
  same context and test loop. Estimated at about 0.40.
- **EV = 0.82 × 6.0 + 0.5 × 1.0 − 0.3 × 1.65 − 0.40 = 4.92 + 0.50 − 0.495 − 0.40 = 4.53.**

Alternatives rejected:

- A class-based `Step` hierarchy with a `Chain of Responsibility`. It adds boilerplate without testability gains over
  `StepSpec(name, fn, mode)` tuples.
- Wrapping each step in its own `try`. That would change today's mixed error semantics (the unguarded prelude) and
  scatter error handling, which goes against the intent.
- Merging `clean_payload` and `apply_cache` into a single step. The interceptor returns both results in one call, but
  the side effects (cleaner metrics vs HIT response) are separate concerns, so `ctx` carries `cached_resp` between
  them.
- Rewriting `_dump_flow_transaction` callers to pass a `WireTransaction` directly. That would break the existing test
  call signatures; the `**fields` shim keeps them working.

## Safety & Constraint Alignment

- **Key world ruleset constraints that affect this plan:** `holon-config/world/constraints.md` §1 (hierarchical branch
  naming, worktree isolation, squash, no autonomous push); §2 (stay in the worktree, no persistent proxy env exports;
  tests use `monkeypatch.setenv`); §3 (ledgers are append-only and untouched by this refactor); §4 Rule 1 (no
  synthetic data for efficacy measurement); Rule 5 (repository separation); Rule 6 (metrics and dashboard endpoints
  must keep working, since `/holon/api/metrics` and `/holon/` are served by the `serve_dashboard` step and are
  parity-tested).
- **Potential violations or edge cases:**
  - Rule 1 could be misread as covering the Step 1 fixtures.
  - Editing `tests/test_complexity_baseline.py` is outside the declared scope.
  - A secret-redaction regression in the wire-record split.
  - Changed exception propagation in the unguarded prelude.
  - Late-binding test seams (`holon_coherence.mitm_addon.*`) being captured at import time.
  - Circular imports.
- **Mitigations built into the plan:**
  - The fixtures are documented as functional-regression inputs only, and no efficacy metric is derived from them.
  - The out-of-scope edit is a single constant, needed for acceptance criterion 5.
  - The redaction assertions and `test_scrubbing.py` stay mandatory.
  - The prelude and guarded segments are modelled explicitly, with a `pytest.raises` parity test.
  - All `_get_*()` shims are called at call time.
  - `steps/*` never imports `proxy.addon` at module level.
  - Parity is checked before and after each step.
- **Residual risk accepted (and why):** behaviour on real mitmproxy objects that no test fixture covers (for example
  header-object subtleties in `writable_headers`). This is accepted because the code paths are moved verbatim and the
  existing suites already exercise both real `mitmproxy.http` and duck-typed objects. A live smoke run
  (`holon-coherence <agent> --ephemeral`) is recommended at execution time if a host session is available, but it is
  not required for acceptance.
- **Allocated Entropy Budget:** 5.0
- **Predicted Plan Entropy:** 1.65 (0.15 + 0.20 + 0.30 + 0.30 + 0.35 + 0.15 + 0.10 + 0.10)
- **Budget Compliance:** 1.65 ≤ 5.0. The plan uses 33% of the allocated budget, which leaves room for one full re-try
  of Step 5 if needed.
