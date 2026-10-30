# Execution Record: E-1793363925-claude-agent-claude-opus-5-5

## Summary

Executing plan P-1793363635-claude-agent-claude-opus-5-5: decompose `MitmproxyAddon.request`, `response`,
`responseheaders` and `_dump_flow_transaction` into an ordered step pipeline under
`src/holon_coherence/proxy/steps/`, with wire-level parity pinned by a characterization suite.

Outcome: all eight plan steps completed with no partial-success fallback. `addon.py` went from 956 to 381 lines.
`request`, `response` and `responseheaders` are each CC 3 (previously 35, 22 and 16), `_dump_flow_transaction` is
CC 3 with 4 parameters (previously 11), and every new step function is at most CC 8. The four complexity `noqa`
suppressions were removed and the ratchet was lowered from 42 to 38. The 38-scenario golden parity suite, captured
from the unmodified hooks, passes unchanged against the refactor. The full suite has 1103 passed and 4 skipped
(baseline: 1033 passed, 4 skipped; +70 new tests, no new failures or skips).

## Actual Metrics

| metric                | value |
| :-------------------- | :---- |
| success_actual        | 1.00  |
| entropy_actual        | 1.30  |
| impact_actual         | 6.00  |
| cost_actual           | 0.35  |
| learning_value_actual | 1.00  |

## Steps Executed

- **Step 1 – Worktree, baseline and characterization suite:** Worked in the harness-provided execution worktree
  (branch `I-1793355582-.../E-1793363925-claude-agent-claude-opus-5-5/_`, not `main`). `uv` was not on the host, so it was
  installed user-level (`pip install --user uv`) and `uv sync` created the worktree-local `.venv`. Baseline:
  `uv run pytest` → 1033 passed, 4 skipped, 8 deselected; `uv run ruff check .` clean; ratchet 42. Per-function
  complexity of `addon.py` (ruff, `--ignore-noqa`, max-complexity=0): `request` CC 35 / 37 branches / 124 statements,
  `response` CC 22 / 24 branches / 96 statements, `responseheaders` CC 16, `_dump_flow_transaction` CC 7 with 11 args.
  Added `tests/proxy/test_addon_pipeline_parity.py` (38 golden scenarios plus 4 explicit quirk pins) and the golden
  file `tests/proxy/fixtures/addon_parity_golden.json`, captured from the unmodified hooks. Green 3 runs in a row.
  Quirks pinned as-is: `PUT`/other methods on mode endpoints and `POST` on metrics fall through to the proxy path;
  Gemini-bridge and Anthropic-local-normaliser exceptions propagate out of `request`; a dict `Content-Type` key in
  non-canonical case (e.g. `CONTENT-TYPE`) is not detected as SSE because dicts take the `.get` branch;
  `response_without_req_data` records a MISS even though `total_requests` is 0.
- **Step 2 – Scaffold `proxy/steps/`:** Added `steps/base.py` (`Outcome`, `RequestContext` / `ResponseContext` with a
  lazily evaluated, cached `passive` property, `StepSpec(name, fn, mode)`, `ErrorPolicy`, `run_steps` with the single
  passive/active gate and `run_guarded` with the single error policy; logger name kept as
  `holon_coherence.proxy.addon`), `steps/_compat.py` (the five `_get_*` late-binding shims moved verbatim plus
  `resolve_response_cls`) and `steps/_headers.py` (`writable_headers`). `ErrorPolicy` gained an `exception_arg`
  (`"url"` / `"exc"`) because the non-200 policy formats its message with the exception, not the URL. No module in
  `steps/` imports `proxy.addon`; `_compat` reaches it lazily through `sys.modules`.
- **Step 3 – Request prelude:** `serve_dashboard.py` (`serve_metrics`, `serve_mode` with `_mode_post` / `_mode_get`
  and fall-through for other methods, `serve_html`, `serve_dashboard`), `route_local_target.py`
  (`route_local_target` recomputes `ctx.url` after the own-port rewrite; `adapt_local_protocol` with
  `_bridge_target_model` / `_bridge_gemini` and the Anthropic local normaliser) and `identify_provider.py`
  (`parse_request_body`, `identify_provider`). `REQUEST_PRELUDE` runs unguarded through `run_steps`, so bridge and
  normaliser exceptions still propagate (pinned by `pytest.raises` tests).
- **Step 4 – Guarded request steps:** `clean_payload.py` (`snapshot_request`, passive `passthrough_payload`, active
  `clean_payload` with `_intercept` / `_log_cleaner`) and `apply_cache.py::serve_cached` (active).
  `MitmproxyAddon.request` is now an 8-line dispatcher (CC 3); its `noqa: C901, PLR0912, PLR0915` is gone. Parity
  suite and the existing addon tests were green with only the request side wired.
- **Step 5 – Response pipeline and wire record:** `load_exchange.py` (`load_request`, `load_response`,
  `require_payloads`), `apply_cache.py::store_response` (active), `record_metrics.py` (`Telemetry`,
  `compute_telemetry`, `inject_miss_headers`, `log_miss_telemetry`, `dump_miss_transaction`,
  `record_response_metrics`, `log_failure`, `record_failure`) and `wire_record.py` (`WireTransaction`,
  `build_wire_record` assembling `_identity` / `_delta` / `_usage` / `_content` / `_mode` / `_timing` in one dict
  literal, so key order is unchanged). `response` (CC 3) and `_dump_flow_transaction(self, flow, resp_data,
status_code=200, **fields)` (CC 3) are slim dispatchers; both `noqa` suppressions are removed.
- **Step 6 – SSE tap:** `steps/sse_tap.py` (`response_content_type`, `install_sse_tap` with the wrapper closure
  unchanged, `_MAX_SSE_BUFFER_BYTES` moved here and re-exported from `addon.py`, so `proxy` and `mitm_addon` still
  export it). `responseheaders` is CC 3 and its `noqa: C901` is removed. The `_get_*` shims were then deleted from
  `addon.py`, which imports the four it uses from `_compat`. No test imports them from `addon`.
  - Harness fix found while doing this: the golden pinned a `content-length` that depends on the pytest tmp-path
    length (mode endpoint bodies embed `wire_log_dir`). The harness now asserts that `content-length` equals the
    body length. The golden was **regenerated against the stashed, unmodified `addon.py`**, then re-verified against
    the refactor (3 runs green).
- **Step 7 – Step tests and ratchet:** Added `tests/proxy/test_steps.py` (28 tests): frozen pipeline order and modes;
  the runner's passive gate in both directions; `HALT` semantics; `passive` evaluated at most once and not at all when
  `snapshot_request` halts; every `ErrorPolicy` routed to the right level, message and `exc_info` (via `caplog`);
  focused tests for `serve_mode` `PUT` fall-through, a no-op `route_local_target`, `identify_provider` unknown → `HALT`,
  the `snapshot_request` deep copy, the `clean_payload` local fixup, `serve_cached` → `CONTINUE`, `store_response` SSE
  bypass, `_delta` / `_content` / `_timing`, the frozen wire-record key order with redaction, and unknown
  `_dump_flow_transaction` fields being logged rather than raised. `BASELINE_CEILING` in
  `tests/test_complexity_baseline.py` went from 42 to 38. The value was computed with the test's own regex over
  `src/`; this is the single out-of-scope line.
- **Step 8 – Gates and commit:** ruff format/check clean; the complexity-only ruff selection over
  `src/holon_coherence/proxy` is clean with no new `noqa` anywhere (the only `noqa` left in `addon.py` is the
  out-of-scope `detect_provider` `PLR0911`). `uv build` wheel contains all 13 `proxy/steps/*.py` modules. Overhead for
  a passive request+response pair (wire logging off, median of 3×5×2000 runs) went from 10.9 µs to 15.0 µs, i.e. about
  2 µs per hook, which is within the 5 µs per-hook discard threshold, so the dataclass contexts were kept. Prettier was
  applied to this record only. Two pre-existing plan files (`plans/P-1793325374-…`, `plans/P-1793334823-…`) already
  fail `prettier --check` on the base commit and were left untouched (out of scope). There is no local `main` /
  `origin/main` ref in this worktree, so the work is committed as one squashed commit on top of the plan commit
  `4161651`. Nothing was pushed.
- **Deviations from the plan:** (1) `ErrorPolicy` carries an `exception_arg` field instead of a formatter callable;
  this is the option the plan allows when the log signatures differ. (2) `RESPONSE_FAILURE` is a single
  `record_failure` step with `_load_failure_request` / `_load_failure_response` helpers. (3) `store_response` is gated
  `active` by the runner, so `passive` is now also evaluated for SSE responses, where the original short-circuited on
  `is_sse` first. `is_flow_passive` has no side effects and swallows its own errors, so this is not observable (the
  parity suite confirms). (4) The `_get_*` shims are no longer importable from `proxy.addon` except the four it uses;
  no caller in `src/` or `tests/` imported them from there. (5) No live `holon-coherence <agent> --ephemeral` smoke run
  was performed. The plan marked it optional, and no host agent session was available in this sandbox.

## Tests Run

| command                                                                                                          | result                                                                               |
| :--------------------------------------------------------------------------------------------------------------- | :----------------------------------------------------------------------------------- |
| `uv run pytest -q` (baseline, before changes)                                                                    | 1033 passed, 4 skipped, 8 deselected                                                 |
| `uv run pytest -q tests/proxy/test_addon_pipeline_parity.py` on unmodified `addon.py` (×3, after golden capture) | 42 passed each run                                                                   |
| `uv run pytest -q tests/proxy/test_addon_pipeline_parity.py` on refactored code (×3)                             | 42 passed each run                                                                   |
| `uv run pytest -q` (final)                                                                                       | 1103 passed, 4 skipped, 8 deselected                                                 |
| `uv run task test`                                                                                               | 1103 passed, 4 skipped, 8 deselected                                                 |
| `uv run ruff format .` / `uv run ruff check .`                                                                   | 167 files unchanged / All checks passed                                              |
| `uv run ruff check --select C901,PLR0911,PLR0912,PLR0913,PLR0915 src/holon_coherence/proxy`                      | All checks passed                                                                    |
| `tests/test_complexity_baseline.py` (ratchet 38, `test_ruff_check_clean`)                                        | passed                                                                               |
| `uv build` + wheel listing                                                                                       | all `holon_coherence/proxy/steps/*.py` shipped                                       |
| `npx prettier --check "**/*.md"`                                                                                 | this record formatted; 2 pre-existing plan files fail on the base commit (untouched) |
