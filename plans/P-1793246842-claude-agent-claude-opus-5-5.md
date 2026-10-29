# Plan for I-1793246826-coherence-ci-timing-regression-gate

- **Plan ID:** P-1793246842-claude-agent-claude-opus-5-5
- **Parent Intent ID:** NONE
- **Agent:** claude-agent (version: 2.1.302)
- **Created At:** 2026-10-29T04:07:22.611Z

## Overall Plan Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.85  |
| entropy_pred        | 1.20  |
| impact_pred         | 7.0   |
| cost_pred           | 0.30  |
| learning_value_pred | 1.5   |
| ev_pred             | 6.04  |

## Planner Autonomy Summary

- **Intent handling:** `ACCEPT_AS_IS`
- **Reframed intent (if applicable):** NONE
- **Exploration stance:** Mostly exploitation. The intent fixes the defaults, the touch set, the file names and the test
  matrix, and the repository already has the matching pattern (`scripts/pre_commit_check.py` imported by
  `tests/test_pre_commit_check.py` as `scripts.<module>`, enabled by `pythonpath = [".", "src"]` in `pyproject.toml`).
  One short exploratory step confirms three external facts the design depends on and cannot be checked from the tree
  alone: that `taskipy` forwards extra arguments (`uv run task test --junitxml=...`), the shape of the GitHub
  `GET /repos/{owner}/{repo}/actions/artifacts?name=` response (`workflow_run.head_branch`, `head_repository_id`,
  `expired`, `archive_download_url`), and that a standard-library `python3` (>= 3.11) is on `PATH` on `ubuntu-latest`
  and `macos-latest` before Conda is set up (the `make` and `docker-build` jobs never install Conda or `uv`).
- **Safety priority level:** elevated
- **Priority Justification:** The change edits every CI workflow on `main`; a defect fails every pull request for every
  concurrent change, or (worse) silently passes. It also introduces the first token-scoped API reads in these workflows.
  The blast radius is wide but fully reversible, no runtime code under `src/` is touched, and the gate logic is pure and
  unit-testable, so elevated (not strict) is proportionate.

## Exploration

- **Proportion of steps that are exploratory:** 0.13
- **Justification:** 1 of 8 steps (Step 1) is exploratory: it validates the CLI pass-through, the Artifacts API contract
  and the runner interpreter, each of which would otherwise surface only after a push as a red CI run. Everything else
  is specified by the intent and is exploitation.

## Plan Description & Strategy

1. Confirm external assumptions (taskipy argument pass-through, Artifacts API fields, runner `python3`) and record the
   current job ids, matrices and permissions of the five workflows.
2. Write the pure core of `scripts/ci_timing_gate.py`: record schema, rolling median, the relative/absolute decision,
   the ceiling, cold start and the label override.
3. Add JUnit XML parsing and the per-test top-offender report to the same module.
4. Add the thin I/O layer (injectable fetchers for artefact listing, zip download, PR labels, clock and environment)
   and the `record` / `compare` command-line interface with all thresholds as flags.
5. Write `tests/test_ci_timing_gate.py` with fake fetchers, covering every case in goal 8 plus the replay of the real
   durations from the description.
6. Edit all five workflows: a first-step timestamp, the `--junitxml` flag on the two test commands, a gate step at the
   end of every job, an artefact upload on successful pushes to `main`, and least-privilege permissions.
7. Document the gate in `.github/workflows/README.md`.
8. Verify (`uv run task test`, `uv run task lint`, `npx prettier --check` on changed Markdown, a syntax-only parse
   of the edited YAML), squash to one commit, and push the execution branch, reporting a missing `workflow` scope as a
   blocker.

## Step-by-Step Breakdown

## Step 1: Confirm external assumptions and inventory the workflows

### Step Intent & Git Integration

- **Sub-intent recommendation:** none (part of the single intent, as the intent's own Q&A requires)
- **Reasoning:** Three design choices rest on facts outside the tree; checking them first is cheaper than a red CI run.
- **Step type:** exploration
- **Exploration level:** medium
- **Git branch:** the execution branch `I-1793246826-coherence-ci-timing-regression-gate/P-1793246842-claude-agent-claude-opus-5-5/E-<timestamp>-<agent>-<model>/_`
  (worktree branched off `origin/main` per `AGENTS.md`)

### Implementation Details

- In the worktree, confirm that `uv run task test --junitxml=/tmp/x.xml -q` writes the file (taskipy appends extra
  arguments to the task command). If it does not, fall back to `uv run pytest -m 'not integration_test' --junitxml=...`
  in the workflow only — but prefer the task form, because the intent names `uv run task test` as the canonical command
  and `pyproject.toml` must not change.
- Read the GitHub REST reference for `GET /repos/{owner}/{repo}/actions/artifacts` (query `name`, `per_page`; fields
  `id`, `name`, `expired`, `created_at`, `archive_download_url`, `workflow_run.{id, head_branch, head_sha,
repository_id, head_repository_id}`) and `GET /repos/{owner}/{repo}/actions/artifacts/{id}/zip` (302 redirect to
  short-lived blob storage; the `Authorization` header must not be forwarded to the redirect target), and
  `GET /repos/{owner}/{repo}/issues/{number}/labels` (readable with `pull-requests: read`).
- Note runner interpreters: `ubuntu-latest` ships `/usr/bin/python3` 3.12; `macos-latest` ships a Homebrew/Xcode
  `python3` >= 3.11. The script must therefore stay compatible with 3.11 (no 3.12-only syntax) even though the project
  targets 3.12, and must be invoked as `python3 scripts/ci_timing_gate.py`, not via `uv`/Conda, so that `make` and
  `docker-build` can run it. In `make.yml`, the "Ensure clean environment" step strips Conda from `PATH` only; system
  `python3` survives.
- Inventory (already observed): job ids `docker-build` (no matrix, `actions: write`), `make` (matrix ubuntu/macOS,
  `name: make (${{ matrix.os }})`), `hygiene` (ubuntu, `fail-fast: true`), `integration` (ubuntu, `actions: write`),
  `unit` (ubuntu/macOS). Job ids are unique across workflows, so `<job id>-<runner.os>` is a unique artefact key.

### Dependencies & Criticality

- **Dependencies:** none
- **Is bottleneck:** yes — Steps 4 and 6 consume its findings.

### Safety & Constraint Considerations

- **Relevant rules:** read-only; no network calls to the GitHub API with credentials from this sandbox are needed (the
  documentation suffices); no files written.
- **Failure modes:** taskipy does not forward arguments; Artifacts API field missing.
- **Guardrails:** fallbacks above are decided here and recorded in the execution notes.

### Success & Discard Criteria

- **Success:** each of the three facts is confirmed or a fallback is chosen.
- **Discard:** none — this step cannot fail the plan, only redirect Steps 4 and 6.

### Step Metrics

| metric         | value |
| :------------- | :---- |
| p_success      | 0.97  |
| entropy        | 0.10  |
| impact         | 0.5   |
| cost           | 0.02  |
| learning_value | 0.6   |

**Step Metrics Rationale:** cheap, read-only, high information value for the riskiest integration points.

## Step 2: Pure decision core of `scripts/ci_timing_gate.py`

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Keep every decision a pure function of numbers so the tests need no I/O.
- **Step type:** implementation
- **Exploration level:** low
- **Git branch:** execution branch (as Step 1)

### Implementation Details

- Module docstring (Australian English) states purpose, the two modes and that it uses the standard library only.
- `TimingRecord` dataclass: `schema` (1), `workflow`, `job`, `os`, `duration_s` (float), `started_at`, `finished_at`
  (epoch seconds), `sha`, `run_id`, `tests: dict[str, float]` (test id `classname::name` -> seconds). `to_json()` /
  `from_json()` helpers; unknown `schema` values are ignored with a notice rather than crashing.
- `rolling_median(values: list[float]) -> float` via `statistics.median`.
- `Verdict` dataclass: `status` in `{"pass", "warn", "fail"}`, `messages: list[str]`.
- `check_ceiling(duration, ceiling) -> str | None` — message when `duration > ceiling`.
- `check_relative(duration, baseline, count, tolerance, min_delta) -> str | None | Skip` — returns a skip notice when
  `len(baseline) < count` ("relative check skipped: only k of N main records; ceiling only"), otherwise a failure
  message only when `duration > median * (1 + tolerance)` **and** `duration - median > min_delta`. The message states
  duration, median, percentage and absolute delta, and both thresholds.
- `decide(duration, baseline, *, count, tolerance, min_delta, ceiling, accepted) -> Verdict` combines them: ceiling
  failure is always `fail`; a relative failure becomes `warn` when `accepted` is true, with the text
  "accepted by the pull-request label 'timing-regression-accepted'". Baseline uses the most recent `count` records only.
- Each function stays a few lines with at most one branch, per the intent's "short and low in branching" constraint.

### Dependencies & Criticality

- **Dependencies:** Step 1
- **Is bottleneck:** yes — Steps 3–5 build on it.

### Safety & Constraint Considerations

- **Relevant rules:** standard library only; Australian English ("artefact", "behaviour", "summarise").
- **Failure modes:** off-by-one between `>` and `>=` on the thresholds; percentage expressed as 50 vs 0.5.
- **Guardrails:** the flag is `--tolerance-percent 50` (a percentage, to match the documentation), converted to a
  fraction once at parse time; tests pin the boundary (exactly +50 % or exactly +30 s passes).

### Success & Discard Criteria

- **Success:** pure functions implemented, importable as `scripts.ci_timing_gate`, ruff-clean.
- **Discard:** none expected; the logic is fully specified.

### Step Metrics

| metric         | value |
| :------------- | :---- |
| p_success      | 0.97  |
| entropy        | 0.20  |
| impact         | 2.0   |
| cost           | 0.05  |
| learning_value | 0.1   |

**Step Metrics Rationale:** specified arithmetic; the only risk is boundary semantics, which the tests pin.

## Step 3: JUnit parsing and the per-test top-offender report

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Goal 4 (EXPLAIN) needs per-test baselines; storing parsed times inside the record avoids keeping raw
  XML in artefacts and keeps the comparison pure.
- **Step type:** implementation
- **Exploration level:** low
- **Git branch:** execution branch

### Implementation Details

- `parse_junit(text: str) -> dict[str, float]` with `xml.etree.ElementTree`: iterate every `testcase` (handles both a
  `testsuites` root and a bare `testsuite`), key `f"{classname}::{name}"`, value `float(time or 0)`. Skipped tests are
  kept (their time is real); a missing or unreadable file yields `{}` and a notice, never a crash. Only pytest's own
  output is parsed (trusted CI file), so `ElementTree` is acceptable; no DTDs/entities are used.
- `test_offenders(current, baseline_records, *, tolerance=0.5, min_delta=5.0, limit=10) -> list[Offender]`: for each
  current test, collect that test's times across baseline records, take the median, keep tests whose time exceeds the
  median by more than 50 % **and** more than 5 s, sort by absolute delta descending, return the top 10. Tests absent
  from the baseline are listed separately only as a count ("n new tests without a baseline").
- `format_offenders(offenders) -> list[str]` produces a fixed-width table (test id, baseline median, current, delta,
  percentage) and the line "no test grew by more than 50 % and 5 s" when empty.
- The per-test thresholds and limit are flags too (`--test-tolerance-percent 50`, `--test-min-delta 5`,
  `--test-limit 10`) so all numbers live in the workflow commands.

### Dependencies & Criticality

- **Dependencies:** Step 2
- **Is bottleneck:** no

### Safety & Constraint Considerations

- **Relevant rules:** report never changes the exit status on its own (goal 4).
- **Failure modes:** parametrised test ids with brackets; duplicate ids across files.
- **Guardrails:** duplicate ids are summed (pytest reruns are rare); ids are used verbatim.

### Success & Discard Criteria

- **Success:** parser and report pass their tests on real pytest JUnit output produced in Step 1.
- **Discard:** none.

### Step Metrics

| metric         | value |
| :------------- | :---- |
| p_success      | 0.96  |
| entropy        | 0.10  |
| impact         | 1.0   |
| cost           | 0.03  |
| learning_value | 0.1   |

**Step Metrics Rationale:** small, well-trodden stdlib parsing.

## Step 4: Injectable I/O layer and the `record` / `compare` CLI

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Goal 8 requires network and artefact access behind small injectable functions so tests use fakes.
- **Step type:** implementation
- **Exploration level:** low
- **Git branch:** execution branch

### Implementation Details

- `Fetchers` dataclass holding three callables: `list_artifacts(name) -> list[dict]`, `download_record(artifact) ->
TimingRecord | None`, `pr_labels(number) -> list[str]`. `github_fetchers(api_url, repo, token)` builds the real ones:
  - `_get_json(url)` via `urllib.request` with `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`,
    `X-GitHub-Api-Version: 2022-11-28` and a 20 s timeout.
  - `list_artifacts` calls `/actions/artifacts?name=<name>&per_page=100`, keeps only entries that are not `expired`,
    whose `workflow_run.head_branch == "main"` and whose `workflow_run.head_repository_id ==
workflow_run.repository_id` (rejects a fork branch also called `main`), sorted by `created_at` descending.
  - `download_record` requests `archive_download_url` with a no-redirect opener, then fetches the `Location` target
    **without** the token, opens the zip with `zipfile` in memory and reads `timing.json`. Any error returns `None` and
    a notice, so a flaky download degrades to a smaller baseline (and possibly the cold-start path), never a crash.
  - `pr_labels` reads `/issues/<number>/labels` live, so re-running the job after adding the label honours it (the
    event payload of a re-run is the original one and would be stale). On failure it falls back to the labels in
    `$GITHUB_EVENT_PATH`.
- `build_parser()` (argparse) with subcommands:
  - `record --workflow --job --os --started-at <epoch> [--junit PATH] --out DIR --ceiling 300`: computes
    `duration = now - started_at`, writes `DIR/timing.json`, prints the duration and applies the ceiling (exit 1 above
    it, so an over-ceiling main job is not recorded because the upload step runs only on success).
  - `compare` takes the same identity flags plus `--baseline-count 5 --tolerance-percent 50 --min-delta 30
--ceiling 300 --accept-label timing-regression-accepted --pr-number N` and the per-test flags. It also writes the
    current record (for debugging, uploaded never). Flow: build current record → `list_artifacts` → download the first
    `count` records → `decide` → per-test report when `--junit` is given → print and append to
    `$GITHUB_STEP_SUMMARY` → emit `::error::` / `::warning::` / `::notice::` annotations → exit 0/1. On failure the
    offender table is appended to the error message.
- `main(argv=None, *, fetchers=None, now=time.time, env=os.environ) -> int`; the token comes from `GITHUB_TOKEN` in the
  step's `env:`, never a flag, and is never printed.
- Artefact naming: `artefact_name(job, os) -> f"ci-timing-{job}-{os}"` (e.g. `ci-timing-unit-macOS`), used by both the
  workflow and the script (the script accepts `--artifact-name` to stay explicit, defaulting to this function).

### Dependencies & Criticality

- **Dependencies:** Steps 1–3
- **Is bottleneck:** yes — Step 6 calls this CLI.

### Safety & Constraint Considerations

- **Relevant rules:** read-only API use; no new dependencies; token not logged; Australian English in log strings.
- **Failure modes:** API rate limit or 5xx on a PR → must not block unrelated PRs; token forwarded to blob storage.
- **Guardrails:** any listing failure is treated as "0 records" → explicit cold-start notice, ceiling still enforced;
  explicit no-redirect opener for the download.

### Success & Discard Criteria

- **Success:** `python3 scripts/ci_timing_gate.py --help` works under Python 3.11 and 3.12; `main()` is fully
  exercisable with fakes.
- **Discard:** if the live label lookup proves unworkable, fall back to event-payload labels only and document that the
  author must push again (or close and reopen) after labelling.

### Step Metrics

| metric         | value |
| :------------- | :---- |
| p_success      | 0.90  |
| entropy        | 0.25  |
| impact         | 2.0   |
| cost           | 0.06  |
| learning_value | 0.3   |

**Step Metrics Rationale:** the only untestable-offline part (real HTTP) is deliberately thin; risk sits in the redirect
and filtering details, mitigated by Step 1.

## Step 5: `tests/test_ci_timing_gate.py`

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Goal 8 enumerates the required coverage; fakes keep the suite offline.
- **Step type:** test
- **Exploration level:** low
- **Git branch:** execution branch

### Implementation Details

- Import style mirrors `tests/test_pre_commit_check.py`: `from scripts.ci_timing_gate import ...`. Pytest only; plain
  functions and `tmp_path`/`monkeypatch`/`capsys`; no `unittest.mock` needed because fetchers are injected.
- A `FakeFetchers` helper built from a list of `TimingRecord`s (and a label list) — no network, no `gh`, no GitHub API.
- Cases:
  1. `rolling_median` on odd and even lengths, and that only the most recent `count` records are used.
  2. Pass inside the tolerance (+40 %, +35 s).
  3. Both-thresholds rule: +60 %/+20 s passes (delta below floor), +20 %/+40 s passes (below tolerance), +60 %/+40 s
     fails; exact boundary +50 %/+30 s passes.
  4. Ceiling: 301 s fails even with a matching baseline and with no baseline; 300 s passes.
  5. Cold start: 0 and 4 records with N = 5 → relative check skipped, the notice text is printed, exit 0 under the
     ceiling and 1 over it.
  6. Label override: relative failure + label → exit 0 and a warning naming `timing-regression-accepted`; ceiling
     failure + label → still exit 1.
  7. Per-test report: ordering by absolute delta, the 10-entry limit, both per-test thresholds, printed on a passing
     run, appended to the failure message on a failing run, never changing the exit code alone.
  8. JUnit parsing: a pytest-shaped `testsuites` document and a bare `testsuite`, parametrised ids, missing `time`,
     missing file.
  9. `record` mode writes `timing.json` with job, OS, duration and parsed tests (clock injected via `now`).
  10. Artefact filtering: expired entries, non-`main` branches and fork-head entries are dropped.
  11. **Replay of the real calibration durations** from the description (job wall clock from the GitHub API for the
      cited main runs), as a table in the test file with run ids in comments:
      - previous main 29b7e50 → latest main acbe924 with the previous value as the baseline (count 1): unit ubuntu
        62 → 53, unit macOS 102 → 115, integration 81 → 79, hygiene 54 → 49, docker-build 33 → 39 — all pass;
      - the worst healthy deviations against the median of the previous 5: unit ubuntu +38 %/+24 s, integration
        +31 %/+22 s, unit macOS +28 %/+26 s — reconstructed as (median, current) pairs from the cited percentages and
        deltas (≈63→87, ≈71→93, ≈93→119) — all pass because each delta is below 30 s and each percentage below 50 %;
      - every value in the cited window ranges (max 130 s) passes the 300 s ceiling;
      - a negative control: doubling the latest unit ubuntu job (53 → 106 against a 53 s median) fails, showing the
        gate catches a real doubling of a test job.
        These are real measured values, not generated data, which keeps the replay within world rule 1 in spirit; the
        fakes elsewhere exercise logic only and measure nothing.

### Dependencies & Criticality

- **Dependencies:** Steps 2–4
- **Is bottleneck:** no

### Safety & Constraint Considerations

- **Relevant rules:** tests run only via `uv run task test` / `uv run pytest` from the worktree root; no `PYTHONPATH`;
  no other test file touched; no `integration_test` marker (these are unit tests).
- **Failure modes:** a test accidentally reaching the network via the default fetchers.
- **Guardrails:** `main()` builds real fetchers only when `fetchers is None`; every test passes fakes, and an autouse
  fixture removes `GITHUB_TOKEN` from the environment.

### Success & Discard Criteria

- **Success:** the new tests and the whole existing suite pass under `uv run task test`.
- **Discard:** none.

### Step Metrics

| metric         | value |
| :------------- | :---- |
| p_success      | 0.95  |
| entropy        | 0.15  |
| impact         | 1.5   |
| cost           | 0.05  |
| learning_value | 0.2   |

**Step Metrics Rationale:** straightforward pure-function tests; the replay table is copied from the intent verbatim.

## Step 6: Wire the gate into all five workflows

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Goals 1, 2, 6 and 7 live in the workflow files.
- **Step type:** implementation
- **Exploration level:** low
- **Git branch:** execution branch

### Implementation Details

For every job (`docker-build`, `make`, `hygiene`, `integration`, `unit`):

- **First step** (before checkout): `- name: Record job start time` / `run: echo "CI_TIMING_STARTED_AT=$(date +%s)" >>
"$GITHUB_ENV"`.
- **Test commands only:** `unit` → `uv sync; uv run task test --junitxml="$RUNNER_TEMP/ci-timing/junit.xml"`;
  `integration` → `uv sync; uv run task test-docker --junitxml="$RUNNER_TEMP/ci-timing/junit.xml"`. Nothing in
  `pyproject.toml` or the `Makefile` changes.
- **Last step — gate**, `if: success()`, `shell: bash` (system `python3`, so it works after `make.yml` strips Conda and
  in `docker-build`, which has no Conda):
  - on `push` to `refs/heads/main`: `python3 scripts/ci_timing_gate.py record --workflow "${{ github.workflow }}"
--job "${{ github.job }}" --os "${{ runner.os }}" --started-at "$CI_TIMING_STARTED_AT" --out
"$RUNNER_TEMP/ci-timing" --ceiling 300 [--junit "$RUNNER_TEMP/ci-timing/junit.xml"]`;
  - on `pull_request`: `python3 scripts/ci_timing_gate.py compare ... --baseline-count 5 --tolerance-percent 50
--min-delta 30 --ceiling 300 --test-tolerance-percent 50 --test-min-delta 5 --test-limit 10 --accept-label
timing-regression-accepted --pr-number "${{ github.event.pull_request.number }}"` with `env: GITHUB_TOKEN: ${{
secrets.GITHUB_TOKEN }}`.
  - on `workflow_dispatch`: only the ceiling is enforced (`record` into a scratch directory with no upload step), so
    manual runs never enter the baseline. Separate steps guarded by `if:` on `github.event_name` keep each command
    readable and every flag visible in the file.
- **Upload step** (push to `main` only, after the gate): `actions/upload-artifact@v4` with `name: ci-timing-${{
github.job }}-${{ runner.os }}`, `path: ${{ runner.temp }}/ci-timing/timing.json`, `retention-days: 90`,
  `if-no-files-found: error`. Same-named artefacts across runs are allowed (names are unique per run, not per repo),
  which is exactly what the listing by `name` relies on. Nothing is written to the repository.
- **Permissions (least privilege, job level):** `unit`, `make`, `hygiene` gain `actions: read` and `pull-requests:
read` beside `contents: read`; `docker-build` and `integration` already hold `actions: write` (needed for the Buildx
  GHA cache) and gain only `pull-requests: read`. No job is given any write scope it did not already have.
- Do not change triggers, matrices, `fail-fast` or existing steps beyond the two test commands.

### Dependencies & Criticality

- **Dependencies:** Step 4 (CLI flags), Step 1 (taskipy pass-through)
- **Is bottleneck:** yes — the user-visible deliverable.

### Safety & Constraint Considerations

- **Relevant rules:** touch set limited to `.github/workflows/*.yml`; ceiling only editable by committing a change to
  its flag; goal 11 (`workflow` token scope).
- **Failure modes:** a typo in an expression breaks every PR; the gate measuring a different interval from the API
  calibration (it omits runner set-up and post-job clean-up, typically a few seconds, so it reads slightly lower, which
  only adds slack); the first PRs after merge see cold start for up to five main pushes.
- **Guardrails:** syntax-only YAML parse in Step 8; `if: success()` so the gate never masks a real failure; cold start
  is explicit and documented.

### Success & Discard Criteria

- **Success:** every job in every workflow has the start step, the gate step and the main-only upload; both test
  commands carry `--junitxml`; all thresholds appear as flags in the YAML.
- **Discard:** if a job cannot run `python3` (not expected), drop the gate for that job only and report it in the
  execution notes rather than editing any off-limits file.

### Step Metrics

| metric         | value |
| :------------- | :---- |
| p_success      | 0.88  |
| entropy        | 0.25  |
| impact         | 2.0   |
| cost           | 0.05  |
| learning_value | 0.3   |

**Step Metrics Rationale:** mechanical but cannot be executed locally; correctness is only fully proven on GitHub.

## Step 7: Document the gate in `.github/workflows/README.md`

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Goal 9.
- **Step type:** documentation
- **Exploration level:** low
- **Git branch:** execution branch

### Implementation Details

- Add a "CI timing regression gate" section: what is recorded and where (artefacts `ci-timing-<job>-<OS>`, 90-day
  retention, never in the repository); how comparison works (rolling median of the last 5 successful `main` records
  for the same job and OS); the failure rule (more than 50 % **and** more than 30 s over the median) and the 300 s
  ceiling; cold start behaviour.
- "Why these defaults": the calibration window (16 successful main pushes, 2026-10-09 to 2026-10-24), the job ranges,
  the worst healthy deviations (+38 %/+24 s, +31 %/+22 s, +28 %/+26 s) and the replay result; that 300 s is more than
  double the largest job (130 s, unit macOS). State honestly that for the shortest jobs (make ubuntu ~29 s,
  docker-build ~39 s) a doubling stays under the 30 s floor and is caught only by the ceiling.
- "Reading the report": the verdict line, the notice/warning/error annotations, the step summary and the top-10 test
  table columns.
- "Accepting a deliberate slow-down": add the label `timing-regression-accepted` and re-run the failed job (labels are
  read live); the warning names the label; the ceiling can change only by editing `--ceiling` in the workflow file.
- Update the existing bullets for `test-unit.yml` and `test-integration.yml` to mention the JUnit report. Do not add
  references to other repositories (leave the existing "Standards Alignment" text as it is; it belongs to another
  change).
- Run `npx prettier --write .github/workflows/README.md` (the repository pins `prettier@3.8.4` in `test-hygiene.yml`;
  use that version).

### Dependencies & Criticality

- **Dependencies:** Steps 4 and 6 (flag names)
- **Is bottleneck:** no

### Safety & Constraint Considerations

- **Relevant rules:** Australian English; target-native paths only; no harness identifiers.
- **Failure modes:** docs drifting from flags.
- **Guardrails:** copy flag names from the final YAML.

### Success & Discard Criteria

- **Success:** `npx --yes prettier@3.8.4 --check .github/workflows/README.md` passes.
- **Discard:** none.

### Step Metrics

| metric         | value |
| :------------- | :---- |
| p_success      | 0.98  |
| entropy        | 0.05  |
| impact         | 0.5   |
| cost           | 0.02  |
| learning_value | 0.1   |

**Step Metrics Rationale:** prose only.

## Step 8: Verify, squash, push and report

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Constraint 12 checks, `AGENTS.md` squash rule and goal 11.
- **Step type:** verification
- **Exploration level:** low
- **Git branch:** execution branch

### Implementation Details

- From the worktree root: `uv run task test` (whole suite), `uv run pytest tests/test_ci_timing_gate.py -v`,
  `uv run task lint`, `npx --yes prettier@3.8.4 --check .github/workflows/README.md` plus any other changed Markdown
  (the plan/execution records).
- Syntax-only YAML parse of each edited workflow: `npx --yes prettier@3.8.4 --stdin-filepath f.yml < f.yml >
/dev/null` (no new dependency).
- Interpreter compatibility: run `python3 -I scripts/ci_timing_gate.py --help` with the system interpreter.
- Smoke-run the CLI locally with a real JUnit file from Step 1 in `record` mode, and `compare` with fakes only via
  the tests (no real API calls from the sandbox).
- `git diff --name-only origin/main` must list only the four touch-set paths plus the flow's own `plans/`,
  `executions/` and appended ledger rows; `git diff` on `holon-knowledge/ledger/*.jsonl` must show additions only.
- Squash to one commit with the attribution trailer; push only the execution branch (never `main`). If the push is
  rejected for lacking the `workflow` scope, stop and report it as a blocker with the exact error, keeping the
  workflow edits intact.
- Execution notes list: the taskipy finding, the cold-start window after merge, the label re-run behaviour, and that
  end-to-end proof requires the first five main pushes after merge.

### Dependencies & Criticality

- **Dependencies:** Steps 2–7
- **Is bottleneck:** yes (gate to merge)

### Safety & Constraint Considerations

- **Relevant rules:** no push to `main`; ledgers append-only; touch set.
- **Failure modes:** push refused (workflow scope); lint failure from line length 120.
- **Guardrails:** blocker reporting as specified; `uv run ruff format .` before `task lint`.

### Success & Discard Criteria

- **Success:** all checks green, one commit, branch pushed or blocker reported.
- **Discard:** none; failures loop back to the owning step.

### Step Metrics

| metric         | value |
| :------------- | :---- |
| p_success      | 0.92  |
| entropy        | 0.10  |
| impact         | 0.5   |
| cost           | 0.02  |
| learning_value | 0.1   |

**Step Metrics Rationale:** routine verification; the main uncertainty is the external push permission.

## Strategy Rationale

The EV formula is `EV = P(success) * Impact + mu * LearningValue - lambda * Delta_S_intent - Cost` with lambda = 0.3 and
mu = 0.5.

- **P(success) = 0.85:** the product of the step probabilities is ≈ 0.62, but the steps are not independent failures —
  Steps 2, 3, 5 and 7 are near-certain and failures in them are corrected inside the same execution. The residual risk
  is concentrated in what cannot be proven offline: the workflow wiring (Step 6), the Artifacts API download path
  (Step 4) and the `workflow`-scope push (Step 8). 0.85 reflects that.
- **Impact = 7.0:** every future pull request gains a calibrated timing guard and a per-test explanation, closing a
  blind spot across all five workflows; it does not change product behaviour, so it is below a runtime feature.
- **LearningValue = 1.5:** first real per-job and per-test timing history for the repository, plus validation of the
  calibration once five main records exist.
- **Delta_S_intent = 1.20:** the sum of the step entropies (0.10 + 0.20 + 0.10 + 0.25 + 0.15 + 0.25 + 0.05 + 0.10).
- **Cost = 0.30:** about 0.30 of a normalised execution budget (the step costs sum to 0.30), plus a few seconds of CI
  time per job for the gate and the upload.
- **EV = 0.85 × 7.0 + 0.5 × 1.5 − 0.3 × 1.20 − 0.30 = 5.95 + 0.75 − 0.36 − 0.30 = 6.04.**

Alternatives rejected: storing records in the repository or a ledger (forbidden by goal 1); using the GitHub API's own
job timings instead of an in-job timestamp (goal 1 fixes the interval, and it would need run-level listing and more
permissions); `pytest --durations` text parsing (fragile, whereas JUnit is structured and required by goal 1); a
composite action or reusable workflow (would add files outside the touch set).

## Safety & Constraint Alignment

- **Key world ruleset constraints that affect this plan:**
  - `constraints.md` §1: work in a worktree branched off `origin/main`, one squashed commit, never push to `main`.
  - `constraints.md` §2: stay inside the worktree; non-interactive commands only; no persistent `export`s (the
    workflow uses `$GITHUB_ENV` per job, which is the job-scoped equivalent).
  - `constraints.md` §3: ledgers under `holon-knowledge/ledger/` append-only.
  - `constraints.md` §4 rule 1 (no synthetic data for benchmarking): the gate measures real CI jobs only; the replay
    test uses the real measured durations cited in the intent; fakes are confined to exercising logic.
  - Intent constraints: touch set (four paths plus the flow's own records), standard library only, no new
    dependencies, Australian English, tests only via `uv run task test` / `uv run pytest`, `uv run task lint` and
    Prettier on changed Markdown.
- **Potential violations or edge cases:**
  - Needing to change `pyproject.toml` if taskipy did not forward `--junitxml` (off-limits).
  - A flaky API read on a PR blocking unrelated work.
  - Leaking `GITHUB_TOKEN` to the artefact blob host via a redirect, or into logs.
  - Over-granting permissions.
  - Fork PRs: `GITHUB_TOKEN` is read-only there; `actions: read` still works, and labels may come only from the
    event payload.
  - Stale labels on job re-runs.
  - Baseline poisoning from non-main or fork artefacts, or from `workflow_dispatch` runs.
  - The ceiling being bypassed by label.
- **Mitigations built into the plan:**
  - Workflow-only fallback for the JUnit flag (Step 1); API failures degrade to the explicit cold-start path with the
    ceiling still enforced (Step 4).
  - A no-redirect opener that drops the token; the token is read from `env` only and never printed.
  - Job-level `actions: read` / `pull-requests: read` only where missing; no new write scopes.
  - Live label lookup with an event-payload fallback.
  - Filtering on `head_branch == "main"`, same head and base repository, not expired; uploads only on `push` to `main`.
  - The ceiling check is evaluated independently of the label in `decide` and covered by a test.
- **Residual risk accepted (and why):**
  - Cold start for the first five main pushes after merge, and again after 90 days without main pushes: the ceiling
    still applies, and the intent explicitly specifies this behaviour.
  - The 30 s floor lets a doubling of the shortest jobs (make ubuntu, docker-build) pass the relative check: accepted
    because the floor is calibrated so that no healthy run fails, and those jobs are dominated by runner and network
    noise rather than code.
  - End-to-end behaviour on GitHub cannot be proven from the sandbox: accepted, with the unit tests and syntax checks
    as the offline proxy and the first post-merge PR as confirmation.
- **Allocated Entropy Budget:** 10.0
- **Predicted Plan Entropy:** 1.20 (0.10 + 0.20 + 0.10 + 0.25 + 0.15 + 0.25 + 0.05 + 0.10)
- **Budget Compliance:** 1.20 ≤ 10.0 — compliant, using 12 % of the budget and leaving ample margin for Step 1
  fallbacks.
