# Calibration Record (hand-authored): bean 0079 — flexible Conda env and OpenSSL check

> **This is not a `holon calibrate` artifact.** No `holon calibrate` run produced this file, and it deliberately does
> not use the `P-<timestamp>-<agent>-<model>_calibration.md` naming that flow reports carry, so that nothing in `plans/`
> can be mistaken for a flow provenance record. It was written by the harness operator at the maintainer's request that
> both PRs carry a calibration record, and it reports only what could be measured.

- **Change:** PR #13, branch `feat/0079-flexible-conda-env-and-openssl-check`, head `919674a`
- **Bean:** `holon-agentic-coder-ref-metadata-0079`
- **Intent / Plan / Execution references:** **none exist in this repository** — see section 2
- **Record date:** 2026-10-11

---

## 1. Measured actuals

`git diff --shortstat "$(git merge-base origin/main HEAD)" HEAD` on `919674a`:

| Metric                                     | Value                                                   |
| :----------------------------------------- | :------------------------------------------------------ |
| Files changed                              | `3` (`Makefile`, `README.md`, `tests/test_makefile.py`) |
| Insertions / deletions                     | `+1095` / `-31`                                         |
| Commits on branch                          | `9`                                                     |
| **Merge commits on branch**                | **`0`**                                                 |
| Test functions in `tests/test_makefile.py` | `39`                                                    |
| CI at `919674a`                            | `7/7 SUCCESS`                                           |

The zero-merges row is the point of the table. This branch never forward-merged `main`, so its diffstat **is** its work.
On the sibling PR in `holon-agentic-coder` (#69) `holon calibrate` recorded `37 files, +1677/-568` against a true
contribution of `7 files, +734/-4`, because a forward-merge of 35 files was counted as work — the defect tracked as
`holon-agentic-coder-ref-metadata-0083`. A calibration computed on this branch's basis would be accurate; the reason the
other one was not is merge topology, not the calculator.

## 2. Predicted metrics: unavailable, and not back-filled

`holon-knowledge/ledger/{intents,plans,executions}.jsonl` each hold four rows in this repository:
`remove-coherence-executable-entrypoint`, `audit-holon-coherence-architecture-bugs`,
`scaffold-holon-config-and-standard-directories`, `coherence-security-and-network-hardening`. **None corresponds to this
change.** There is no intent row, no plan row, and therefore no `$P(\text{success})$, impact, cost, learning-value or
$EV$ prediction to compare against.

So this record reports no $\Delta EV$, no entropy factor and no accuracy rating. The calculator derives `impact` and
`learning_value` from the _prediction_ and cost from execution metadata; inventing a prediction after the fact and then
measuring the error against it would produce a number that looks like calibration and is purely fiction. The absence is
the honest entry.

Worth naming plainly: the flow **has** driven this repository four times, so running this change through intent → plan →
execute was available, not blocked — the flow resolves one remote at a time via `get_repo_url()`, and both halves of
bean 0079 could not run in one pass. Working in a host worktree is the documented route for `holon-coherence`, but the
consequence — no intent provenance, no plan metrics, no EV accounting for a 1095-line change — is real and is what
section 2 is evidence of.

## 3. Review-loop outcome (from `.subagent/holon-coherence_pr13_coordination.json`)

| Iteration | Votes cast at        | Ensemble verdicts                                                                                          |
| :-------- | :------------------- | :--------------------------------------------------------------------------------------------------------- |
| 1         | `b0e8786`            | CHANGES_REQUESTED `1C/4I/6N`, CHANGES_REQUESTED `0/3/2`, reviewer 3 **FAILED** (runtime)                   |
| 2         | `13e22a4`            | CHANGES_REQUESTED `0/1/2`, `0/2/2`, `0/3/3`                                                                |
| 3         | `51f3222`, `86a960b` | CHANGES_REQUESTED; fixes landed at `d8e0564`, `39f4570`, `919674a`; **no head received three clean votes** |

- Findings applied: `12`. Rejected with reason: `1`. Residual risks recorded: `7`.
- Terminal state: **not approved**, iteration cap reached, handed to the maintainer for the merge decision.
- Deferred to beans rather than absorbed into this PR: `0082` (dry-run detector), `0083` (calibration measurement
  basis), `0084` (CI check-name collision).

The mechanism is worth recording because it is not "the code got worse": on a branch that must push each fix, every fix
moves the head and invalidates the votes cast against the previous head. Nine commits and twelve applied findings means
nine candidate heads, and no head survived a clean unanimous pass.

## 4. What this change actually hardened

Three behaviours that previously failed silently, each pinned by a test:

1. **Flexible Conda environment** — `create-conda-env` no longer insists on one environment name, and refuses to prune
   an environment it did not choose unless `CONDA_PRUNE` came from the command line.
2. **Dry-run honesty** — `make -I incdir_n` used to skip every prerequisite check and exit 0; the word-scan over
   `MAKEFLAGS` is replaced by an option-cluster test that drops leading long options and assignments and reads the one
   compacted flag word left (GNU make 3.81 and 4.x lay `MAKEFLAGS` out differently; recipe-time evaluation only), and no
   installing recipe line references `$(MAKE)` any more, so a missed dry run cannot install anything.
3. **A shell whose `read` cannot time out** (`/bin/dash`) — the target now **refuses and installs nothing** instead of
   skipping the prompt and exiting 0, so it never silently selects an environment on the user's behalf.

## 5. Residual risks carried forward

From the seven recorded: the `check-docker` probes still prefix-match their version capture (Bean 0086), the `openssl`
severity wording is stricter than the runtime behaviour, and the review-loop votes at iteration 1 include one reviewer
that failed on the local runtime rather than on the code. None is a known path to a broken install; all are on record
rather than in prose.
