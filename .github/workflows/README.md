# GitHub Actions Workflows

This directory contains the CI/CD workflows for the `holon-coherence` project.

## Workflows

- `make.yml`: Runs on pushes to `main` and pull requests across both `ubuntu-latest` and `macos-latest`. It verifies
  `uname -m`, `make help`, `make` (default target), tests that Conda is not present, installs Conda, installs the
  `holon` Conda environment from `environment.yml`, and verifies the environment and `uv` installation.
- `docker-build.yml`: Runs on pushes to `main` and pull requests on `ubuntu-latest`. It builds the Docker container via
  `make build-image` using Buildx Bake with multi-architecture caching and verifies image creation.
- `test-hygiene.yml`: Runs on pushes to `main` and pull requests on `ubuntu-latest`. It pulls out all repository hygiene
  into an isolated build: verifying dependencies with `uv sync`, ensuring `uv.lock` is up-to-date, running Ruff linting
  and formatting via `uv run task lint`, checking markdown formatting with Prettier, and validating cleanup via
  `uv run task clean`.
- `test-unit.yml`: Runs on pushes to `main` and pull requests for both `ubuntu-latest` and `macos-latest`. It executes
  unit tests (`uv run task test`) using the Conda environment, writing a pytest JUnit report that feeds the per-test
  timing report.
- `test-integration.yml`: Runs on pushes to `main` and pull requests on `ubuntu-latest`. It builds the Docker image via
  `make build-image` and executes integration tests that require Docker services, writing a pytest JUnit report that
  feeds the per-test timing report. For why Docker runs only on Ubuntu, see [macos-docker.md](../macos-docker.md).

## CI Timing Regression Gate

Every job in every workflow ends with `scripts/ci_timing_gate.py`, a standard-library script run with the runner's
system `python3` (so it works in `make` after Conda is removed and in `docker-build`, which has no Conda).

### What is recorded

- The first step of each job writes `CI_TIMING_STARTED_AT` (epoch seconds) to `$GITHUB_ENV`; the gate measures from
  there to its own start. Runner set-up and post-job clean-up are excluded, so it reads a few seconds below the job
  time shown by GitHub.
- On pushes to `main`, `record` writes `timing.json` (workflow, job, OS, duration, SHA, run id and, for `unit` and
  `integration`, per-test times parsed from the JUnit report) and uploads it as the artefact
  `ci-timing-<job id>-<runner OS>` (for example `ci-timing-unit-macOS`) with 90-day retention. Nothing is written to the
  repository. Manual (`workflow_dispatch`) runs only enforce the ceiling and never enter the baseline.

### How pull requests are compared

On `pull_request`, `compare` lists the artefacts with the same name, keeps unexpired ones from `main` runs of this
repository (fork branches called `main` are rejected) and takes the most recent 5 (`--baseline-count 5`). The job
fails when:

- its duration exceeds the rolling median by **more than 50 % and more than 30 s** (`--tolerance-percent 50`,
  `--min-delta 30`); exactly +50 % or exactly +30 s passes; or
- its duration exceeds the absolute ceiling of **300 s** (`--ceiling 300`), whatever the baseline or labels say.

With fewer than 5 main records (cold start: the first five main pushes after this gate lands, or after 90 days without
a main push) the relative check is skipped with a notice and only the ceiling applies. An unreachable API or an
unreadable artefact also degrades to a smaller baseline or a cold start, never to a failed job; at most twice the
baseline count of downloads is attempted. A missing start timestamp skips the gate with a notice and records nothing
(the upload then only warns). The gate only runs when every earlier step succeeded, so it never masks a real failure.
All thresholds are flags in the workflow files.

### Why these defaults

The defaults were calibrated on the job wall clock of the 16 successful `main` pushes between 2026-10-09 and 2026-10-24.
The largest job was `unit` on macOS at 130 s; the worst healthy deviations from the median of the previous five runs
were +38 %/+24 s (`unit` ubuntu), +31 %/+22 s (`integration`) and +28 %/+26 s (`unit` macOS). Each stays under at least
one of the two thresholds, so replaying the window produces no failures, while doubling the latest `unit` ubuntu job (53
s to 106 s) fails. The 300 s ceiling is more than double the largest job.

For jobs whose median is at or below 30 s (for example `make` on ubuntu, at 29 s on the latest `main` run, and at times
`docker-build`, whose runs ranged from 25 s to 63 s) a doubling stays within the 30 s floor, so only the ceiling catches
them. This is deliberate: those jobs are dominated by runner and network noise. Once a job's median is above 30 s, as
for `docker-build` at 39 s on the latest `main` run, it fails when it grows by more than both 50 % and 30 s.

### Reading the report

- The step log and the job summary show the verdict line, for example `CI timing unit (Linux): pass, 62 s`.
- Annotations: `notice` for informational messages (cold start, unreadable artefacts), `warning` for an accepted
  regression and `error` for a failure, stating the duration, median, percentage, absolute delta and both thresholds.
- For `unit` and `integration`, a table lists up to 10 tests (`--test-limit 10`) that grew by more than 50 % and more
  than 5 s against their own median (`--test-tolerance-percent 50`, `--test-min-delta 5`), largest absolute delta
  first, with columns `test`, `median`, `current`, `delta` and `change`, plus a count of new tests without a baseline.
  The table never changes the result on its own; on failure it is appended to the error annotation.

### Accepting a deliberate slow-down

Add the label `timing-regression-accepted` to the pull request and re-run the failed job. Labels are read live from the
API, so a re-run honours a label added after the first run. A relative failure then becomes a warning naming the
label. The label never overrides the ceiling, which can only change by editing `--ceiling` in the workflow file.

Not every failure is a slow-down worth accepting. When `docker-build` fails after its Buildx cache was evicted or
invalidated, the cold cache is transient: re-run the job first, and add the label only if a warm-cache re-run still
fails.

### Permissions

The gate needs `actions: read` (artefact listing) and `pull-requests: read` (labels). `make`, `test-hygiene` and
`test-unit` gain exactly these; `docker-build` and `test-integration` already hold `actions: write` for the Buildx
cache and gain only `pull-requests: read`. The token is passed through the step environment and never printed, and it
is not forwarded to the blob-storage redirect when an artefact is downloaded.

## Key Configuration: Conda Package Resolution

During the setup of the CI, packages are resolved from the `conda-forge` channel via `environment.yml`.

### Conda Package Format (`use-only-tar-bz2: false`)

The `setup-miniconda` action includes:

```yaml
use-only-tar-bz2: false
```

## Reusable Actions

- `.github/actions/ci-timing-gate`: Reusable composite action eliminating duplicated shell blocks for recording job
  start epochs and verifying job runtimes against maximum duration budgets.
  - **Prerequisite:** `actions/checkout` must execute before invoking this action so the local composite action definition exists on disk.
  - **Inputs:**
    - `phase`: Required. `'start'` writes `CI_JOB_START_EPOCH` (and `CI_TIMING_STARTED_AT` for backward compatibility) to `$GITHUB_ENV`; `'check'` invokes the runtime budget checker script (`scripts/check_ci_runtime_budget.py`).
    - `max-seconds`: Optional (default: `'300'`). Maximum allowed runtime threshold in seconds.

  ```yaml
  - name: Checkout repository
    uses: actions/checkout@v7

  - name: CI Timing Gate (Start)
    uses: ./.github/actions/ci-timing-gate
    with:
      phase: start

  # ... job execution steps ...

  - name: CI Timing Gate (Check <= 5 min)
    if: always()
    uses: ./.github/actions/ci-timing-gate
    with:
      phase: check
      max-seconds: "300"
  ```

- `.github/actions/docker-pull`: Reusable composite action to pull images from GHCR mirror with automatic fallback to
  public upstream registry and local re-tagging. Note: Workflows using this action require `packages: write` permissions
  to push images to the GHCR mirror on fallback.

  ```yaml
  - uses: ./.github/actions/docker-pull
    with:
      image_name: mitmproxy/mitmproxy:12.2.3
      github_token: ${{ secrets.GITHUB_TOKEN }}
  ```

## Standards Alignment

All workflows in this repository conform to the standard Holon modular CI/CD architecture derived from
[`agentic-knowledge-base/.github`](https://github.com/thomashan/agentic-knowledge-base/tree/main/.github).
