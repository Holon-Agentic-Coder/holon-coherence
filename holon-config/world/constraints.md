# Holon World Constraints

This document defines the core operational constraints, git workflow disciplines, sandbox safety boundaries, and
behavioral invariants for `holon-coherence`.

---

## §1 Git Flow & Branch Disciplines

1. **Branch Prefix Convention**: Work must strictly adhere to the hierarchical Holon branch naming convention:
   - Intent branch: `I-<timestamp>-<slug>/_` (or `I-<timestamp>-<slug>`)
   - Plan branch: `I-.../P-<timestamp>-<agent>-<model>/_`
   - Execution branch: `I-.../P-.../E-<timestamp>-<agent>-<model>/_`
2. **Squash Commits & Rebase Discipline**: Feature and execution commits relative to `main` must maintain clean commit
   boundaries and be squashed into a single logical commit upon task completion.
3. **No Autonomous Remote Push**: Never push directly to `main`. Remote branch push operations must follow designated
   workflow rules and never unilaterally overwrite remote target branches.

---

## §2 Sandbox Containment

1. **Filesystem Boundaries**: Tool and agent actions must remain within the allocated workspace directory
   (`<worktree-root>`). Never modify files outside designated workspace boundaries or system roots.
2. **Subprocess Execution**: Unvetted or arbitrary system subprocesses must not be executed. All commands must run in
   non-interactive, auditable processes.
3. **Process Isolation**: Do not use persistent exports of environment variables (e.g., `export HTTP_PROXY=...`) that
   contaminate shared shell sessions. Use inline environment variables or ephemeral command runners
   (`holon-coherence run -- <cmd>`).

---

## §3 Ledger Immutability

1. **Append-Only History**: Historical records within `holon-knowledge/ledger/` (including `intents.jsonl`,
   `plans.jsonl`, and `executions.jsonl`) are strictly immutable.
2. **Zero Modification or Truncation**: Never modify, overwrite, edit, or truncate pre-existing ledger lines. New
   entries must only be appended to the corresponding ledger files.

---

## §4 Behavioral Invariants

1. **Zero Synthetic / Mock Data for Benchmarking (Rule 1)**: Absolutely never use synthetic data, canned payloads, mock
   stream generators, or randomized simulation loops to measure the efficacy of token reduction methods or LLM
   performance. All evaluations, telemetry metrics, and scorecards must derive exclusively from authentic real data
   streams (live execution container runs, genuine captured wire logs in `transactions.jsonl`, or authentic production
   payloads).
2. **Inline Proxy Process Isolation (Rule 2)**: When connecting agents or test runners to the proxy, use inline
   environment variables or `holon-coherence run -- <cmd>` rather than persistent `export HTTP_PROXY=...` to prevent
   terminal session contamination.
3. **Universal Credentials & Native Auth Fallback (Rule 4)**: Standardize host credentials on `HOLON_AGENT_KEY`. Never
   require vendor-specific API keys. If `HOLON_AGENT_KEY` is omitted, runners transparently fallback to native host auth
   sessions (such as `~/.gemini`, `~/.claude.json`).
4. **Strict Repository Separation (Rule 5)**: Commands targeting `holon-coherence` must be executed strictly inside
   `holon-coherence/` (or its git worktrees).
