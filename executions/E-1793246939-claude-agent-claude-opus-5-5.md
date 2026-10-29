# Execution Record: E-1793246939-claude-agent-claude-opus-5-5

- **Plan:** P-1793246750-claude-agent-claude-opus-5-5
- **Intent:** I-1793246735-coherence-remove-harness-path-and-task-id-leaks
- **Agent:** claude-agent (claude-opus-5-5)

## Summary

All nine plan steps completed. The wire-log default moved to `.holon/mitm_wire_logs` (with `WIRE_LOG_DIR` override
unchanged), the harness directory was dropped from `.gitignore`, task ids were removed from source, tests and docs,
the shipped docs now use repository-native paths and real `holon-coherence` commands instead of harness scripts and
absolute machine paths, and `tests/test_repo_hygiene.py` guards against reintroduction. Tests, ruff and Prettier are
green. Off-limits files needed no edits (no old wire-log default in Makefile, Dockerfile, config, .github, README.md or
scripts). Work was committed as a single commit on the execution branch; nothing was pushed.

## Actual Metrics

| metric                | value |
| :-------------------- | :---- |
| success_actual        | 1.0   |
| entropy_actual        | 5.4   |
| impact_actual         | 0.72  |
| cost_actual           | 0.20  |
| learning_value_actual | 0.35  |

## Steps Executed

### Step 1: Worktree setup and baseline inventory

- Deviation: the harness already placed this execution on a dedicated, isolated execution branch (not `main`) in a
  shallow single-commit checkout with no local `origin/main`. Creating a second worktree would have split the execution
  record from the changes, so all work was done on the execution branch in the provided workspace.
- `uv` was not on `PATH`; installed it with `pip install --user uv`, then `uv sync` created `.venv` at the root.
- Baseline: `uv run pytest` gave 704 passed, 4 skipped, 8 deselected; `uv run task lint` was clean.
- Inventory matched the plan, with additional hits inside the touch set:
  - test class names with an id suffix (`tests/test_cli.py` x3, `tests/test_mitm_addon.py` x1), which the id pattern
    matches;
  - the module docstring of `tests/test_mitm_addon.py` (plural "Beans" form);
  - the harness repository name in `docs/token_reduction_{ab_testing,measurement_plan,plan}.md` (including
    `../../<harness>/develop/...` relative links into the external checkout).
- `git grep mitm_wire_logs` over Makefile, Dockerfile, config, .github, README.md and scripts found no hard-coded old
  default.

### Step 2: Wire-log default to `.holon/mitm_wire_logs`

- Added `DEFAULT_WIRE_LOG_DIR = ".holon/mitm_wire_logs"` in `mitm_addon.py` and (separately) `commands/metrics.py`; the
  offline candidate list now uses the constant. The writer already calls `os.makedirs(..., exist_ok=True)`.
- `test_handle_metrics_offline_fallback_holon_logs` now calls `monkeypatch.chdir(tmp_path)`.
- New tests: offline fallback from `.holon/mitm_wire_logs`, metrics module default/override via `importlib.reload`
  (restored afterwards), and wire-logger default directory creation plus `WIRE_LOG_DIR` override in
  `tests/test_mitm_addon.py` (exercised through `dump_wire_transaction`, avoiding a reload of the heavy addon module).

### Step 3: `.gitignore`

- Removed the single harness-directory line. `git check-ignore` confirms `.holon/mitm_wire_logs/transactions.jsonl`
  is still ignored via `.holon`.

### Step 4: Task ids in source and tests

- Removed every id from docstrings/comments per the plan table ("normalizer" became "normaliser" on the rewritten
  line). Also renamed the four id-suffixed test classes (dropped the suffix; no name collisions).
- `git grep -nE 'Bean' -- src tests` is empty; ruff check/format clean; full suite 708 passed, 4 skipped.

### Step 5: `docs/methods/*.md`

- Applied the path mapping (runtime data under `.holon/`). Replaced the "Unified Benchmark Harness" file cells with "A/B
  measurement on captured wire logs (see [README](README.md))".
- `README.md`: the runner section now describes measuring each method on a real agent session through the proxy, using
  the shipped `holon-coherence ab-test` (`--command`, or `--baseline`/`--optimized` wire-log directories), plus
  `holon-coherence run -- <cmd>`, `.holon/mitm_wire_logs/transactions.jsonl` and `holon-coherence metrics --json`. No
  scripts or figures were invented.
- Dashboard test commands now use `uv run pytest .holon/artifacts/generate_website/test_dashboard.py`; "Initialize"
  became "Initialise" on the rewritten line.
- Migration note added after the directory set-up block in `context_cleaning.md`.

### Step 6: `docs/token_reduction_*.md` and `docs/mitm_telemetry_metrics_plan.md`

- `token_reduction_ab_testing.md`: Tiers 1-4 rewritten. Tier 1 is `uv run pytest`; Tier 2 is an offline parser smoke
  check (`ab-test --trace-file` on a captured wire log), explicitly not used for efficacy figures; Tier 3 is passive
  (`start --passive`) vs optimised proxy runs with `holon-coherence run --`; Tier 4 is `holon-coherence ab-test`.
  Harness checkout `cd` lines and the harness-relative mount path were replaced with repository paths.
- `token_reduction_plan.md`: harness name removed from the intro; tier headings no longer name scripts.
- `token_reduction_measurement_plan.md`: removed the harness-topology note; all links into the external checkout now
  point at `../src/holon_coherence/*.py` (all targets exist); Docker mounts use `${REPO_ROOT}/src`; path mapping
  applied; code sample shows `DEFAULT_WIRE_LOG_DIR = ".holon/mitm_wire_logs"`; the `.gitignore` sentence references the
  `.holon/` entry; migration note added in "Structured Wire Logger"; Gantt task and step 4 heading reworded.
- `mitm_telemetry_metrics_plan.md`: absolute link replaced with a repository-relative link; id dropped from the
  callout; Phase 5 rewritten around `X-Holon-*` headers, `.holon/mitm_wire_logs/transactions.jsonl`,
  `holon-coherence metrics --json` and `holon-coherence ab-test`.

### Step 7: `docs/audit_report.md`

- "Parent" line became "Scope"; the quoted absolute path finding is kept but described generically and marked resolved;
  mermaid nodes renamed `F1`-`F5` with id-free labels; candidate headings are "Candidate Follow-up: <title>"; section
  6 title and lead-in no longer use tracker terminology; 7.1 retitled and its id column dropped. `### ` heading count
  unchanged (26).

### Step 8: `tests/test_repo_hygiene.py`

- Implemented as planned (fragment-assembled tokens, exact first-component directory match, provenance and allowed-file
  exemptions, NUL-byte binary skip, git-unavailable skip). Added positive tests for every pattern (including the three
  id variants) and for each forbidden directory, plus negative tests (`.beads/`, `/home/mitmproxy/.mitmproxy`,
  `.holon/mitm_wire_logs`, a nested directory with the same name under `src/`).
- The first self-match run caught an unsplit absolute-path sample; it is now assembled from fragments.
- Negative proof: appending a harness-directory path to the tracked `.dockerignore` made the leak test fail; the file
  was then restored with `git checkout`.

### Step 9: Verification and commit

- Final `git grep` for harness directories and task ids (provenance directories excluded) is empty.
- Touch set only: `.gitignore`, `docs/audit_report.md`, `docs/methods/*.md`, `docs/mitm_telemetry_metrics_plan.md`,
  `docs/token_reduction_*.md`, the listed `src/` and `tests/` files, the new `tests/test_repo_hygiene.py` and this
  record. Paths were staged explicitly; one commit; no push.

## Tests Run

| command                                                                 | result                                    |
| :---------------------------------------------------------------------- | :---------------------------------------- |
| `uv run pytest` (baseline, before changes)                              | 704 passed, 4 skipped, 8 deselected       |
| `uv run pytest -q tests/test_repo_hygiene.py`                           | 23 passed                                 |
| Hygiene negative proof (scratch leak appended to `.dockerignore`)       | leak test failed as expected, reverted    |
| `uv run task test`                                                      | 731 passed, 4 skipped, 8 deselected       |
| `uv run pytest`                                                         | 731 passed, 4 skipped, 8 deselected       |
| `uv run task lint` (ruff check + format check)                          | All checks passed; 93 files formatted     |
| `npx prettier --check "**/*.md"`                                        | All matched files use Prettier code style |
| `git grep -nE '<harness dir>/\|<id pattern>'` excluding provenance dirs | no matches                                |
