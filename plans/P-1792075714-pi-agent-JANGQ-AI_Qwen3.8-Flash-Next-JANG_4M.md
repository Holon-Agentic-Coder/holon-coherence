# Plan for I-1792075530-coherence-telemetry-metrics-prefill-decode

- **Plan ID:** P-1792075714-pi-agent-JANGQ-AI_Qwen3.8-Flash-Next-JANG_4M
- **Agent:** pi-agent
- **Model:** JANGQ-AI/Qwen3.8-Flash-Next-JANG_4M
- **Created At:** 2026-10-15T14:48:34Z
- **Bean:** holon-agentic-coder-ref-metadata-0097
- **Target Repository:** `holon-coherence` (base `origin/main` @ `6599f4b`, i.e. Bean 0096 merged)

## Overall Plan Metrics

| metric              | value |
| ------------------- | ----- |
| p_success_pred      | 0.9   |
| entropy_pred        | 2.0   |
| impact_pred         | 80.0  |
| cost_pred           | 4.0   |
| learning_value_pred | 3.0   |
| ev_pred             | 68.9  |

## 1. Problem Statement

Three defects make `holon-coherence` telemetry untrustworthy:

1. **Prefill speed reads `0.00 tokens/sec` while 1.2M+ prompt tokens are recorded.**
   `MitmproxyAddon.response()` back-filled missing timing stamps with `time.perf_counter()`:

   ```python
   if req_start is None:
       req_start = now  # both stamps land on the same reading
   if resp_headers_time is None:
       resp_headers_time = now  # => ttfb = 0.0, ttft = 0.0
   prefill_tps = input_tokens / ttft if ttft > 0 else 0.0
   ```

   A flow whose request hook never stamped `request_start_time` (resumed/replayed flows, and any
   path where `request()` is not observed for the same flow object) therefore produced
   `ttft == 0.0` and a _fabricated_ `0.00` prefill reading next to a genuinely large token volume.
   `0.0` was then indistinguishable from "no data" in every consumer.

2. **Decode throughput reads 34,000-38,000+ tokens/sec.**
   `generation_time = total_time - ttft` is used for **every** reply. For a **non-streaming** reply
   the headers and the whole body arrive in the same network chunk, so `total_time - ttft` collapses
   to socket parse time (~1-2 ms) and `output_tokens / generation_time` explodes. Because
   `CumulativeMetrics.record_response()` admits any `output_tps > 0`, those samples enter
   `sum_decode_throughput_tps / count_decode` and poison the cumulative average forever. The same
   arithmetic exists a second time in `_read_offline_metrics` (`total_ms - ttft_ms`).

3. **Four surfaces re-implement the arithmetic independently** -- `CumulativeMetrics.to_dict()`,
   `/holon/api/metrics`, the `/holon/` dashboard, the `holon-coherence metrics` scorecard and
   `_read_offline_metrics` -- so a fix applied to one silently diverges from the others, and the
   wire log carried only `ttft_ms` / `total_ms`, which is not enough to tell a streaming window from
   a socket-parse window after the fact.

## 2. Design

### 2.1 Single source of truth: `src/holon_coherence/metrics_math.py` (new)

Pure, dependency-free helpers used by every surface:

- `MIN_STREAMING_WINDOW_SEC = 0.05` -- the shortest generation window that can be trusted.
- `positive_seconds(v)` / `positive_rate(v)` -- coerce to a strictly positive float or `None`
  (**`None` means "not measured"**, never `0.0`); NaN, ±inf and booleans are rejected.
- `compute_prefill_tps(input_tokens, ttft_sec)` -> `float | None`.
- `compute_tail_prefill_tps(uncached_input_tokens, ttft_sec)` -> `float | None`.
- `compute_decode_tps(output_tokens, generation_sec, streaming)` -> `float | None`; returns `None`
  unless `streaming` is true **and** `generation_sec >= MIN_STREAMING_WINDOW_SEC`.
- `average(total, count)` and `format_rate(value, precision)` (renders `unmeasured`).

### 2.2 One clock domain per flow: `resolve_flow_timing()`

`mitm_addon.py` gains a `FlowTiming` dataclass (`ttft_sec`, `total_sec`, `generation_sec`,
`streaming`) and `resolve_flow_timing(flow, completed_at)`:

- Prefers the `time.perf_counter()` stamps recorded by `request()`, `responseheaders()` and the SSE
  chunk wrapper; never mixes clocks.
- When `request_start_time` is absent it falls back to mitmproxy's own epoch stamps
  (`request.timestamp_start`, `response.timestamp_first_byte`, `response.timestamp_end`) instead of
  substituting `now`, so a missing stamp yields a real TTFT or an honest `None` -- never `0.0`.
- `generation_sec` is computed **only** for SSE streams, as `last_chunk_time - first_chunk_time`.
  `responseheaders()`' chunk wrapper now also stamps `flow.last_chunk_time`. For a buffered reply
  `generation_sec` stays `None`, so no decode rate can be derived from parse latency.

### 2.3 Accumulators

`CumulativeMetrics.record_response()` takes `output_tps`, `prefill_tps` and `tail_prefill_tps` as
`float | None` (`None` = not measured) plus `total_time`, and adds `latest_decode_tps`,
`latest_ttft_ms`, `latest_total_time_ms`. `to_dict()` additively exposes
`latest_decode_throughput_tps`, `latest_total_time_ms`, `latest_ttft_ms` and
`decode_samples` (how many streaming samples back the decode average). Existing key names and
semantics are unchanged, so `/holon/api/metrics` stays backward compatible; the dashboard now shows
latest decode and the streaming-sample count.

### 2.4 Wire log contract (additive)

`_dump_flow_transaction()` writes the resolved rates so offline readers do not re-derive them from
rounded milliseconds:

```json
"timing": {
  "ttft_ms": 500.0, "total_ms": 900.0,
  "streaming": true, "generation_ms": 400.0,
  "prefill_tps": 2000.0, "tail_prefill_tps": 2000.0, "decode_tps": 250.0
}
```

Non-streaming records carry `"streaming": false` with `"generation_ms": null` and
`"decode_tps": null`.

### 2.5 Offline parser

`_read_offline_metrics()` uses the same helpers and prefers the stored rates. For records written
before this change (no `streaming` key, no `decode_tps`) it falls back to `total_ms - ttft_ms`
**through `compute_decode_tps`**, whose 50 ms floor rejects exactly the 1-2 ms windows that produced
the 34k-38k artefacts while still admitting credible legacy windows.

### 2.6 Telemetry headers

`X-Holon-Streaming` is added; `X-Holon-TTFT-Ms`, `X-Holon-Decode-Time-Sec`, `X-Holon-Total-Time-Ms`,
`X-Holon-Prefill-TPS`, `X-Holon-Tail-Prefill-TPS` and `X-Holon-Output-TPS` render the literal
`unmeasured` instead of a fabricated `0.0000`. The `[TELEMETRY]` log line reports
`Output: n/a [non-streaming] (1500 tok)` for those transactions.

## 3. Steps

1. Add `src/holon_coherence/metrics_math.py` (pure arithmetic + floor constant + `unmeasured`
   rendering).
2. `mitm_addon.py`: import helpers; add `FlowTiming` + `resolve_flow_timing()`; stamp
   `flow.last_chunk_time` in the SSE wrapper; replace the timing block in `response()`; widen
   `CumulativeMetrics` and `to_dict()`; extend `_dump_flow_transaction()`; expose latest decode and
   sample count in the dashboard.
3. `commands/metrics.py`: consume the shared helpers in `_read_offline_metrics()`, publish the same
   `latest_*` / `decode_samples` keys, and label the decode line in the terminal scorecard.
4. Tests: `tests/test_mitm_addon.py` (`TestTelemetryThroughputBean0097` -- 10 cases),
   `tests/test_cli.py` (`TestOfflineTelemetryThroughputBean0097` -- 5 cases, including a
   live-vs-offline equality check over 24 shared keys).
5. Verify: `ruff check .`, `ruff format --check .`, `pytest -m "not integration_test"`.

## 4. Acceptance Criteria Mapping

| Acceptance criterion                                                                            | Implementation                                        | Test                                                                                                                                                 |
| ----------------------------------------------------------------------------------------------- | ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| Non-streaming requests never compute or corrupt decode TPS                                      | `generation_sec` is `None` unless SSE; header/logging | `test_non_streaming_reply_never_samples_decode`                                                                                                      |
| Sub-50 ms generation windows are guarded                                                        | `compute_decode_tps` floor                            | `test_buffered_stream_burst_below_floor_is_unmeasured`                                                                                               |
| Prefill = prompt tokens / TTFT whenever both are positive                                       | `compute_prefill_tps`, no `now` substitution          | `test_genuine_stream_yields_prefill_and_decode`, `test_missing_start_timestamp_is_unmeasured_not_zero`, `test_wall_clock_timestamps_recover_prefill` |
| All surfaces mathematically consistent                                                          | shared `metrics_math`, stored wire-log rates          | `test_live_and_offline_metric_surfaces_agree`, `test_wire_log_publishes_streaming_timing`                                                            |
| Comprehensive tests for streaming and non-streaming TPS in `test_mitm_addon.py` / `test_cli.py` | 15 new cases                                          | both classes                                                                                                                                         |

## 5. Risks and Mitigations

- **Consumers of `X-Holon-Output-TPS` expecting a float.** Values are unchanged when measurable;
  only previously fabricated `0.0000` readings become the literal `unmeasured`.
- **Legacy wire logs lose decode samples whose window is sub-50 ms.** Intended: those samples were
  parse latency, not generation speed. Plausible legacy windows (>= 50 ms) are still admitted and
  covered by `test_legacy_plausible_window_is_still_admitted`.
- **JSON contract.** Strictly additive; no key renamed or removed.

## 6. Authorship Note (Out-of-Flow Execution)

The intent / plan / execute branch chain, `intents.jsonl`, `plans.jsonl` and `executions.jsonl` rows
and commit identities below were produced by the host-side Holon Flow stage code
(`sandbox_executor.flow.run_intent_stage` / `run_plan_stage`) and then authored by this pi session,
**at explicit user instruction**, instead of by the containerized planner/executor roles: those roles
`git clone` the target repository from `origin` inside the sandbox, and the host currently has no
network egress. Stages 4 (PR creation + review loop) and 5 (calibration) were **not** run and remain
outstanding; they must execute once connectivity is restored, per the Bean 0097 runbook.
