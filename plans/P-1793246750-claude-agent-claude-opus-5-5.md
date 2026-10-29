# Plan for I-1793246735-coherence-remove-harness-path-and-task-id-leaks

- **Plan ID:** P-1793246750-claude-agent-claude-opus-5-5
- **Parent Intent ID:** NONE
- **Agent:** claude-agent (version: 2.1.302)
- **Created At:** 2026-10-29T04:05:51.399Z

## Overall Plan Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.86  |
| entropy_pred        | 6.0   |
| impact_pred         | 0.72  |
| cost_pred           | 0.18  |
| learning_value_pred | 0.35  |
| ev_pred             | 0.41  |

### Strategy Rationale

`EV = P(success) * Impact + mu * LearningValue - lambda * Delta_S_intent - Cost`, with lambda = 0.3 and mu = 0.5.

- `P(success) * Impact = 0.86 * 0.72 = 0.619`
- `mu * LearningValue = 0.5 * 0.35 = 0.175`
- `Delta_S_intent` is the predicted plan entropy normalised by the allocated budget: `6.0 / 9.0 = 0.667`, so
  `lambda * Delta_S_intent = 0.3 * 0.667 = 0.200`
- `Cost = 0.18`
- `EV = 0.619 + 0.175 - 0.200 - 0.180 = 0.414 ≈ 0.41`

**P(success) = 0.86.** The change is mostly mechanical text edits with a clear inventory, which was produced during
planning with `git grep` (see "Pre-planning inventory" below). The main risks are a missed occurrence the hygiene test
then catches (self-correcting: the new test fails, the executor fixes it), a too-broad "absolute harness path" regex that
rejects legitimate container paths such as `/home/mitmproxy/.mitmproxy` (already found in README.md and
docs/running_mitm_sidecar_guide.md, both off-limits), and Prettier reflowing long Markdown tables in docs/audit_report.md.

**Impact = 0.72.** It removes a runtime default that writes into a harness-owned directory, removes dead links and
absolute machine paths from shipped docs, and adds a permanent guard against reintroduction. It is hygiene, not a
feature, so impact is capped below 0.8.

**Cost = 0.18.** About 15 files are edited, almost all docs and docstrings. Only two lines of runtime behaviour change.

**Learning value = 0.35.** Moderate. Writing a self-excluding pattern test and an exact directory-name matcher is
reusable knowledge for sibling repositories.

### Pre-planning inventory (from `git grep` at commit 2940352)

- Runtime defaults: `src/holon_coherence/mitm_addon.py:80`, `src/holon_coherence/commands/metrics.py:33` and
  `:308`.
- `.gitignore:36` contains `todo/`. `.holon/` is already ignored (last lines of the file). `cache/` and
  `mitm_wire_logs/` stay.
- todo paths in docs: `docs/methods/{README,context_cleaning,local_cache_layer,openbrain_memory,prompt_cache_optimization,rag_codebase_indexer,ringer_framework}.md`,
  `docs/token_reduction_{ab_testing,measurement_plan,plan}.md` and `docs/mitm_telemetry_metrics_plan.md`.
  `docs/token_reduction_plan.md:156-164` is not in the intent's description, but it matches the `docs/token_reduction_*.md`
  touch-set glob and has to be fixed or the hygiene test fails.
- Absolute machine paths: `docs/mitm_telemetry_metrics_plan.md:6,99,101` and `docs/audit_report.md:144`, which quotes
  the leaked path as part of a finding.
- Task ids: every location listed in the intent, plus `docs/audit_report.md:4` ("Parent Bean"), the mermaid graph at
  `:482-486`, the candidate headings at `:489-533`, the table at `:551-554` and the section title "Status of Addressed
  Beans" (`:547`).
- No tracked file lives under `todo/`, `.subagent/` or `.beans/`. `.agents/AGENTS.md` is tracked but contains none of the
  forbidden patterns.
- Legitimate absolute paths outside the touch set (`/home/mitmproxy/.mitmproxy` in README.md,
  docs/running_mitm_sidecar_guide.md and others) must not be rejected by the hygiene test.
- `tests/test_cli.py:2754` (`test_handle_metrics_offline_fallback_holon_logs`) relies on the cwd-relative default not
  existing. With the new default `.holon/mitm_wire_logs`, a developer's real local logs under the repository root would
  shadow the fixture, so the test must `monkeypatch.chdir(tmp_path)`.

## Planner Autonomy Summary

- **Intent handling:** `ACCEPT_AS_IS`
- **Reframed intent (if applicable):** NONE
- **Exploration stance:** Strong exploitation. The leak inventory is complete and deterministic from `git grep`, and the
  target state is fully specified. The only exploratory work is re-running the inventory in the fresh worktree and
  deciding the exact regexes for "absolute path into a harness checkout" so that they reject the leaked
  `file:///Users/<user>/git/...` form without rejecting container paths.
- **Safety priority level:** elevated
- **Priority Justification:** Runtime code (the wire-log default) changes, the touch set is strict because concurrent
  changes own neighbouring files, and the new test runs in the shared unit job. A false-positive pattern would break CI
  for every concurrent change. The work is not security-critical, so elevated rather than strict.

## Exploration

- **Proportion of steps that are exploratory:** 0.11
- **Justification:** One of nine steps (Step 1: worktree setup and inventory confirmation) is exploratory. Everything
  else is exploitation of a known inventory. More exploration would add cost without reducing risk, because the
  hygiene test itself is the final oracle for completeness.

## Safety & Constraint Alignment

- **Key world ruleset constraints that affect this plan:**
  - AGENTS.md: work in a dedicated worktree off `origin/main`, squash to a single commit, never push without
    instruction, run tests via `uv run pytest` from the worktree root, run Prettier on Markdown and ruff on Python.
  - Behavioural invariant 1 (no synthetic data for benchmarking): the docs rewrite must not invent benchmark scripts or
    numbers. Where a referenced harness script does not exist, the doc describes the measurement against real wire logs
    instead.
  - Intent constraints: Australian English; no new dependencies; short, low-branching functions; strict touch set; no
    harness directory names or task ids in written files; ledgers append-only; `uv run task lint` and
    `npx prettier --check` on changed Markdown must pass.
- **Potential violations or edge cases:**
  1. The hygiene test file must reference `todo/`, `.subagent/`, `.beans/` and the `Bean` + digits pattern, which would
     both match itself and break the "never reference harness directories" rule.
  2. Regex over-matching: `todo/` could match words like `autotodo/`; `.beans/` must not match `.beads/`; and an
     absolute-path pattern could match `/home/mitmproxy/...`.
  3. Under-matching: `Bean 0045`, `Bean0045` and `Bean-0045` variants.
  4. Binary tracked files (none at present, but possible later) could crash a text read.
  5. Doc rewrites could need a file outside the touch set (for example README.md also documents wire logs).
  6. Prettier reflow of the audit-report table could create a large diff.
  7. `test_handle_metrics_offline_fallback_holon_logs` could become environment-dependent with the new cwd-relative
     default.
  8. Doc commands using `python3 -m unittest` would name a non-pytest runner.
- **Mitigations built into the plan:**
  1. Assemble forbidden tokens from fragments at import time, for example `"to" + "do"` and `"." + "be" + "ans"`, and
     build the id regex as `"Be" + "an" + r"[ _-]?\d{4}\b"`. Neither literal appears in the file, so no self-exclusion
     is needed.
  2. Anchor directory matches on a path boundary (`(?<![\w.-])todo/` and `(?<![\w-])\.beans/`). Check tracked paths by
     comparing the first path component exactly (`path.split("/", 1)[0] in FORBIDDEN_DIRS`). Add explicit parametrised
     negative tests for `.beads/`, `.beads/x.md` and a file containing `.beads/` text.
  3. Define the harness-checkout pattern narrowly: `/(?:Users|home)/[^/\s]+/git/` and the harness repository name
     fragment (`"holon-agentic-" + "coder-ref"`). Add a negative test proving `/home/mitmproxy/.mitmproxy` passes.
  4. Read files as bytes and decode with `errors="ignore"`. Skip files containing NUL bytes.
  5. Any needed file outside the touch set is dropped and reported in the execution notes, not edited.
  6. Run `npx prettier --write` only on changed Markdown files, then `--check`.
  7. Add `monkeypatch.chdir(tmp_path)` to that test.
  8. Replace with `uv run pytest <path>`.
- **Residual risk accepted (and why):** The hygiene patterns are heuristic. A future leak in a novel form (for example a
  different tracker prefix) will not be caught. This is accepted because the intent defines the exact pattern set and
  wider patterns would raise false-positive risk in a shared CI job. Users with existing logs in the old directory must
  move them or set `WIRE_LOG_DIR`. This is documented in the migration note.
- **Allocated Entropy Budget:** 9.0
- **Predicted Plan Entropy:** 6.0 (0.3 + 0.9 + 0.2 + 0.8 + 1.0 + 1.0 + 0.5 + 0.9 + 0.4)
- **Budget Compliance:** 6.0 ≤ 9.0, which leaves 3.0 of headroom for re-work found by the hygiene test.

## Plan Description & Strategy

1. Create the worktree off `origin/main`, sync `.venv` and re-run the leak inventory to confirm the baseline.
2. Change the wire-log default to `.holon/mitm_wire_logs` in `mitm_addon.py` and `commands/metrics.py`, replace the
   offline search candidate and isolate the affected CLI test.
3. Remove `todo/` from `.gitignore`.
4. Replace task ids in source and test docstrings and comments with plain behaviour descriptions.
5. Rewrite `docs/methods/*.md` to use target-native paths and describe missing benchmark scripts as measurements.
6. Rewrite `docs/token_reduction_*.md` and `docs/mitm_telemetry_metrics_plan.md`: target-native paths, no absolute
   paths, no task ids, and the wire-log migration note.
7. Strip external ids from `docs/audit_report.md` while keeping every finding.
8. Add `tests/test_repo_hygiene.py` with the leak guard and the `.beads/` negative proof.
9. Verify with `git grep`, `uv run task test`, `uv run task lint` and `npx prettier --check`, then squash into a single
   commit (no push).

---

## Step 1: Worktree setup and baseline inventory

### Step Intent & Git Integration

- **Sub-intent recommendation:** none (part of this intent)
- **Reasoning:** AGENTS.md forbids edits on the main worktree, and a fresh inventory protects against drift since
  planning.
- **Step type:** setup / exploration
- **Exploration level:** exploratory (low)
- **Git branch:** `feat/coherence-remove-harness-path-and-task-id-leaks`, in worktree
  `../feat-coherence-remove-harness-path-and-task-id-leaks`

### Implementation Details

```bash
git fetch origin main
git worktree add --no-track -b feat/coherence-remove-harness-path-and-task-id-leaks \
  ../feat-coherence-remove-harness-path-and-task-id-leaks origin/main
cd ../feat-coherence-remove-harness-path-and-task-id-leaks
uv sync
uv run task test   # baseline must be green before changes
git grep -nE 'todo/|Bean[ _-]?[0-9]{4}|\.subagent/|\.beans/|file:///|/Users/' \
  -- ':!holon-knowledge/ledger' ':!plans' ':!executions' ':!intents'
```

Compare the output with the inventory in this plan. Record any new hits and add them to Steps 4-7 if they are inside the
touch set. If they are outside it, report them in the execution notes. They would make the hygiene test fail, so the
step that adds the test must then be reported as blocked.

### Dependencies & Criticality

- **Dependencies:** none
- **Is bottleneck:** yes (everything depends on the worktree)

### Safety & Constraint Considerations

- **Relevant rules:** worktree isolation; `.venv` only at the worktree root.
- **Failure modes:** a pre-existing red test suite.
- **Guardrails:** if the baseline fails, record the failing tests and continue only if they are unrelated to the touch
  set.

### Success & Discard Criteria

- **Success:** worktree exists, baseline tests are green and the inventory is confirmed.
- **Discard:** `origin/main` is unreachable. Stop and report.

### Step Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.98  |
| entropy_pred        | 0.3   |
| impact_pred         | 0.10  |
| cost_pred           | 0.02  |
| learning_value_pred | 0.15  |

**Step Metrics Rationale:** These are routine commands. The learning value comes only from confirming the inventory.

---

## Step 2: Change the wire-log default to `.holon/mitm_wire_logs`

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** This is the only runtime behaviour change. Isolating it keeps review focused.
- **Step type:** implementation (code + test)
- **Exploration level:** exploitation
- **Git branch:** same worktree branch

### Implementation Details

- `src/holon_coherence/mitm_addon.py:80`:
  `WIRE_LOG_DIR = os.getenv("WIRE_LOG_DIR", DEFAULT_WIRE_LOG_DIR)`, with a module constant
  `DEFAULT_WIRE_LOG_DIR = ".holon/mitm_wire_logs"` defined just above. The override semantics stay byte-for-byte the
  same (`os.getenv` with the same variable name).
- `src/holon_coherence/commands/metrics.py:33`: the same pattern with its own `DEFAULT_WIRE_LOG_DIR` constant. Do not
  import from `mitm_addon`, so that the CLI does not load mitmproxy-heavy imports.
- `commands/metrics.py:308`: `candidate_dirs.append(DEFAULT_WIRE_LOG_DIR)`. The order (env override, default,
  `~/.holon/logs`) and the de-duplication stay unchanged.
- Check whether the log writer creates the directory with `os.makedirs(..., exist_ok=True)`. If it already does, no
  change is needed. If it does not, add `exist_ok` creation where the writer already prepares the directory, without
  adding branches. `.holon/` is nested, so creating the parent is required.
- `tests/test_cli.py` `test_handle_metrics_offline_fallback_holon_logs`: add `monkeypatch.chdir(tmp_path)` so that a
  developer's real `.holon/mitm_wire_logs` cannot shadow the fixture.
- Add focused tests in `tests/test_cli.py` (metrics area) and `tests/test_mitm_addon.py`:
  - With `WIRE_LOG_DIR` unset, `importlib.reload` of the module gives `.holon/mitm_wire_logs`.
  - With `WIRE_LOG_DIR` set, the override wins. Restore the module state in teardown with `monkeypatch` and reload.
  - Offline fallback reads `transactions.jsonl` from `tmp_path/.holon/mitm_wire_logs` after `chdir(tmp_path)`. The
    fixture rows reuse the existing captured-record shape already in `test_cli.py`. These are unit fixtures for the
    parser, not benchmark data, so invariant 1 is respected.

### Dependencies & Criticality

- **Dependencies:** Step 1
- **Is bottleneck:** no

### Safety & Constraint Considerations

- **Relevant rules:** keep the `WIRE_LOG_DIR` override exactly as it is; short, low-branching functions; Australian
  English in any comment.
- **Failure modes:** module reload leaking state into other tests; a Docker image or Makefile that hard-codes
  `todo/mitm_wire_logs` (both off-limits).
- **Guardrails:** `git grep -n 'mitm_wire_logs' -- Makefile Dockerfile config .github`. If there are hits there, report
  them in the execution notes and do not edit them.

### Success & Discard Criteria

- **Success:** the new tests pass, the existing metrics tests pass and the default string appears only as the new
  constant.
- **Discard:** if a reload-based test proves flaky, replace it with an assertion against `DEFAULT_WIRE_LOG_DIR` plus a
  subprocess-free `os.getenv` check.

### Step Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.92  |
| entropy_pred        | 0.9   |
| impact_pred         | 0.30  |
| cost_pred           | 0.04  |
| learning_value_pred | 0.10  |

**Step Metrics Rationale:** The code change is small. Most of the entropy comes from the test isolation (module reload
and cwd).

---

## Step 3: Remove `todo/` from `.gitignore`

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** The ignore rule implies that the harness directory belongs to this repository.
- **Step type:** configuration
- **Exploration level:** exploitation
- **Git branch:** same

### Implementation Details

Delete only line 36 (`todo/`) under `# Local cache & logs`. Keep `cache/`, `*.db*`, `mitm_wire_logs/`,
`transactions.jsonl`, `turn_*.json`, `.holon-cache/`, `.holon/` and `.holon`. Confirm with
`git check-ignore -v .holon/mitm_wire_logs/transactions.jsonl`.

### Dependencies & Criticality

- **Dependencies:** Step 1
- **Is bottleneck:** no

### Safety & Constraint Considerations

- **Relevant rules:** keep the cache, wire-log and `.holon/` entries.
- **Failure modes:** a local untracked `todo/` directory becomes visible in `git status`.
- **Guardrails:** never `git add -A`. Stage explicit paths only, so that a harness `todo/` directory in a developer
  checkout is never committed. The hygiene test also catches this.

### Success & Discard Criteria

- **Success:** `git diff .gitignore` shows a single removed line, and `check-ignore` confirms that `.holon/` coverage
  remains.
- **Discard:** none expected.

### Step Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.99  |
| entropy_pred        | 0.2   |
| impact_pred         | 0.05  |
| cost_pred           | 0.01  |
| learning_value_pred | 0.02  |

**Step Metrics Rationale:** This is a one-line deletion.

---

## Step 4: Replace task ids in source and test files

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Docstrings and comments must describe behaviour, not an external tracker.
- **Step type:** refactor (comments and docstrings only)
- **Exploration level:** exploitation
- **Git branch:** same

### Implementation Details

Edit each occurrence and drop the parenthetical id. Where the id carried meaning, replace it with a phrase:

| Location                                  | Replacement guidance                                                                                       |
| :---------------------------------------- | :--------------------------------------------------------------------------------------------------------- |
| `mitm_addon.py:383`, `:558`, `:2211`      | "... where `None` means _not measured_." / "... prefill readings of 0.00 tokens/sec." (drop id)            |
| `mitm_addon.py:490`, `:1119`              | drop "(Bean 0043)"                                                                                         |
| `mitm_addon.py:2005`, `:2020`             | `# Gemini v1beta bridge to OpenAI ...` / `# Strict Anthropic normaliser for host-local engines` (en-AU)    |
| `commands/metrics.py:1`, `:150`           | drop the id; ":150" becomes "Records written with measured timings and ..."                                |
| `commands/endpoints.py:1`, `start.py:111` | drop "(Bean 0129)"                                                                                         |
| `metrics_math.py:1`                       | drop "(Bean 0097)"                                                                                         |
| `tests/test_ab_testing.py:1`              | drop the id                                                                                                |
| `tests/test_cli.py:2490,2650,2859,2920`   | drop the id                                                                                                |
| `tests/test_cli.py:2889`                  | `# Local LLM runner sets AGY_GATEWAY_URL ...`                                                              |
| `tests/test_host_local.py:165`            | `"""The container-side decision table."""`                                                                 |
| `tests/test_hybrid_cache.py:1`            | drop the id                                                                                                |
| `tests/test_makefile.py:857`              | `# Dry-run detector` (the trailing "review" referred to an external review id, so drop it with the id)     |
| `tests/test_mitm_addon.py` (7 lines)      | drop ids; line 877 becomes "An inspector URL that ever lands in a logged request or response is redacted." |
| `tests/test_mitm_addon_sse.py:1`          | drop the id                                                                                                |

Do not touch any existing American spelling outside the edited line unless it is on the same line being rewritten (for
example "normalizer" becomes "normaliser"). Keep diffs minimal. Afterwards:
`git grep -nE 'Bean[ _-]?[0-9]{4}' -- src tests` must be empty. Then run `uv run ruff format .` and
`uv run ruff check .`.

### Dependencies & Criticality

- **Dependencies:** Step 1
- **Is bottleneck:** no

### Safety & Constraint Considerations

- **Relevant rules:** behaviour unchanged; Australian English.
- **Failure modes:** accidentally editing string literals that are asserted by tests. None of the listed lines are
  literals, but check by running the tests.
- **Guardrails:** `git diff --stat` must show changes only in the listed files. `git diff -U0 | grep '^[-+][^-+]'`
  must contain only comment and docstring lines.

### Success & Discard Criteria

- **Success:** no ids remain in `src/` or `tests/`, and the tests and lint are green.
- **Discard:** none.

### Step Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.97  |
| entropy_pred        | 0.8   |
| impact_pred         | 0.10  |
| cost_pred           | 0.03  |
| learning_value_pred | 0.03  |

**Step Metrics Rationale:** There are many small mechanical edits. The entropy comes from the number of files, not from
difficulty.

---

## Step 5: Rewrite `docs/methods/*.md` with target-native paths

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** The method guides currently tell users to run harness scripts that this repository does not ship.
- **Step type:** documentation
- **Exploration level:** exploitation
- **Git branch:** same

### Implementation Details

Path mapping (runtime data goes under `.holon/`, relative to the repository root):

- `todo/mitm_wire_logs` → `.holon/mitm_wire_logs`
- `todo/cache` → `.holon/cache`
- `todo/openbrain` → `.holon/openbrain`
- `todo/artifacts/<x>` → `.holon/artifacts/<x>`
- `todo/scorecard_report.md` → `.holon/scorecard_report.md`

Per file:

- `README.md:27-35`: replace "script located in `todo/` … `python3 todo/ab_measure_all_methods.py`" with a description
  of the measurement. Each method is evaluated by running a real agent session through the proxy
  (`holon-coherence run -- <cmd>` or `holon-coherence <agent>`), once with the method enabled and once disabled. Turn
  telemetry is then read from `.holon/mitm_wire_logs/transactions.jsonl`, and live totals come from
  `holon-coherence metrics --json`. If `holon-coherence ab-test --help` (shipped in `commands/ab_test.py`) covers
  trace-based comparison, reference it by its real CLI name. Otherwise do not link a command.
- `context_cleaning.md`, `openbrain_memory.md`, `prompt_cache_optimization.md`, `rag_codebase_indexer.md` and
  `ringer_framework.md` "Unified Benchmark Harness" table rows: change the file cell to
  "A/B measurement on captured wire logs (see [README](README.md))". Keep the measurement column.
- `context_cleaning.md:104,120,121,280,284,299`, `local_cache_layer.md:29,52,85,153,176,179,216`,
  `openbrain_memory.md:32,53,70,159` and `prompt_cache_optimization.md:186,190`: apply the path mapping. Change
  "Initialize" to "Initialise" on any rewritten line.
- `openbrain_memory.md:140,146` and `ringer_framework.md:85-86,119-148,216`: apply the path mapping in prompts. Replace
  `python3 -m unittest todo/artifacts/generate_website/test_dashboard.py` with
  `DASHBOARD_DIR=.holon/artifacts/generate_website uv run pytest .holon/artifacts/generate_website/test_dashboard.py`.
- Add a one-line note where `.holon/mitm_wire_logs` first appears in `context_cleaning.md`: logs from older versions
  live in the previous default directory, so move them to `.holon/mitm_wire_logs` or point `WIRE_LOG_DIR` at the old
  location. Word this without spelling out the old path, because target files must not reference harness directories.
  For example: "Earlier releases wrote wire logs to a different default directory. Move those files into
  `.holon/mitm_wire_logs`, or set `WIRE_LOG_DIR` to their location to keep reading them."
- Run `npx prettier --write docs/methods/*.md`, then `--check`.

### Dependencies & Criticality

- **Dependencies:** Step 2 (the default path must match the docs)
- **Is bottleneck:** no

### Safety & Constraint Considerations

- **Relevant rules:** invariant 1 (no invented benchmark numbers or scripts); `uv run pytest` for test commands; en-AU.
- **Failure modes:** dangling relative links; Prettier table reflow.
- **Guardrails:** `git grep -n 'todo/' docs/methods` must be empty. Manually check that every relative link target
  exists (`ls` each linked path).

### Success & Discard Criteria

- **Success:** no `todo/` in docs/methods, Prettier check passes and every link resolves.
- **Discard:** none.

### Step Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.93  |
| entropy_pred        | 1.0   |
| impact_pred         | 0.20  |
| cost_pred           | 0.04  |
| learning_value_pred | 0.05  |

**Step Metrics Rationale:** There are seven files with prose judgement calls about how to describe measurements instead
of linking scripts.

---

## Step 6: Rewrite `docs/token_reduction_*.md` and `docs/mitm_telemetry_metrics_plan.md`

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** These docs contain the bulk of the harness script references and all of the absolute machine paths.
- **Step type:** documentation
- **Exploration level:** exploitation
- **Git branch:** same

### Implementation Details

- `docs/token_reduction_ab_testing.md:78-111`: remove the `uv run python ../../todo/ab_benchmark_*.py` commands. Replace
  them with a description of each tier's measurement: live API comparison through the proxy using
  `holon-coherence run -- <cmd>` with optimisation on and off, and end-to-end agent comparison via
  `holon-coherence <agent>`. Results are read from `.holon/mitm_wire_logs/transactions.jsonl` and
  `holon-coherence metrics --json`. The "outputs … into the `todo/` directory" sentence becomes "into
  `.holon/mitm_wire_logs`". The mock-API tier (`ab_benchmark_mock_api.py`) conflicts with invariant 1, so describe it
  only as an offline parser smoke check that is not used for efficacy figures.
- `docs/token_reduction_plan.md:156-164`: replace script filenames in the tier headings with plain tier descriptions.
- `docs/token_reduction_measurement_plan.md`: apply the path mapping on lines 85-301 and 765-968. In the code sample on
  line 96, show `".holon/mitm_wire_logs"`. On lines 99-101, say that the default is `.holon/mitm_wire_logs/` and that
  it is ignored through the `.holon/` entry in `.gitignore`. Add the migration note from Step 5 in the "Structured Wire
  Logger" section. In the Gantt task on line 926, change "script in todo/" to "measurement on captured wire logs". On
  line 968, change the step heading to "Implement A/B measurement over captured wire logs".
- `docs/mitm_telemetry_metrics_plan.md`:
  - Line 6: replace the absolute link with
    [`src/holon_coherence/mitm_addon.py`](../src/holon_coherence/mitm_addon.py).
  - Line 78: change the callout to `> [!IMPORTANT] Each timing/throughput header ...` (drop the id).
  - Lines 99-109: remove both absolute links and the `todo/ab_*` result files. Describe recording prefill and output TPS
    from `X-Holon-*` headers and `.holon/mitm_wire_logs/transactions.jsonl` (inspected with
    `holon-coherence metrics --json`). Replace "for all live network tests in `todo/`" with "for all live network
    tests".
- Run `npx prettier --write` on the changed files, then `--check`.

### Dependencies & Criticality

- **Dependencies:** Step 2
- **Is bottleneck:** no

### Safety & Constraint Considerations

- **Relevant rules:** invariant 1; no absolute paths; en-AU; no harness names (the harness repository name must
  disappear with the links).
- **Failure modes:** the measurement plan is long (about 970 lines), so an occurrence is easy to miss.
- **Guardrails:** run
  `git grep -nE 'todo/|file:///|/Users/|Bean[ _-]?[0-9]{4}' -- docs/token_reduction_*.md docs/mitm_telemetry_metrics_plan.md`
  and require it to be empty. Step 8's test is the final guard.

### Success & Discard Criteria

- **Success:** the grep is empty, Prettier passes and the relative link resolves.
- **Discard:** none.

### Step Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.92  |
| entropy_pred        | 1.0   |
| impact_pred         | 0.20  |
| cost_pred           | 0.04  |
| learning_value_pred | 0.05  |

**Step Metrics Rationale:** This is the largest prose rewrite. Rewording the mock tier needs care to stay within
invariant 1.

---

## Step 7: Strip external ids from `docs/audit_report.md`

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** The audit findings are valuable. Only the tracker ids leak.
- **Step type:** documentation
- **Exploration level:** exploitation
- **Git branch:** same

### Implementation Details

- Line 4: change `- **Parent Bean:** Bean 0045 (...)` to `- **Scope:** Comprehensive Architecture, Security, and
Quality Audit`.
- Line 144: keep the finding but replace the quoted path with "an absolute local user-home file URL into an external
  checkout". This finding is resolved by Step 6, so optionally append "(resolved: links are now
  repository-relative)".
- Mermaid graph, lines 482-486: keep the node ids (`Audit`, `B46` to `B50` are internal identifiers that do not match
  the pattern, but rename them to `F1` to `F5` for clarity). Labels become `"Audit Report"`,
  `"Security & File Permission Hardening"` and so on.
- Headings at 489-533: `### Candidate Follow-up: <title>`.
- Section 7.1: retitle it "Status of Addressed Remediations". Drop the first table column (the ids). Keep the domain,
  status and achievements. Re-run Prettier on the file.
- Afterwards: `git grep -nE 'Bean|file:///' docs/audit_report.md` must be empty.

### Dependencies & Criticality

- **Dependencies:** Step 6 (line 144 references its fix)
- **Is bottleneck:** no

### Safety & Constraint Considerations

- **Relevant rules:** keep the findings; en-AU.
- **Failure modes:** the mermaid syntax breaks after relabelling.
- **Guardrails:** keep the edge syntax identical and change only the bracketed labels and node ids.

### Success & Discard Criteria

- **Success:** no ids, the finding count is unchanged (count `### ` headings before and after) and Prettier passes.
- **Discard:** none.

### Step Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.96  |
| entropy_pred        | 0.5   |
| impact_pred         | 0.07  |
| cost_pred           | 0.02  |
| learning_value_pred | 0.02  |

**Step Metrics Rationale:** One file with known edits. The table reflow is the only uncertainty.

---

## Step 8: Add `tests/test_repo_hygiene.py`

### Step Intent & Git Integration

- **Sub-intent recommendation:** none (the intent's Q&A requires it to land together with the removals)
- **Reasoning:** This prevents regressions. It runs in the existing unit job with no workflow change.
- **Step type:** test implementation
- **Exploration level:** exploitation (regex design is bounded by the mitigations above)
- **Git branch:** same

### Implementation Details

Structure (pytest only, standard library only, short functions):

```python
"""Repository hygiene: tracked files must not depend on an external harness."""

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
# Fragments are joined so that this file never matches its own patterns.
FORBIDDEN_DIRS = frozenset({"to" + "do", "." + "sub" + "agent", "." + "be" + "ans"})
PROVENANCE_PREFIXES = ("holon-knowledge/ledger/", "plans/", "executions/", "intents/")
ALLOWED_FILES = frozenset({"." + "agents/AGENTS.md"})
CONTENT_PATTERNS = (
    re.compile(r"(?<![\w.-])" + "to" + r"do/"),
    re.compile(r"(?<![\w-])\." + "sub" + r"agent/"),
    re.compile(r"(?<![\w-])\." + "be" + r"ans/"),
    re.compile(r"/(?:Users|home)/[^/\s]+/git/"),
    re.compile("holon-agentic-" + "coder-ref"),
    re.compile("Be" + "an" + r"[ _-]?\d{4}\b"),
)


def tracked_files() -> list[str]: ...  # git ls-files -z, cwd=REPO_ROOT
def forbidden_dir(path: str) -> bool: ...  # path.split("/", 1)[0] in FORBIDDEN_DIRS
def is_exempt(path: str) -> bool: ...  # provenance prefix or ALLOWED_FILES
def leaks_in(text: str) -> list[str]: ...  # pattern.pattern for each match
def read_text(path: str) -> str | None: ...  # bytes; None if NUL present; decode errors="ignore"


def test_no_tracked_file_under_forbidden_dir(): ...
def test_no_tracked_file_contains_harness_leak(): ...  # collects "path:pattern" offenders, asserts []
@pytest.mark.parametrize("path", [".beads/issues.jsonl", ".beads", "docs/beads.md"])
def test_beads_paths_are_allowed(path): ...  # not forbidden_dir(path)
@pytest.mark.parametrize("text", ["see .beads/ for issues", "/home/mitmproxy/.mitmproxy", "Beans are fine", "autotodo/x"])
def test_benign_text_is_allowed(text): ...  # leaks_in(text) == []
@pytest.mark.parametrize("text", [<assembled positive samples, one per pattern>])
def test_each_leak_pattern_is_detected(text): ...
def test_hygiene_file_does_not_match_itself(): ...  # leaks_in(Path(__file__).read_text()) == []
```

Notes:

- Positive samples are assembled from the same fragments (for example `"to" + "do/x.py"`), so the file stays clean.
- The `ALLOWED_FILES` literal `"." + "agents/AGENTS.md"` is assembled from fragments as well. This keeps the
  "never reference .agents/" constraint satisfied while still allowing the file.
- `git ls-files` runs with `cwd=REPO_ROOT` and `check=True`. If git is unavailable, `pytest.skip`. The unit job has git,
  so this skip only protects odd local environments. Count it as a branch and keep the function under 10 lines.
- Run `uv run pytest tests/test_repo_hygiene.py -q`, then the full suite.

### Dependencies & Criticality

- **Dependencies:** Steps 2-7 (otherwise the test fails on arrival)
- **Is bottleneck:** yes (it is the acceptance oracle)

### Safety & Constraint Considerations

- **Relevant rules:** pytest only; no new dependencies; patterns built so the file does not match itself; exact
  directory names; `.beads/` must pass; the provenance records are excluded.
- **Failure modes:** false positives on legitimate files outside the touch set, which would break CI for concurrent
  changes.
- **Guardrails:** before finalising, run the content check across all tracked files and inspect every hit. Any hit
  outside the touch set that is a true leak cannot be fixed here. In that case, report it in the execution notes and
  narrow the guard only if the intent allows it (it does not). The step is then reported as blocked rather than
  editing an off-limits file. The planning inventory found no such hit.

### Success & Discard Criteria

- **Success:** all hygiene tests pass, and temporarily adding a `todo/` path to a scratch tracked file (then reverting)
  makes the leak test fail.
- **Discard:** if an unavoidable false positive appears outside the touch set, drop that specific pattern and report it
  rather than widening exemptions silently.

### Step Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.90  |
| entropy_pred        | 0.9   |
| impact_pred         | 0.35  |
| cost_pred           | 0.03  |
| learning_value_pred | 0.20  |

**Step Metrics Rationale:** Regex boundary design and the self-exclusion technique carry most of the plan's learning
value and its main false-positive risk.

---

## Step 9: Verification, formatting and single squashed commit

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Required by intent goal 6 and AGENTS.md.
- **Step type:** verification / integration
- **Exploration level:** exploitation
- **Git branch:** same. One commit; no push.

### Implementation Details

```bash
git grep -nE 'todo/|Bean[ _-]?[0-9]{4}' -- ':!holon-knowledge/ledger' ':!plans' ':!executions' ':!intents'  # empty
uv run task test
uv run task lint
npx prettier --check $(git diff --name-only origin/main -- '*.md')
git diff --name-only origin/main   # must be a subset of the touch set
git add <explicit paths>
git commit -m "Remove harness path and task-id leaks; add repository hygiene test" \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Execution notes must list: any dropped steps or off-limits hits (for example Makefile, Dockerfile or README.md
references to the old wire-log directory if found), the migration note locations, and the test results.

### Dependencies & Criticality

- **Dependencies:** Steps 1-8
- **Is bottleneck:** yes

### Safety & Constraint Considerations

- **Relevant rules:** squash to one commit; no push; ledgers append-only (only the flow's own rows); no auxiliary
  ledgers.
- **Failure modes:** a file outside the touch set is accidentally staged.
- **Guardrails:** compare the `git diff --name-only` output against the touch-set list before committing.

### Success & Discard Criteria

- **Success:** the grep is empty, tests, lint and Prettier are green, and there is one commit containing only touch-set
  files.
- **Discard:** any check fails. Fix it within the touch set, or report and stop.

### Step Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.95  |
| entropy_pred        | 0.4   |
| impact_pred         | 0.05  |
| cost_pred           | 0.02  |
| learning_value_pred | 0.03  |

**Step Metrics Rationale:** These are deterministic checks. Any residual risk comes from earlier steps, which this step
surfaces.
