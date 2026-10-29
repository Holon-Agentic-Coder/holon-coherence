# Plan for I-1793246643-coherence-pin-python-3-13

- **Plan ID:** P-1793246658-claude-agent-claude-opus-5-5
- **Parent Intent ID:** NONE
- **Agent:** claude-agent (version: 2.1.302)
- **Created At:** 2026-10-29T04:04:19.480Z

## Overall Plan Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.92  |
| entropy_pred        | 1.20  |
| impact_pred         | 0.60  |
| cost_pred           | 0.10  |
| learning_value_pred | 0.20  |
| ev_pred             | 0.19  |

### Strategy Rationale

`EV = P(success) * Impact + mu * LearningValue - lambda * Delta_S_intent - Cost`, with lambda = 0.3 and mu = 0.5:

`EV = 0.92 * 0.60 + 0.5 * 0.20 - 0.3 * 1.20 - 0.10 = 0.552 + 0.100 - 0.360 - 0.100 = 0.192 ≈ 0.19`

- **P(success) 0.92:** the change is four files and mostly declarative. The intent author has already verified on main
  `acbe924` that ruff 0.16.7 with `--target-version py313` passes check and format with no source change. The residual
  risk sits in `uv lock` (a lock that drifts beyond the `requires-python` and `resolution-markers` lines) and in the
  host lacking a 3.13 interpreter (uv can download one, but a network-restricted sandbox might block it; note that `uv`
  was not on `PATH` in the planning sandbox, so the executor must run in an environment with uv).
- **Impact 0.60:** this removes a real reproducibility defect (venvs coming up on 3.14.8) and lines CI, conda, Docker
  docs and the sibling repository up on one interpreter. It is a tooling change, not a feature, so impact is moderate.
- **Learning value 0.20:** low. The only new information is how far `uv lock` rewrites the lock once the 3.14 split
  disappears.
- **Entropy 1.20:** the sum of the step entropies below, well within the 4.0 budget.
- **Cost 0.10:** a handful of edits, one lock regeneration, one sync and two task runs.

## Planner Autonomy Summary

- **Intent handling:** `ACCEPT_AS_IS`
- **Reframed intent (if applicable):** NONE
- **Exploration stance:** heavy exploitation. The intent fixes the exact values (`==3.13.*`, `py313`, `.python-version`
  = `3.13`), the touch set and the verification commands. The only exploratory element is inspecting the `uv.lock` diff
  to confirm that it contains nothing beyond the expected interpreter-related changes.
- **Safety priority level:** elevated
- **Priority Justification:** the change is low-risk in code terms, but the intent sets a strict four-file touch set
  because concurrent changes own neighbouring files (`.github/workflows/`, `Dockerfile`, `environment.yml`, `src/`,
  `tests/`). A lock regeneration can also silently bump transitive dependencies, which would breach the "no new
  dependencies" rule. Both risks call for explicit guardrails rather than standard care.

## Exploration

- **Proportion of steps that are exploratory:** 0.17
- **Justification:** one of six steps (Step 1, the pre-flight baseline check) is exploratory: it confirms the starting
  state (line numbers, lock header, a 3.13 interpreter available to uv) before anything is edited. Every other step is a
  prescribed edit or verification. No further exploration is warranted because the intent has already established that
  the ruff target change needs no source change.

## Safety & Constraint Alignment

- **Key world ruleset constraints that affect this plan:** from `holon-config/world/ruleset.md`, `constraints.md` and
  `AGENTS.md`:
  - Work in a dedicated git worktree branched off `origin/main`; squash to one commit; never push without explicit
    instruction.
  - Run every `uv` and Python command from the worktree root, with the venv only at `<worktree-root>/.venv`.
  - Run tests only through `uv run task test` or `uv run pytest`: never use `PYTHONPATH` and never name another runner.
  - Pass `uv run task lint` (ruff check plus ruff format check) and `npx prettier --check` on every changed Markdown
    file.
  - Use Australian English in docs.
  - Add no new dependencies.
  - Keep paths target-native: no `.beans/`, `todo/`, `.agents/`, bean ids or review ids in any target file.
  - Keep the ledgers under `holon-knowledge/ledger/` append-only, and create no auxiliary ledgers.
  - **Touch set:** `pyproject.toml`, `uv.lock`, a new `.python-version` and `README.md`, plus the flow's own ledger
    rows and `plans/` / `executions/` records.
- **Potential violations or edge cases:**
  1. `uv lock` could re-resolve and bump the unpinned `taskipy>=1.14.1` or transitive packages, which would bring
     dependency changes in by stealth.
  2. `npx prettier --write "**/*.md"` (the AGENTS.md habit) would reformat Markdown files outside the touch set.
  3. `uv run task fix-ruff` or `ruff format .` could rewrite files under `src/` or `tests/` if `py313` triggered new
     `UP` (pyupgrade) fixes.
  4. An existing `.venv` built on 3.14 could mask whether a fresh sync selects 3.13.
  5. The host may have no 3.13 interpreter, and uv's managed-Python download may be blocked.
  6. Accidental edits to other `pyproject.toml` keys (for example the ruff section, or tasks such as a `lint-docs`
     task, which is explicitly out of scope).
  7. A test that asserts on `pyproject.toml` contents or interpreter versions (none were found by grep over `tests/`,
     `scripts/`, `Makefile` and `.github/`, but this must be confirmed by the test run).
- **Mitigations built into the plan:**
  - Run `uv lock` without `--upgrade`, then review `git diff uv.lock`. Only the `requires-python` line, the removal of
    `resolution-markers` and the 3.14-only marker/wheel entries are acceptable. Any changed package `version =` line
    is a stop condition.
  - Run Prettier with `--check` (and `--write` only if needed) on `README.md` alone.
  - Never run fix modes for ruff. Use only `uv run task lint` (check-only). If it fails under `py313`, stop and
    report, because a source change is out of scope.
  - Delete `.venv` before the verification sync, and assert the interpreter with
    `uv run python -c "import sys; print(sys.version)"` and `.venv/pyvenv.cfg`.
  - Before committing, run `git diff --name-only origin/main` and require it to list exactly the four touch-set paths
    (plus the flow's own records).
- **Residual risk accepted (and why):** `requires-python = "==3.13.*"` makes the package uninstallable on 3.12 and
  3.14. This is the stated intent, and it matches the sibling holon-agentic-coder. The Dockerfile keeps using the
  mitmproxy base image's interpreter, which the intent explicitly leaves alone. If that image's Python is not 3.13 and
  the image installs the package with pip, the Docker build could reject it. That is outside the touch set, and the
  executor reports it in notes if observed, rather than fixing it.
- **Allocated Entropy Budget:** 4.0
- **Predicted Plan Entropy:** 1.20 (0.15 + 0.15 + 0.05 + 0.35 + 0.20 + 0.30)
- **Budget Compliance:** compliant. 1.20 is 30% of the 4.0 budget, which leaves ample headroom for a stop-and-report
  outcome on the lock or lint checks.

## Plan Description & Strategy

1. **Pre-flight:** create the worktree off `origin/main` and confirm the baseline (line numbers, lock header, no
   `.python-version`, a 3.13 interpreter available to uv).
2. **Edit `pyproject.toml`:** set `requires-python = "==3.13.*"` and `[tool.ruff] target-version = "py313"`; change
   nothing else.
3. **Add `.python-version`:** the single line `3.13`.
4. **Regenerate `uv.lock`:** run `uv lock`, audit the diff for version drift, and confirm with `uv lock --check`.
5. **Document in `README.md`:** state "Python 3.13 only" and that `uv sync --group dev` creates a 3.13 virtualenv,
   in the development setup sections; run the Prettier check.
6. **Verify and commit:** run a fresh `uv sync --group dev` (asserting 3.13), `uv run task test`, `uv run task lint`
   and the touch-set audit, then make one squashed commit (no push).

## Step 1: Pre-flight baseline and worktree

### Step Intent & Git Integration

- **Sub-intent recommendation:** none (part of the single intent).
- **Reasoning:** confirms that the facts the intent cites still hold on current `origin/main` before any edit, and
  isolates the work as AGENTS.md requires.
- **Step type:** exploratory / setup.
- **Exploration level:** medium.
- **Git branch:** `I-1793246643-coherence-pin-python-3-13`, as a worktree off `origin/main`.

### Implementation Details

- `git fetch origin main`. Create or enter the worktree for the intent branch based on `origin/main`, and `cd` to its
  root.
- Confirm:
  - `sed -n 10p pyproject.toml` shows `requires-python = ">=3.12"`.
  - `grep -n target-version pyproject.toml` shows `"py311"` under `[tool.ruff]`.
  - `head -7 uv.lock` shows `requires-python = ">=3.12"` and the `resolution-markers` split at `3.14`.
  - `test ! -e .python-version` succeeds.
- Confirm that uv is available (`uv --version`) and that a 3.13 interpreter is obtainable:
  `uv python find 3.13 || uv python install 3.13`.
- Record the baseline package versions for the later comparison:
  `grep -E '^(name|version) = ' uv.lock > /tmp/lock-before.txt` (a scratch file outside the repository, not a ledger).

### Dependencies & Criticality

- **Dependencies:** none.
- **Is bottleneck:** yes. Without a 3.13 interpreter, Steps 4 and 6 cannot run.

### Safety & Constraint Considerations

- **Relevant rules:** worktree isolation; commands from the worktree root.
- **Failure modes:** `main` has moved and the line numbers differ (harmless; edit by key rather than line number); no
  network for `uv python install` (stop and report).
- **Guardrails:** read-only checks only; scratch output goes to `/tmp`.

### Success & Discard Criteria

- **Success:** the baseline matches the intent description and `uv python find 3.13` resolves.
- **Discard:** no 3.13 interpreter can be obtained → stop and report in the execution notes.

### Step Metrics

| metric         | value |
| :------------- | :---- |
| p_success      | 0.95  |
| entropy        | 0.15  |
| impact         | 0.10  |
| cost           | 0.01  |
| learning_value | 0.10  |

#### Step Metrics Rationale

These are read-only checks. The only uncertainty is whether the interpreter is available in the execution host
(uv was absent from the planning sandbox).

## Step 2: Pin the interpreter and ruff target in `pyproject.toml`

### Step Intent & Git Integration

- **Sub-intent recommendation:** none.
- **Reasoning:** the core declarative change. `requires-python` constrains resolution and installation;
  `target-version` aligns ruff's pyupgrade rules with the runtime.
- **Step type:** implementation.
- **Exploration level:** low.
- **Git branch:** `I-1793246643-coherence-pin-python-3-13`.

### Implementation Details

- Replace `requires-python = ">=3.12"` with `requires-python = "==3.13.*"` in `[project]`.
- Replace `target-version = "py311"` with `target-version = "py313"` in `[tool.ruff]`.
- Make no other changes. In particular, do not touch the tasks, the dependency groups or the classifiers, and do not
  add a `lint-docs` task.
- Check: `git diff --stat pyproject.toml` shows exactly 2 insertions and 2 deletions.

### Dependencies & Criticality

- **Dependencies:** Step 1.
- **Is bottleneck:** yes. Step 4 depends on the new `requires-python`.

### Safety & Constraint Considerations

- **Relevant rules:** "nothing else in the file changes"; the touch set.
- **Failure modes:** an editor reformats the TOML, or a stray whitespace change slips in.
- **Guardrails:** use exact string replacement and the two-line diff check.

### Success & Discard Criteria

- **Success:** the diff is exactly the two value changes.
- **Discard:** any other hunk appears → revert the file and redo the edit.

### Step Metrics

| metric         | value |
| :------------- | :---- |
| p_success      | 0.99  |
| entropy        | 0.15  |
| impact         | 0.35  |
| cost           | 0.01  |
| learning_value | 0.00  |

#### Step Metrics Rationale

This is a deterministic two-value edit. Its entropy reflects the behavioural change for installers (3.12 and 3.14 are
now rejected), not any difficulty in making the edit.

## Step 3: Add `.python-version`

### Step Intent & Git Integration

- **Sub-intent recommendation:** none.
- **Reasoning:** uv honours `.python-version` when it chooses an interpreter, so CI (`uv sync` in `test-unit.yml`) and
  local syncs select 3.13 without any workflow edit.
- **Step type:** implementation.
- **Exploration level:** none.
- **Git branch:** `I-1793246643-coherence-pin-python-3-13`.

### Implementation Details

- Create `.python-version` at the repository root containing exactly `3.13` followed by a single trailing newline
  (`printf '3.13\n' > .python-version`).
- Confirm that `.gitignore` does not ignore it: `git check-ignore -v .python-version` must print nothing. If it is
  ignored, stop and report, because `.gitignore` is outside the touch set. Do not use `git add -f` to bypass it
  silently.

### Dependencies & Criticality

- **Dependencies:** Step 1.
- **Is bottleneck:** no.

### Safety & Constraint Considerations

- **Relevant rules:** touch set (new `.python-version` permitted).
- **Failure modes:** the file is ignored by `.gitignore`; a patch version is written (for example `3.13.15`), which
  would over-pin relative to the intent.
- **Guardrails:** use the exact content `3.13`, then run the ignore check.

### Success & Discard Criteria

- **Success:** `cat .python-version` prints `3.13`, and `git status` shows it as untracked and addable.
- **Discard:** the file is ignored by `.gitignore` → report and stop.

### Step Metrics

| metric         | value |
| :------------- | :---- |
| p_success      | 0.97  |
| entropy        | 0.05  |
| impact         | 0.15  |
| cost           | 0.01  |
| learning_value | 0.00  |

#### Step Metrics Rationale

The step creates a single trivial file. The only risk is the `.gitignore` rule, which is out of scope to change.

## Step 4: Regenerate and audit `uv.lock`

### Step Intent & Git Integration

- **Sub-intent recommendation:** none.
- **Reasoning:** the lock must record the new `requires-python`, or `uv lock --check` and `uv sync --locked` will fail.
- **Step type:** implementation and verification.
- **Exploration level:** low–medium (the shape of the diff is predicted but not certain).
- **Git branch:** `I-1793246643-coherence-pin-python-3-13`.

### Implementation Details

- From the worktree root, run `uv lock`. Do not pass `--upgrade` or `--upgrade-package`.
- Expected diff:
  - the `requires-python = ">=3.12"` line becomes `requires-python = "==3.13.*"`;
  - the `resolution-markers` block (`>= '3.14'` / `< '3.14'`) is removed;
  - any package entries, markers or wheels that existed only for the 3.14 fork collapse or drop out.
- Audit with `grep -E '^(name|version) = ' uv.lock | diff /tmp/lock-before.txt -`:
  - no package may change its `version`;
  - no new package `name` may appear;
  - a package that only the 3.14 fork needed may disappear;
  - a package listed twice (once per fork) may collapse to the single version the `< 3.14` fork used.
- Run `uv lock --check`; it must exit 0.

### Dependencies & Criticality

- **Dependencies:** Step 2.
- **Is bottleneck:** yes. Step 6's sync depends on a valid lock.

### Safety & Constraint Considerations

- **Relevant rules:** no new dependencies; touch set (`uv.lock` permitted).
- **Failure modes:** uv re-resolves `taskipy>=1.14.1` or transitive packages to newer versions; a newer uv bumps the
  lock `revision` (acceptable, because it is format metadata only, but note it in the execution notes).
- **Guardrails:** no upgrade flags; a version-diff audit against the baseline.

### Success & Discard Criteria

- **Success:** `uv lock --check` passes, and the diff contains only interpreter-scoped changes.
- **Discard:** any package version bump or new package → `git checkout uv.lock`, retry once with plain `uv lock`. If
  the drift persists, stop and report it rather than committing the drift.

### Step Metrics

| metric         | value |
| :------------- | :---- |
| p_success      | 0.90  |
| entropy        | 0.35  |
| impact         | 0.20  |
| cost           | 0.03  |
| learning_value | 0.10  |

#### Step Metrics Rationale

This step carries the highest uncertainty in the plan, because the lock is machine-generated and the removal of the
fork changes its structure. The audit turns that uncertainty into a binary check.

## Step 5: Document the Python 3.13 requirement in `README.md`

### Step Intent & Git Integration

- **Sub-intent recommendation:** none.
- **Reasoning:** contributors need to know that only 3.13 is supported and that the uv dev sync produces a 3.13
  venv; the conda route (line ~104) already says 3.13.
- **Step type:** documentation.
- **Exploration level:** low.
- **Git branch:** `I-1793246643-coherence-pin-python-3-13`.

### Implementation Details

- In `## 🛠 Development & Worktree Workflow`, immediately after the introductory sentence and before the code block,
  add a short paragraph in Australian English, for example:

  > holon-coherence supports Python 3.13 only. `pyproject.toml` declares `requires-python = "==3.13.*"` and the
  > repository's `.python-version` pins `3.13`, so running `uv sync --group dev` from the worktree root creates a
  > Python 3.13 virtualenv at `.venv`, downloading a 3.13 interpreter through uv if the host does not have one.

- In the code block, add `uv sync --group dev` (with a comment such as
  `# Create the Python 3.13 development virtualenv`) before `uv run task test`.
- Optionally add a one-line pointer in `#### For Local Contributors & Development:` noting the Python 3.13 requirement.
  Keep it to one sentence, and do not duplicate the paragraph.
- Wrap at the repository's 120-column Markdown width.
- Do not mention harness paths (`.beans/`, `todo/`, `.agents/`), bean ids or review ids.
- Run `npx prettier --check README.md`. If it fails, run `npx prettier --write README.md` (this file only) and
  re-check. Never use the `"**/*.md"` glob here, because it would touch files outside the touch set.

### Dependencies & Criticality

- **Dependencies:** Steps 2 and 3 (the README must describe the committed state).
- **Is bottleneck:** no.

### Safety & Constraint Considerations

- **Relevant rules:** Australian English; Prettier on changed Markdown; target-native paths; touch set.
- **Failure modes:** American spellings creep in (for example "honor" or "optimize" in new text); the global Prettier
  glob reformats `docs/`; the README claims behaviour that is not true (for example that CI was edited).
- **Guardrails:** keep the wording factual and limited to what Steps 2–4 deliver; use the single-file Prettier
  invocation; spell-check the new lines by eye.

### Success & Discard Criteria

- **Success:** both statements (3.13 only; `uv sync --group dev` creates a 3.13 venv) are present in the development
  setup section, and `npx prettier --check README.md` passes.
- **Discard:** Prettier rewrites unrelated README regions → inspect the changes. If they are pre-existing formatting
  drift, keep only this change's hunks, and report the drift.

### Step Metrics

| metric         | value |
| :------------- | :---- |
| p_success      | 0.96  |
| entropy        | 0.20  |
| impact         | 0.10  |
| cost           | 0.02  |
| learning_value | 0.00  |

#### Step Metrics Rationale

The documentation edit is small. Its entropy covers wording and Prettier reflow risk.

## Step 6: Verify end-to-end and make one squashed commit

### Step Intent & Git Integration

- **Sub-intent recommendation:** none.
- **Reasoning:** the intent's VERIFY clause needs proof of a fresh 3.13 venv and passing test and lint runs. AGENTS.md
  needs a single squashed commit and no push.
- **Step type:** verification / integration.
- **Exploration level:** low.
- **Git branch:** `I-1793246643-coherence-pin-python-3-13`.

### Implementation Details

1. Run `rm -rf .venv` (the worktree-local venv only), then `uv sync --group dev` from the worktree root.
2. Assert that the interpreter is 3.13:
   - `uv run python -c "import sys; assert sys.version_info[:2] == (3, 13), sys.version; print(sys.version)"`;
   - `grep -E '^version' .venv/pyvenv.cfg` must show `3.13.x`.
3. Run `uv lock --check` again; it must still exit 0.
4. Run `uv run task test`; it must pass (unit tests, integration tests excluded).
5. Run `uv run task lint` (ruff check plus `ruff format --check`). It must report "All checks passed!" and that all
   files are already formatted. If any `UP` rule or other violation appears under `py313`, **stop and report**:
   source edits are out of scope, so do not run `fix-ruff`.
6. Run `npx prettier --check README.md`.
7. Audit the touch set: `git status --porcelain` and `git diff --name-only origin/main` must list only `pyproject.toml`,
   `uv.lock`, `.python-version` and `README.md` (plus this flow's own plan and execution records and ledger appends).
   Revert anything else.
8. Run `git add pyproject.toml uv.lock .python-version README.md` (plus the flow records). Make one commit, for example
   `chore: pin holon-coherence to Python 3.13`, with a body summarising the four changes and ending with the required
   `Co-Authored-By` attribution line. Squash if more than one commit exists relative to `origin/main`.
9. Do not push.
10. Append the execution row to `holon-knowledge/ledger/executions.jsonl` (append-only), recording the observed
    interpreter version, the test and lint results, and any dropped or reported items. Candidate items to report:
    - the Dockerfile base-image interpreter, if relevant;
    - drift in the lock `revision`.

### Dependencies & Criticality

- **Dependencies:** Steps 2–5.
- **Is bottleneck:** yes. This step is the acceptance gate.

### Safety & Constraint Considerations

- **Relevant rules:**
  - tests only via `uv run task test` / `uv run pytest` from the root, with no `PYTHONPATH`;
  - lint must pass;
  - append-only ledgers;
  - no push;
  - single commit.
- **Failure modes:**
  - a test depends on the 3.14 behaviour of a library;
  - `mitmproxy==12.2.3` has no 3.13 wheel for a dependency (unlikely: the conda route already uses 3.13);
  - stale `__pycache__` folders;
  - the `.venv` deletion is aimed at the wrong directory.
- **Guardrails:**
  - delete only `./.venv` from the confirmed worktree root;
  - make no source edits under any failure;
  - stop and report on any failing gate.

### Success & Discard Criteria

- **Success:** all of the following hold:
  - the venv interpreter is 3.13.x;
  - `uv lock --check`, `uv run task test`, `uv run task lint` and `npx prettier --check README.md` all exit 0;
  - the diff is limited to the touch set;
  - there is exactly one commit ahead of `origin/main`.
- **Discard:** any gate fails in a way that would need a file outside the touch set → do not commit that fix. Record
  the failure and its cause in the execution notes, and leave the branch for review.

### Step Metrics

| metric         | value |
| :------------- | :---- |
| p_success      | 0.93  |
| entropy        | 0.30  |
| impact         | 0.10  |
| cost           | 0.03  |
| learning_value | 0.10  |

#### Step Metrics Rationale

The ruff outcome was pre-verified by the intent author, so the main uncertainty is a fresh 3.13 resolution of the
pinned dependency set and test behaviour on 3.13. Both are low-risk, given that the conda route and the sibling
repository already run on 3.13.
