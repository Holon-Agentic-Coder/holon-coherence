# Execution Record: E-1793246775-claude-agent-claude-opus-5-5

- **Plan ID:** P-1793246658-claude-agent-claude-opus-5-5
- **Intent ID:** I-1793246643-coherence-pin-python-3-13
- **Agent:** claude-agent (claude-opus-5-5)

## Summary

Pinned holon-coherence to Python 3.13. `pyproject.toml` now declares `requires-python = "==3.13.*"` and ruff
`target-version = "py313"`, a new `.python-version` contains `3.13`, `uv.lock` was regenerated and the README development
section documents the 3.13-only requirement. A fresh `uv sync --group dev` created a CPython 3.13.14 venv, and the tests,
lint and Prettier all pass. There were no source changes and no dependency version changes.

## Actual Metrics

| metric                | value |
| :-------------------- | :---- |
| success_actual        | 1.00  |
| entropy_actual        | 0.90  |
| impact_actual         | 0.60  |
| cost_actual           | 0.08  |
| learning_value_actual | 0.20  |

## Steps Executed

### Step 1: Pre-flight baseline

- The execution branch already contains `origin/main` (`acbe924`) plus the plan commit, so the sandbox workspace served
  as the isolated worktree and no extra worktree was created.
- The baseline matched the plan: `requires-python = ">=3.12"` (line 10), `target-version = "py311"` (line 53), the lock
  had `revision = 3` with a 3.14 `resolution-markers` split, and there was no `.python-version`.
- uv was not on `PATH`, so uv 0.13.6 was installed for the user with `pip install --user uv` (a host tool, not a
  project dependency). `uv python find 3.13` resolved `/usr/local/bin/python3.13` (3.13.14).
- The baseline package list was saved to `/tmp/lock-before.txt`.

### Step 2: `pyproject.toml`

- The two values changed, and `git diff --stat` shows 2 insertions and 2 deletions.

### Step 3: `.python-version`

- Created it with the content `3.13`. `git check-ignore` reported nothing, so the file is not ignored.

### Step 4: `uv.lock`

- Ran plain `uv lock` (no upgrade flags). The diff shows `requires-python` changed to `"==3.13.*"`, the
  `resolution-markers` block removed, and the lock `revision` bumped from 3 to 5. The revision bump is format metadata
  from the newer uv.
- `typing-extensions 4.14.0` was removed. It was only referenced under the marker `python_full_version < '3.13'`, which
  the new `requires-python` excludes. No package `version` changed and no new package was added.
- `uv lock --check` passed.

### Step 5: `README.md`

- Added a paragraph saying the project supports Python 3.13 only and that `uv sync --group dev` creates a 3.13 venv.
- Added `uv sync --group dev` to the worktree code block.
- Added "(Python 3.13 only)" to the local contributors sentence.
- `npx prettier --check README.md` passed.

### Step 6: Verification and commit

- Removed the old `.venv` and ran a fresh `uv sync --group dev`. The venv interpreter is 3.13.14, and `pyvenv.cfg`
  shows `version_info = 3.13.14`.
- All gates passed (see Tests Run). The touch set is limited to `pyproject.toml`, `uv.lock`, `.python-version`,
  `README.md` and this execution record. These are staged but not committed: `git commit` failed because the sandbox
  has no git author identity, and none was invented. They are left for the harness's single execution commit. Nothing
  was pushed.
- No row was appended to `holon-knowledge/ledger/executions.jsonl`, because the execution harness writes those
  rows itself (summary and action entries). Appending one by hand would duplicate them.

### Reported items (out of scope)

- The `Dockerfile` uses `FROM mitmproxy/mitmproxy:12.2.3` and `pip install .`. If that image's interpreter is not
  3.13, the build will now reject the package. This was not checked here because Docker is outside the touch set.
- The lock `revision` changed from 3 to 5 (uv 0.13.6).

## Tests Run

| command                                        | result                                        |
| :--------------------------------------------- | :-------------------------------------------- |
| `uv run python -c "...sys.version_info..."`    | 3.13.14                                       |
| `uv lock --check`                              | pass (57 packages)                            |
| `uv run task test`                             | 704 passed, 4 skipped, 8 deselected           |
| `uv run task lint`                             | All checks passed; 92 files already formatted |
| `npx prettier --check README.md <this record>` | pass                                          |

## Post-review amendments

The sections above record the state at the end of execution and are left unchanged. Pull request review then amended
that state, so the merged result differs from the record above in the following ways:

- `requires-python` is `">=3.13"`, not `"==3.13.*"`. The container image installs the package with `pip install .` on
  the `mitmproxy/mitmproxy:12.2.3` base image, whose interpreter is Python 3.14, so the exact pin failed the image build.
  That is the `Dockerfile` risk listed under "Reported items". Ruff `target-version = "py313"` and `.python-version`
  (`3.13`) are unchanged, so development and CI still run on Python 3.13.
- `uv.lock` was regenerated with `revision = 3` and keeps its 3.14 `resolution-markers`. `typing-extensions` remains
  removed, and no package version changed.
- The README says holon-coherence is developed and tested on Python 3.13, rather than that it supports Python 3.13 only.
