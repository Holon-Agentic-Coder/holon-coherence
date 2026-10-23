# Plan for I-1792762893-coherence-mitmweb-inspection-and-monotonic-readiness

- **Plan ID:** P-1792766452-claude-agent-claude-opus-5-5
- **Parent Intent ID:** NONE
- **Agent:** claude-agent (version: 2.1.302)
- **Created At:** 2026-10-23T14:40:53.485Z

## Planner Autonomy Summary

- **Intent handling:** `ACCEPT_AS_IS`
- **Reframed intent (if applicable):** NONE
- **Exploration stance:** Mostly exploitation. Both beans are confined to code paths the planner has already read
  (`commands/start.py`, `commands/docker_ops.py`, `commands/metrics.py`, `commands/web_token.py`, `cli.py`). The
  existing `--web` branch already does port fallback, token resolution and persistence, so Bean 0129 is mainly about
  turning that branch on by default and reporting the endpoints in one shared way. The one open design question is how
  the in-container `start` banner treats the token, because it ends up in `docker logs`. That question is settled in
  Step 2 and is the only exploratory element.
- **Safety priority level:** elevated
- **Priority Justification:** The change enables a credential-protected UI by default and prints that credential to the
  terminal. A careless implementation could leave the UI unauthenticated, bind it beyond loopback, or write the token
  into persisted logs (`~/.holon/logs`, `docker logs`). Wire-log scrubbing has to stay intact. The clock change is
  low-risk but touches the cold-start path that every `run`/`run-agent` call depends on.

## Exploration

- **Proportion of steps that are exploratory:** 0.15
- **Justification:** Five of six steps are deterministic edits against code that has already been inspected. Part of
  Step 2 is exploratory: confirming the mitmweb 12.2.3 option names (`web_password`, `web_open_browser`) inside the
  pinned image and settling how the in-container token banner behaves. This is bounded by checking `mitmweb --options`
  in the image, or the mitmproxy 12 option docs, before writing code.

## Overall Plan Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.90  |
| entropy_pred        | 4.40  |
| impact_pred         | 8.50  |
| cost_pred           | 1.60  |
| learning_value_pred | 3.50  |
| ev_pred             | 6.48  |

### Strategy Rationale

`EV = P(success) * Impact + mu * LearningValue - lambda * Delta_S_intent - Cost` with `lambda = 0.3`, `mu = 0.5` (from
`holon-config/metrics/ev_config.json`):

- `P * Impact = 0.90 * 8.50 = 7.65`
- `mu * LV = 0.5 * 3.50 = 1.75`
- `lambda * Delta_S = 0.3 * 4.40 = 1.32`
- `Cost = 1.60`
- `EV = 7.65 + 1.75 - 1.32 - 1.60 = 6.48`

**P(success) = 0.90.** Most of the needed code already exists. The fallback loop, `resolve_web_password` and
`save_web_token` are all in place. The main risk is regressions in the roughly 15 existing `start` tests in
`tests/test_cli.py`, which assume a plain `start` emits no `-p ...:8081` mapping and no `--web`. **Impact = 8.5.** Every
developer gets live traffic inspection by default, and cold-start readiness becomes immune to NTP or suspend clock
steps. **Entropy = 4.40**, the sum of the step entropies, well inside the 12.0 budget. **Cost = 1.6.** The work is
moderate edits across five source files, one new helper module, tests and two docs. **Learning value = 3.5.** It
establishes a reusable endpoint-reporting helper and a monotonic-clock testing pattern.

## Safety & Constraint Alignment

- **Key world ruleset constraints that affect this plan:**
  - `ruleset.md` §1: Python 3.13, `uv` only, `.venv` at the worktree root. All tools run via `uv run`.
  - `ruleset.md` §2: PEP 8, explicit type hints on all new public functions and dataclasses, docstrings preserved and
    added, Ruff clean (`ruff check` and `ruff format --check` via `make lint` / `uv run ruff check .`).
  - `ruleset.md` §3: hermetic tests with no Docker, network or real ports in unit tests. Patch `is_port_in_use`,
    `get_container_mapped_port`, `subprocess.run`, `_urlopen_no_proxy` and the module `time`. Existing tests stay at a
    100% pass rate, and integration tests stay behind `@pytest.mark.integration_test`.
  - `constraints.md` §1: work on the intent branch hierarchy and squash to a single logical commit. Never push to
    `main`.
  - `constraints.md` §2: stay inside the workspace. No persistent `export` of proxy variables.
  - `constraints.md` §3: `holon-knowledge/ledger/*.jsonl` is append-only and is not touched by this plan.
  - `constraints.md` §4 Rule 1: no synthetic or mock data is used to report metrics. Tests may mock transport (for
    example a fake HTTP 200 for readiness) but must never assert or publish benchmark numbers from fabricated data.
  - Intent-specific: Australian English in comments, docstrings and log strings (for example "optimisation",
    "behaviour", "initialise"), no new runtime dependencies, and markdown formatted only with the repository's own
    configuration (`make lint-md`, i.e. `npx prettier --no-config`, the same invocation the Makefile uses).
- **Potential violations or edge cases:**
  1. **Unauthenticated inspector.** If the default path skipped `resolve_web_password`, mitmweb would start with its own
     random token that we never print, or with no password.
  2. **Token leakage.** The in-container banner (`🌐 Web dashboard exposed at ...?token=...`) runs inside the container.
     With `-d`, its stdout is kept by `docker logs`. The token is also passed via `-e HOLON_COHERENCE_WEB_PASSWORD`,
     which makes it visible in `docker inspect`. That is existing behaviour and is kept as is.
  3. **Inspector shows raw, unscrubbed traffic.** mitmweb holds live flows in memory, including `Authorization` headers.
     Scrubbing applies to persisted wire logs, not to the in-memory flows that mitmweb renders. Scrubbing those flows
     would corrupt upstream requests.
  4. **Port collisions.** The inspector port could collide with the proxy port, with an occupied host port, or with a
     `--local-llm-base` model server on 8081, which the README already warns about at lines 360-361.
  5. **Stale URL.** `~/.holon/web-token` persists after `stop`, so `status` or `metrics` could print a URL for a
     container that is down or headless.
  6. **Behaviour change for `run`/`run-agent`.** `ensure_proxy_running()` launches the image with `start --port 8080`.
     If the in-container `start` now defaults to mitmweb, those background containers would silently run an unmapped
     mitmweb with a throwaway token.
  7. **Clock audit over-reach.** `hybrid_cache.created_at` and `openbrain_memory` timestamps are persisted epoch values
     compared across processes and must stay `time.time()`.
- **Mitigations built into the plan:**
  1. The default path calls the same `resolve_pwd(...)` and `save_tok(...)` as today's `--web` path, and passes
     `--set web_password=<token>` to mitmweb. A unit test asserts the token appears in the mitmweb argv and in the
     docker `-e` list.
  2. The in-container banner no longer prints the raw token. It prints the URL with the token masked and points to
     `holon-coherence web-token` / `status`. The host-side `start` prints the full
     `http://127.0.0.1:<port>/?token=<token>` to the user's terminal only, because the host process is not captured by
     `docker logs` or wire logs. A test asserts the in-container output has no raw token. mitm_addon never sees CLI
     stdout, and `_URL_QUERY_SECRET_PATTERN` already redacts `token=` query values. A test pins that, so an inspector
     URL that ever lands in a logged request is redacted.
  3. The docs state plainly that the inspector shows raw secrets, is bound to `127.0.0.1` on the host, and is
     token-gated. They also give the opt-out (`--no-web`).
  4. The fallback loop is reused and extended to skip both the resolved proxy port and any `--local-llm-base` port.
  5. `status` and `metrics` print an inspector URL only when the container is running **and**
     `docker port <name> 8081/tcp` resolves. Otherwise they print `not running`. A missing token file on a running
     inspector prints a hint, not a broken URL.
  6. `ensure_proxy_running()` explicitly appends `--no-web`, which keeps `run`/`run-agent` headless exactly as today.
     The host `start` always passes an explicit `--web --web-port 8081` or `--no-web` to the container.
  7. The audit converts only in-process durations and gates. `hybrid_cache._next_prune_at` moves to `time.monotonic()`
     while the TTL cutoff keeps `time.time()`. Epoch timestamps are listed and left untouched, with a short comment
     where the distinction is non-obvious.
- **Residual risk accepted (and why):** The token stays visible via `docker inspect` (env) and `ps` inside the container
  (`--set web_password=`). Both are pre-existing, local-only and outside the intent's "wire logs / unsanitised output"
  scope. The intent requires the token to be printed on the host terminal, so terminal scrollback holds it by design.
  mitmweb shows unscrubbed live traffic, which is the purpose of a raw inspector. It is mitigated by loopback binding
  and the token.
- **Allocated Entropy Budget:** 12.0
- **Predicted Plan Entropy:** 0.50 + 1.20 + 1.00 + 0.90 + 0.50 + 0.30 = 4.40
- **Budget Compliance:** 4.40 / 12.0 (37%). Compliant with ample headroom for rework on test regressions.

## Plan Description & Strategy

1. **Monotonic readiness deadline and clock audit (Bean 0133).** Convert `wait_for_proxy_ready()` to `time.monotonic()`,
   audit every `time.time()` in `src/holon_coherence`, and convert only duration and gate uses.
2. **mitmweb inspector by default (Bean 0129).** Make `--web` default-on via `argparse.BooleanOptionalAction`, which
   adds `--no-web`. Run the existing port fallback and token resolution on every non-headless start, mask the token in
   the in-container banner, and keep `run`/`run-agent` headless.
3. **Shared endpoint reporting.** Add a small `commands/endpoints.py` helper that resolves and formats the proxy,
   Coherence dashboard and mitmweb inspector rows in the `metrics` table style. Use it from `start`, `status`, `metrics`
   and `web-token`.
4. **Unit tests.** Cover the monotonic clock (backwards step, forwards step, immediate 200), default mitmweb, the
   opt-out, the port fallback, endpoint output, token masking and the scrub regression. Adjust existing `start` tests to
   the new default.
5. **Docs.** Update README.md and `docs/running_mitm_sidecar_guide.md`, plus the mitmweb note in
   `docs/token_reduction_measurement_plan.md` if needed.
6. **Quality gates.** Run `make lint`, `uv run ruff check .` and `uv run pytest -m "not integration_test"` until all are
   green, then format the changed markdown with `make lint-md`'s Prettier invocation and squash-commit.

## Step-by-Step Breakdown

## Step 1: Monotonic readiness deadline and `time.time()` audit (Bean 0133)

### Step Intent & Git Integration

- **Sub-intent recommendation:** none. Keep it inline.
- **Reasoning:** A two-line production fix plus an audit. It is small and independent, so it is done first for an early
  green signal.
- **Step type:** bug fix / hardening
- **Exploration level:** 0.0
- **Git branch:**
  `I-1792762893-coherence-mitmweb-inspection-and-monotonic-readiness/P-1792766452-claude-agent-claude-opus-5-5/E-<ts>-<agent>-<model>/_`

### Implementation Details

1. In `src/holon_coherence/commands/start.py`, `wait_for_proxy_ready()` (lines ~147-190):
   - `deadline = time.time() + timeout` becomes `deadline = time.monotonic() + timeout`.
   - `while time.time() < deadline:` becomes `while time.monotonic() < deadline:`.
   - Extend the docstring: the timeout is a duration measured on the monotonic clock, so a wall-clock step (NTP
     correction, VM resume, manual `date`) can neither stretch nor cut short the cold-start wait.
   - Keep the call through the module-level `time` reference (`time.monotonic()`, not `from time import monotonic`) so
     tests can keep patching `holon_coherence.commands.start.time`.
2. Audit result. Run `grep -rn "time\.time()" src/holon_coherence` to confirm it at execution time:
   - `hybrid_cache.py:142` `_freshness_clause` (`time.time() - ttl`, compared with persisted `created_at`) is an epoch
     comparison against stored data. **Keep.**
   - `hybrid_cache.py:158-161` `_prune_expired` uses `now` both for the persisted cutoff (epoch, **keep**) and for the
     in-process `_next_prune_at` gate (a duration, **convert**). Split it into `now = time.time()` for `cutoff` and
     `tick = time.monotonic()` for `if not force and tick < self._next_prune_at` and
     `self._next_prune_at = tick + self.prune_interval_seconds`. The `0.0` initial value still means "sweep on first
     write", because the monotonic clock is non-negative. Add a one-line comment explaining the split.
   - `hybrid_cache.py:417` (`now` stored as `created_at`) is an epoch record. **Keep.**
   - `openbrain_memory.py:60` (stored memory timestamp) is an epoch record. **Keep.**
   - `mitm_addon.py` already uses `time.perf_counter()` for TTFT and durations and `datetime.now(UTC)` for wire-record
     timestamps. `ab_test.py` uses `perf_counter`. **No change.**
   - The second loop in `ensure_proxy_running()` (line ~396) is already monotonic. **No change.**
3. Check `tests/test_hybrid_cache.py` for any test that patches `time.time` to drive prune gating. If one exists, update
   it to patch `time.monotonic` for the gate while keeping the `time.time` patch for the TTL cutoff.

### Dependencies & Criticality

- **Dependencies:** none.
- **Is bottleneck:** no.

### Safety & Constraint Considerations

- **Relevant rules:** ruleset §2 (docstrings preserved, Ruff clean), §3 (existing tests pass).
- **Failure modes:** `test_wait_for_proxy_ready_timeout` patches the module `time` with a `MagicMock` that only drives
  `.time`. After the change, `fake_time.monotonic` would return a `MagicMock` and the comparison would raise
  `TypeError`. That test must be updated in Step 4 to drive `.monotonic`. Converting an epoch use by mistake would break
  TTL expiry across restarts.
- **Guardrails:** Only the four `time.time()` sites above are touched, and only the prune gate changes. Each kept site
  is justified in the audit table that goes into the execution report.

### Success & Discard Criteria

- **Success:** `wait_for_proxy_ready` contains no `time.time()`, the audit table is recorded, and the hybrid cache tests
  pass.
- **Discard:** If converting the prune gate breaks hybrid-cache tests in ways that require changing semantics, revert
  that single sub-change and record it as deferred. The readiness fix is the mandatory part.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.96  |
| entropy_pred        | 0.50  |
| impact_pred         | 6.50  |
| cost_pred           | 0.20  |
| learning_value_pred | 2.50  |
| ev_pred             | 7.14  |

### Step Metrics Rationale

The change is mechanical and the target lines were identified exactly. EV = 0.96·6.5 + 0.5·2.5 − 0.3·0.5 − 0.2 = 7.14.

## Step 2: mitmweb inspector enabled by default with opt-out and port fallback (Bean 0129)

### Step Intent & Git Integration

- **Sub-intent recommendation:** none.
- **Reasoning:** This is the core behaviour change. It reuses the existing `--web` machinery instead of duplicating it.
- **Step type:** feature
- **Exploration level:** 0.30 (confirm the mitmweb 12.2.3 option names and the token banner policy)
- **Git branch:** same execution branch.

### Implementation Details

1. **CLI (`src/holon_coherence/cli.py`, lines ~208-214):**
   - Replace `--web` `store_true` with
     `start_parser.add_argument("--web", action=argparse.BooleanOptionalAction, default=True, help="Launch the mitmweb raw request/response inspector (default: on; use --no-web for a headless mitmdump-only start)")`.
     `--web` stays accepted for backward compatibility and `--no-web` is the explicit opt-out.
   - Update the `--web-port` help: "mitmweb inspector host port (default: 8081; falls back to the next free port if
     occupied)".
   - Leave `--web-password` unchanged.
2. **Host path in `handle_start()` (`commands/start.py`, lines ~651-705):**
   - Introduce `web_enabled = bool(getattr(args, "web", True))`. `getattr` keeps callers that build a bare `Namespace`
     working.
   - When `web_enabled`, keep the token handling exactly as today: `web_password = resolve_pwd(...)`, then
     `save_tok(web_password)`.
   - Port fallback: keep the existing loop, and add a `reserved` set made of `actual_proxy_port` plus
     `start_route.target.port` when `--local-llm-base` is given. Loop
     `while actual_web_port in reserved or in_use(actual_web_port): actual_web_port = find_port(actual_web_port + 1)`.
     Keep the existing warning text, but say "mitmweb inspector" instead of "web dashboard".
   - Docker args stay unchanged when enabled: `-p 127.0.0.1:{actual_web_port}:8081` (loopback-only) and
     `-e HOLON_COHERENCE_WEB_PASSWORD=...`. The container command becomes `start --port 8080 --web --web-port 8081` when
     enabled, or `start --port 8080 --no-web` when headless. The flag is always explicit, so the in-container default
     never matters.
   - Replace the two token `print` lines (and the error messages' `web=... if args.web else 'N/A'`) with the shared
     endpoint block from Step 3, using
     `ExposedEndpoints(proxy_port=actual_proxy_port, web_port=actual_web_port if web_enabled else None, web_token=web_password)`.
     Error messages use `web_enabled`.
3. **In-container path (lines ~558-590):**
   - `tool = "mitmweb" if web_enabled else "mitmdump"`.
   - Keep `--web-host 0.0.0.0` (required for the host `-p` mapping), `--web-port`, and `--set web_password=<token>`. Add
     `--set web_open_browser=false`, after checking that the option exists in the image's mitmweb 12.2.3
     (`docker run --rm --entrypoint mitmweb holon-coherence:latest --options | grep web_`, or the mitmproxy 12 docs). If
     it does not exist, skip it, because a headless container has no browser anyway.
   - **Token banner policy:** inside the container, print
     `🌐 mitmweb inspector listening on container port <web_port> (token: <first 4 chars>…; run 'holon-coherence web-token' on the host for the full URL)`.
     Never print the raw token, because this stdout persists in `docker logs`. Remove the in-container
     `🔑 Web API Key / Password` line.
4. **`ensure_proxy_running()` (line ~508):** append `"--no-web"` after `"--port", "8080"` so `run`/`run-agent`
   background containers stay mitmdump-only as before. Add a code comment explaining why.
5. **`handle_web_token()` (`commands/web_token.py`):** replace the hard-coded `8081` with the running container's mapped
   inspector port via `get_container_mapped_port(name, 8081)` (fetched through `get_cli()` to keep the patching
   convention). Fall back to the current wording when the container is not running. Update the "Start the proxy with
   '--web'" hint to "Start the proxy with 'holon-coherence start' (the inspector is on by default)". Import from
   `docker_ops` lazily inside the function if needed to avoid an import cycle.
6. Keep Dockerfile `CMD ["start", "--port", "8080"]` unchanged. A bare `docker run` would now default to mitmweb with a
   random, persisted-in-container token. That is acceptable and documented, and EXPOSE already lists 8081.

### Dependencies & Criticality

- **Dependencies:** Step 3's helper (implement them together, or stub the call and finish it in Step 3).
- **Is bottleneck:** yes. Steps 3 and 4 depend on the final flag semantics.

### Safety & Constraint Considerations

- **Relevant rules:** intent Q&A (token resolved and persisted exactly as today, authenticated UI, never in wire logs),
  ruleset §2.
- **Failure modes:** the token is missing from the mitmweb argv, which leaves the UI unauthenticated. `--no-web` is not
  propagated into the container. The inspector binds to `0.0.0.0` on the host (it must stay `127.0.0.1:<port>:8081`).
  The fallback loop spins forever (bounded by `find_available_port`'s `max_attempts` plus its OS-assigned fallback).
- **Guardrails:** Tests in Step 4 assert each of these. No changes to `mitm_addon.py` scrubbing.

### Success & Discard Criteria

- **Success:** a plain `holon-coherence start -d` builds a docker command containing `-p 127.0.0.1:8081:8081`,
  `HOLON_COHERENCE_WEB_PASSWORD=<token>` and `--web --web-port 8081`. `--no-web` builds one with none of these plus
  `--no-web`. `run-agent` containers stay headless.
- **Discard:** If `BooleanOptionalAction` conflicts with an existing alias parser or tests, fall back to `--web`
  (`store_true`, kept as a no-op) plus a separate `--no-web` / `--headless` `store_true` that sets `web=False`.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.88  |
| entropy_pred        | 1.20  |
| impact_pred         | 8.50  |
| cost_pred           | 0.50  |
| learning_value_pred | 3.50  |
| ev_pred             | 8.37  |

### Step Metrics Rationale

This is the highest-impact step and carries the most regression risk, because existing tests encode the old default. EV
= 0.88·8.5 + 0.5·3.5 − 0.3·1.2 − 0.5 = 8.37.

## Step 3: Shared endpoint reporting for `start`, `status` and `metrics`

### Step Intent & Git Integration

- **Sub-intent recommendation:** none.
- **Reasoning:** Three commands must print identical, accurate endpoints. One helper avoids drift and keeps the
  `metrics` table convention.
- **Step type:** feature / refactor
- **Exploration level:** 0.0
- **Git branch:** same execution branch.

### Implementation Details

1. New module `src/holon_coherence/commands/endpoints.py` with a module docstring, using only the standard library:
   - `@dataclass(frozen=True) class ExposedEndpoints: proxy_port: int | None; web_port: int | None; web_token: str | None`
   - `def resolve_container_endpoints(container_name: str, fallback_proxy_port: int | None = None) -> ExposedEndpoints`
     uses `get_cli()` lookups of `is_container_running`, `get_container_mapped_port` and `get_active_web_token`, so
     existing patch targets keep working. If the container is not running, it returns `web_port=None`. The proxy port
     comes from `docker port <name> 8080/tcp`, or the fallback. The web port comes from `docker port <name> 8081/tcp`.
   - `def format_endpoint_rows(ep: ExposedEndpoints, label_width: int = 28) -> list[str]` uses the same
     `f"  {label:<{label_width}} : {value}"` shape as `metrics._format_metric_row`. Rows:
     - `Proxy Listen Address` → `127.0.0.1:<proxy_port>`, or `not running`.
     - `Coherence Live Dashboard` → `http://127.0.0.1:<proxy_port>/holon/`, or `not running`.
     - `mitmweb Raw Req/Resp Inspector` → `http://127.0.0.1:<web_port>/?token=<token>` in exactly that form when both
       values are known. When `web_port` is known but the token is not, it prints
       `running on 127.0.0.1:<web_port> (token unavailable; run 'holon-coherence web-token')`. Otherwise it prints
       `not running (headless start or --no-web)`.
   - `def print_endpoints(ep: ExposedEndpoints, header: str = "Exposed Endpoints") -> None` prints a `"-" * 64` rule,
     the header, and the rows.
   - Export the new names through `commands/__init__.py` and `cli.py` `__all__` / imports, following the existing
     re-export pattern, so `holon_coherence.cli.<name>` patches work.
2. **`start`** (host path): call `print_endpoints(...)` after the `🐳 Starting ...` line, using the resolved ports from
   Step 2 rather than a container query, because the container may not be up yet. The `--no-web` case shows the
   inspector as `not running`.
3. **`status`** (`docker_ops.handle_status`, lines ~270-324): replace the ad-hoc `🔑 Web Dashboard Token` /
   `🌐 Access URL` lines and the trailing `🌐 Live Dashboard` line with
   `print_endpoints(resolve_container_endpoints(...))`. Print the block whenever the container is running, independent
   of whether `/holon/api/metrics` answers. Keep the `📊 Optimization Metrics Summary` line as is. When the container is
   down, keep the `🔴 ... is down` line and add a single `mitmweb inspector: not running` line, so no stale token URL
   from `~/.holon/web-token` is printed.
4. **`metrics`** (`commands/metrics.py`): in the table path, replace the closing
   `Live Web Dashboard: http://127.0.0.1:{target_port}/holon/` block with the endpoint rows inside the existing
   `"=" * 64` frame. Resolve the inspector via
   `resolve_container_endpoints(container, fallback_proxy_port=target_port)`, but override `proxy_port` with
   `target_port` so an explicit `--port` is honoured. In the DOWN / UNREACHABLE banner, add
   `mitmweb inspector: not running`. In `--offline` table output, show the endpoints as resolved, which is typically
   `not running`. Leave the `--json` output schema unchanged. This is a deliberate choice so that machine output never
   carries the token. Document it.
5. Australian English throughout, for example "optimisation" in any new strings. Do not rename existing user-visible
   strings that tests depend on, apart from those this plan deliberately changes.

### Dependencies & Criticality

- **Dependencies:** Step 2 (flag semantics and resolved ports).
- **Is bottleneck:** no.

### Safety & Constraint Considerations

- **Relevant rules:** intent goal 3 (exact URL form, explicit "not running", table conventions), the token policy, and
  ruleset §2 (type hints, docstrings).
- **Failure modes:** a stale token URL printed for a stopped container; an import cycle between `docker_ops`, `metrics`
  and `endpoints`; the token leaking into `--json`.
- **Guardrails:** The helper depends only on `_dispatch.get_cli` and lazy lookups. `metrics` already imports from
  `docker_ops`, so `endpoints` imports `docker_ops` and `web_token` but nothing imports `endpoints` back at module level
  except the command modules. Tests in Step 4 assert the stale-URL and JSON behaviour.

### Success & Discard Criteria

- **Success:** All three commands print the three labelled endpoints with resolved ports. A stopped or headless
  container prints `not running` for the inspector.
- **Discard:** If a shared module causes an import cycle that cannot be resolved cleanly, inline `format_endpoint_rows`
  into `docker_ops.py` and import it from there.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.90  |
| entropy_pred        | 1.00  |
| impact_pred         | 8.00  |
| cost_pred           | 0.40  |
| learning_value_pred | 3.00  |
| ev_pred             | 8.00  |

### Step Metrics Rationale

Straightforward formatting work. The risk comes from existing `status` and `metrics` output assertions. EV = 0.90·8.0 +
0.5·3.0 − 0.3·1.0 − 0.4 = 8.00.

## Step 4: Unit tests (hermetic, no Docker)

### Step Intent & Git Integration

- **Sub-intent recommendation:** none.
- **Reasoning:** Intent goal 4 and ruleset §3 require coverage for every new behaviour.
- **Step type:** test
- **Exploration level:** 0.0
- **Git branch:** same execution branch.

### Implementation Details

All tests go in `tests/test_cli.py`, next to the existing `wait_for_proxy_ready` and `start` tests, following their
`patch("holon_coherence.cli....")` and `MagicMock` fake-clock style.

1. **Update existing tests:**
   - `test_wait_for_proxy_ready_timeout`: drive `fake_time.monotonic.side_effect` instead of `.time`. Keep the 3-call
     assertions.
   - Plain `start` tests that inspect `docker_cmd`: patch `save_web_token` (and `resolve_web_password` where determinism
     is needed) so no test writes the real `~/.holon/web-token`. Update assertions that assumed no `:8081` mapping.
   - Port-conflict tests whose `fake_in_use` returns `True` for 8081 now see the inspector fall back too. Adjust the
     expected mappings.
   - Any test asserting the `🔑 Web API Key / Password` or `🌐 Access URL` text in `status` / `web-token` output gets
     updated to the new rows.
2. **New monotonic readiness tests** (Bean 0133). Each patches `holon_coherence.commands.start.time` with a `MagicMock`
   that has separate `wall = [1_000_000.0]` and `mono = [0.0]` lists. `.time` reads `wall` and `.monotonic` reads
   `mono`. `.sleep` advances `mono` by `PROXY_POLL_INTERVAL_SECONDS`, and the test steps `wall` inside the `sleep` or
   `_urlopen_no_proxy` side effects.
   - (a) `test_wait_for_proxy_ready_backwards_wall_step_does_not_extend`: on the first sleep, set `wall -= 3600`. With
     `timeout=1.0` and a refusing endpoint, it returns `False` after exactly `ceil(1.0 / 0.2) = 5` polls. Assert
     `mock_urlopen.call_count == 5`.
   - (b) `test_wait_for_proxy_ready_forwards_wall_step_does_not_short_circuit`: on the first sleep, set `wall += 3600`.
     The poll keeps going for the full monotonic budget (same call count as (a)) rather than exiting after 1 call.
   - (c) `test_wait_for_proxy_ready_returns_on_first_200_despite_wall_steps`: refuse twice, stepping `wall` each time,
     then return a response with `.status == 200`. Assert `True`, `call_count == 3`, and `sleep.call_count == 2`.
   - Also assert `fake_time.time.call_count == 0`, which pins that the function no longer reads wall time.
3. **New mitmweb default tests** (Bean 0129):
   - `test_start_default_selects_mitmweb_and_passes_token`: `main(["start", "-d"])` with `resolve_web_password` patched
     to return `"tok123"` and `save_web_token` patched. Assert `"127.0.0.1:8081:8081"`,
     `"HOLON_COHERENCE_WEB_PASSWORD=tok123"`, `--web` and `--web-port 8081` are in `docker_cmd`, and that
     `save_web_token` was called once with `"tok123"`.
   - `test_start_no_web_selects_mitmdump`: `main(["start", "-d", "--no-web"])`. Assert no `:8081` mapping, no password
     env, `--no-web` in the container args, and `resolve_web_password` / `save_web_token` not called.
   - `test_start_in_container_default_runs_mitmweb_with_password`: patch `is_in_container=True` and `subprocess.run`.
     Assert `cmd[0]` ends with `mitmweb` and contains `--web-host 0.0.0.0`, `--web-port 8081` and
     `--set web_password=tok123`. Also assert that captured stdout does **not** contain `tok123`.
   - `test_start_in_container_no_web_runs_mitmdump`: `cmd[0]` ends with `mitmdump` and has no `web_password`.
   - `test_start_default_inspector_port_falls_back`: `fake_in_use` returns `True` for 8081 only. Expect
     `127.0.0.1:8082:8081` and the inspector URL printed with `8082`.
   - `test_start_inspector_fallback_skips_local_llm_port` (optional but recommended): `--local-llm-base localhost:8082`
     with 8081 busy. The inspector must not land on 8082.
   - `test_ensure_proxy_running_stays_headless`: the background container command contains `--no-web` and no `:8081`
     mapping.
4. **New endpoint output tests:**
   - `test_start_prints_all_endpoints`: capsys contains `127.0.0.1:8080`, `http://127.0.0.1:8080/holon/`, and
     `http://127.0.0.1:8081/?token=tok123` with the inspector label.
   - `test_status_prints_all_endpoints_when_running`: patch `is_container_running=True`, `get_container_mapped_port`
     (8080→8080, 8081→8082), `get_active_web_token="tok"`, and `subprocess.run`. Assert all three rows including
     `http://127.0.0.1:8082/?token=tok`.
   - `test_status_reports_inspector_not_running_without_stale_url`: container down, token file present. The output
     contains `not running` and no `?token=`.
   - `test_status_headless_container_reports_inspector_not_running`: running, but the 8081 mapping is `None`.
   - `test_metrics_table_prints_all_endpoints`: patch `urllib.request.urlopen` to return a minimal empty-counters
     payload (zeros only; transport fixture, no fabricated performance numbers asserted) and the mapped ports and token.
     Assert all three endpoint rows.
   - `test_metrics_json_does_not_include_token`.
   - `test_metrics_down_reports_inspector_not_running`.
   - `test_format_endpoint_rows_alignment`: labels padded to width 28, matching `_format_metric_row`.
5. **Scrub regression** (in `tests/test_mitm_addon.py`): `scrub_string("GET http://127.0.0.1:8081/?token=abcDEF123")` no
   longer contains `abcDEF123`. Also check that the existing scrubbing tests are untouched and passing.
6. Do not add or modify integration tests beyond confirming `tests/test_docker_integration.py`'s `start -d` path stays
   valid with the inspector default, since port fallback covers conflicts. Keep the `integration_test` marker.

### Dependencies & Criticality

- **Dependencies:** Steps 1-3.
- **Is bottleneck:** no.

### Safety & Constraint Considerations

- **Relevant rules:** ruleset §3 (hermetic, deterministic), constraints §4 Rule 1 (no synthetic metrics reporting:
  fixtures exercise formatting only and never feed published numbers).
- **Failure modes:** tests writing the real `~/.holon/web-token` (always patch `save_web_token`); flaky real-socket
  probes (always patch `is_port_in_use`); `MagicMock` comparisons raising `TypeError` on unpatched clock attributes.
- **Guardrails:** each new test patches every external boundary. Run the new tests in isolation and with
  `-p no:randomly` and default ordering.

### Success & Discard Criteria

- **Success:** All new and existing non-integration tests pass, and each intent goal 4 bullet maps to at least one test.
- **Discard:** none. Tests are mandatory. If a test is hard to make deterministic, simplify its scenario rather than
  drop it.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.92  |
| entropy_pred        | 0.90  |
| impact_pred         | 7.50  |
| cost_pred           | 0.40  |
| learning_value_pred | 2.50  |
| ev_pred             | 7.48  |

### Step Metrics Rationale

The test patterns already exist in the file. Most effort goes into updating legacy assertions. EV = 0.92·7.5 + 0.5·2.5 −
0.3·0.9 − 0.4 = 7.48.

## Step 5: Documentation

### Step Intent & Git Integration

- **Sub-intent recommendation:** none.
- **Reasoning:** Intent goal 5.
- **Step type:** docs
- **Exploration level:** 0.0
- **Git branch:** same execution branch.

### Implementation Details

1. **README.md** (around lines 169-190, 360-361 and 430):
   - In the CLI quick-start, show that `holon-coherence start` now exposes the inspector by default, and
     `holon-coherence start --no-web` for headless use. Keep `--web-password` and `web-token` examples, and note that
     `--web` is still accepted.
   - Add a short "Inspecting live traffic with mitmweb" subsection covering:
     - Opening the printed `http://127.0.0.1:<web_port>/?token=<token>` URL.
     - What it shows: request method, URL, headers, request body, response status code and body, cache status (the
       `X-Holon-Cache`-style response headers or flow markers the addon sets; use the actual header names after checking
       `mitm_addon.py`), and TLS details (the Connection / server certificate tabs).
     - Token resolution order: `--web-password`, then `HOLON_COHERENCE_WEB_PASSWORD`, then an auto-generated
       `secrets.token_urlsafe(16)`. It is persisted to `~/.holon/web-token` with mode 0600 and printed by `start`,
       `status`, `metrics` (table) and `web-token`, but never in `--json` output, container logs or wire logs.
     - A security note: the inspector shows raw, unscrubbed traffic including credentials, is bound to `127.0.0.1` only,
       and wire-log scrubbing is unaffected.
     - Port reporting: the default is 8081 with a fallback to the next free port that also avoids the proxy and
       `--local-llm-base` ports, and the resolved ports appear in the endpoint block. Include a sample block.
   - Update the 360-361 note: the inspector is now on by default, so either use `--no-web`, a different `--web-port`, or
     rely on the automatic fallback.
2. **`docs/running_mitm_sidecar_guide.md`** (lines ~34-63): rewrite the "enable the web dashboard" section to cover the
   default-on inspector, the opt-out and the endpoint block. Keep the direct `docker run` instructions and tip.
3. **`docs/token_reduction_measurement_plan.md`** (line ~336): adjust the mitmweb note only if it implies `--web` is
   required.
4. Australian English throughout. Do not modify historical plan files or the ledger.

### Dependencies & Criticality

- **Dependencies:** Steps 2-3, so the documented flags and labels match the code.
- **Is bottleneck:** no.

### Safety & Constraint Considerations

- **Relevant rules:** markdown formatted only with the repository's own Prettier invocation (`--no-config`).
- **Failure modes:** documenting header names or labels that do not match the code; docs that show a real token.
- **Guardrails:** grep the final code for the exact labels and copy them. Use a placeholder `<token>` in examples.

### Success & Discard Criteria

- **Success:** Every goal-5 topic is covered and `make lint-md` (Prettier check) passes on the changed files.
- **Discard:** none.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.95  |
| entropy_pred        | 0.50  |
| impact_pred         | 5.00  |
| cost_pred           | 0.20  |
| learning_value_pred | 1.50  |
| ev_pred             | 5.15  |

### Step Metrics Rationale

Low-risk prose changes. EV = 0.95·5.0 + 0.5·1.5 − 0.3·0.5 − 0.2 = 5.15.

## Step 6: Quality gates and commit

### Step Intent & Git Integration

- **Sub-intent recommendation:** none.
- **Reasoning:** Intent goal 6. These are the acceptance gates.
- **Step type:** verification
- **Exploration level:** 0.0
- **Git branch:** same execution branch, squashed into a single logical commit (constraints §1.2).

### Implementation Details

1. `uv run ruff format .` on the changed Python files, then `uv run ruff check .` with zero errors.
2. `make lint` with zero errors, including `ruff format --check` and the Prettier JSON/YAML/MD checks when `npx` is
   available. If Prettier flags changed markdown, run `npx prettier --no-config --write <changed .md files>` (the same
   configuration the Makefile uses). Never reformat unrelated files.
3. `uv run pytest -m "not integration_test"` with zero failures. Also run `uv run pytest` to confirm integration tests
   still skip or deselect cleanly without Docker.
4. Run `grep -rn "time\.time()" src/holon_coherence` and attach the audit table to the execution report. Run
   `grep -rn "Web API Key" src` to confirm the old token banner was removed from the in-container path.
5. Spelling sweep of the changed lines (`git diff | grep -iE "optimiz|behavior|initializ|color"`). Fix new US spellings
   and leave untouched pre-existing identifiers alone.
6. Squash-commit with a message referencing Beans 0129 and 0133, ending with the required
   `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` attribution line. Do not push to `main`.

### Dependencies & Criticality

- **Dependencies:** Steps 1-5.
- **Is bottleneck:** yes (final gate).

### Safety & Constraint Considerations

- **Relevant rules:** ruleset §1 (`uv run` only), §2.4, §3.2; constraints §1.
- **Failure modes:** a Prettier version mismatch rewriting unrelated files; a missing `npx` making `lint-md` skip (that
  is acceptable and should be reported as skipped, not as passed).
- **Guardrails:** Format only the files changed in this plan and report any skipped linters honestly.

### Success & Discard Criteria

- **Success:** All three commands exit 0 and a single squashed commit is on the execution branch.
- **Discard:** none. Loop back to the failing step.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.93  |
| entropy_pred        | 0.30  |
| impact_pred         | 6.00  |
| cost_pred           | 0.15  |
| learning_value_pred | 1.00  |
| ev_pred             | 5.84  |

### Step Metrics Rationale

This step is deterministic verification, and its probability reflects residual lint and format churn. EV = 0.93·6.0 +
0.5·1.0 − 0.3·0.3 − 0.15 = 5.84.
