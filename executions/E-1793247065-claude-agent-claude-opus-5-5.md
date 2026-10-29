# Execution Record: E-1793247065-claude-agent-claude-opus-5-5

- **Plan ID:** P-1793246842-claude-agent-claude-opus-5-5
- **Intent ID:** I-1793246826-coherence-ci-timing-regression-gate
- **Agent:** claude-agent (claude-opus-5-5)

## Summary

Added a CI timing regression gate: `scripts/ci_timing_gate.py` (standard library only, `record` / `compare`),
`tests/test_ci_timing_gate.py` (46 offline tests, including the replay of the real calibration durations), wiring in all
five workflows (start timestamp, JUnit report on the two test commands, gate steps, main-only artefact upload,
least-privilege read permissions) and a documentation section in `.github/workflows/README.md`. The whole suite, ruff and
Prettier pass locally. End-to-end proof needs the first five `main` pushes after merge (cold start until then).

## Actual Metrics

| metric                | value |
| :-------------------- | :---- |
| success_actual        | 0.90  |
| entropy_actual        | 0.90  |
| impact_actual         | 6.5   |
| cost_actual           | 0.25  |
| learning_value_actual | 1.2   |

## Steps Executed

### Step 1: Confirm external assumptions and inventory the workflows

- `uv` was not on `PATH` in the sandbox; installed it with `python3 -m pip install --user uv` (tooling only, no
  repository change) and ran `uv sync` in the worktree root.
- taskipy forwards extra arguments: `uv run task test --junitxml=/tmp/x.xml -q` wrote a pytest JUnit report
  (`testsuites` root, `testcase` elements with `classname`, `name`, `time`). The task form is used in the workflows;
  `pyproject.toml` is unchanged.
- Artifacts API contract taken from the GitHub REST reference (no credentialed calls from the sandbox):
  `GET /repos/{owner}/{repo}/actions/artifacts?name=&per_page=` returns `artifacts[]` with `id`, `name`, `expired`,
  `created_at`, `archive_download_url` and `workflow_run.{id, repository_id, head_repository_id, head_branch,
head_sha}`; `.../artifacts/{id}/zip` answers with a 302 to short-lived blob storage.
- Runner interpreters: the gate is run with the system `python3` and kept compatible with Python 3.11 (ruff
  `target-version = "py311"` already enforces this), so it works in `make` after Conda is stripped and in
  `docker-build`, which has no Conda.
- Inventory confirmed: `docker-build`, `make` (ubuntu/macOS), `hygiene`, `integration`, `unit` (ubuntu/macOS); job ids
  are unique across workflows, so `ci-timing-<job>-<runner.os>` is a unique artefact name.

### Step 2: Pure decision core

- `TimingRecord` (schema 1, unknown schemas ignored with a notice), `rolling_median`, `check_ceiling`,
  `check_relative` (returns a `Skip` on cold start), `decide` and `Verdict` (status, messages, notices). The ceiling is
  checked independently of the label. Boundaries are strict: exactly +50 % or exactly +30 s passes.
- `--tolerance-percent` is converted to a fraction once at parse time.

### Step 3: JUnit parsing and per-test report

- `parse_junit` / `read_junit` (bare `testsuite` or `testsuites`, duplicates summed, missing `time` is 0, unreadable or
  missing file yields `{}` with a notice), `test_offenders`, `count_new_tests`, `format_offenders`.
- Deviation: `test_offenders` keeps the planned name but sets `test_offenders.__test__ = False`, because importing it
  into a test module would otherwise make pytest collect it as a test.

### Step 4: Injectable I/O layer and CLI

- `Fetchers` (list, download, labels) and `github_fetchers` with `urllib`: Bearer token from `GITHUB_TOKEN` only,
  20 s timeout, artefact zip fetched with a no-redirect opener and the redirect target fetched without the token; live
  label lookup with an event-payload fallback.
- Deviation: the main/unexpired/same-repository filter lives in the pure `select_main_artifacts`, applied by `compare`
  to whatever the fetcher returns, so the filtering is exercised by the fakes as well.
- Any listing failure degrades to "0 main records" (cold start, ceiling still enforced). Labels are only read when
  `--pr-number` is given.
- Verified offline: `compare` against an unreachable API prints the cold-start notice and exits 0.

### Step 5: Tests

- `tests/test_ci_timing_gate.py`: 46 tests covering cases 1-11 of the plan, including the calibration replay
  (consecutive main runs, worst healthy deviations, 130 s under the ceiling, the 53 s to 106 s negative control). An
  autouse fixture removes `GITHUB_TOKEN`; every `compare` test injects fakes.

### Step 6: Workflows

- All five jobs: first step records `CI_TIMING_STARTED_AT`; `unit` and `integration` pass
  `--junitxml="$RUNNER_TEMP/ci-timing/junit.xml"`; three final steps (record on non-PR events, compare on
  `pull_request` with every threshold as a flag, upload `ci-timing-<job>-<OS>` on push to `main` with 90-day retention).
- Deviation: manual runs share the single `record` step (no scratch directory); they never upload because the upload
  step is limited to pushes to `main`. Identity flags use the default `$GITHUB_WORKFLOW`, `$GITHUB_JOB`, `$RUNNER_OS`
  variables and the PR number goes through `env`, avoiding expression interpolation in scripts.
- Deviation: permissions were added to the existing workflow-level `permissions` block (each workflow has one job)
  rather than a new job-level block: `actions: read` + `pull-requests: read` for make, hygiene and unit;
  `pull-requests: read` only for docker-build and integration. No new write scopes.

### Step 7: Documentation

- New "CI Timing Regression Gate" section in `.github/workflows/README.md` (recording, comparison, defaults and
  calibration, the short-job limitation, reading the report, accepting a slow-down, permissions); the `test-unit.yml` and
  `test-integration.yml` bullets mention the JUnit report.

### Step 8: Verification and commit

- All checks below pass. Committed as a single execution commit on top of the plan commit. The branch was not pushed:
  `AGENTS.md` forbids pushing to `origin` without an explicit instruction from the user, which takes precedence over the
  plan's push step. Pushing needs a token with the `workflow` scope because `.github/workflows/*.yml` change.
- Follow-ups: cold start lasts until five `main` pushes exist for each job and OS; adding the label requires a re-run of
  the failed job; GitHub-side behaviour (artefact download redirect, label permission) is only proven by the first PR
  after merge.

## Tests Run

| command                                                                 | result                                     |
| :---------------------------------------------------------------------- | :----------------------------------------- |
| `uv run task test --junitxml=/tmp/x.xml -q` (pre-change, taskipy check) | 704 passed, 4 skipped; JUnit file written  |
| `uv run pytest tests/test_ci_timing_gate.py -q`                         | 46 passed                                  |
| `uv run task test`                                                      | 750 passed, 4 skipped, 8 deselected        |
| `uv run task lint` (ruff check + format check)                          | all checks passed                          |
| `npx --yes prettier@3.8.4 --check "**/*.md"`                            | all files formatted                        |
| `npx --yes prettier@3.8.4 --check .github/workflows/*.yml`              | all five workflows parse and are formatted |
| PyYAML `safe_load` of the five workflows (`uv run --with pyyaml`)       | ok                                         |
| `python3 -I scripts/ci_timing_gate.py compare --help` / `record` smoke  | ok; `timing.json` with 708 test times      |
