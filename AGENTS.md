# Agent Operating Guidelines & Rules for holon-coherence

Welcome, Agent. This document defines the operational rules, development workflows, and behavioral constraints for
working on `holon-coherence`.

---

## 🌲 Git Worktree Workflow

When contributing or executing tasks in `holon-coherence`:

1. **Worktree Isolation**: Never make code changes directly on the `main` worktree. Always create a dedicated Git
   worktree branched off `origin/main`:
   ```bash
   cd holon-coherence/.git
   git worktree add --no-track -b feat/<feature-name> ../feat-<feature-name> origin/main
   ```
   _(Note: If you are already inside an existing worktree, `git worktree add` can be run directly without changing into
   `.git` where `.git` is a pointer file.)_
2. **Squash and Push**: Ensure all commits on your feature branch are squashed into a single logical commit relative to
   `main`.
3. **No Autonomous Remote Push**: Never push to `origin` unless explicitly instructed by the user. Never push directly
   to `main`.

---

## 🛠 Testing & Environment Standards

- **Pytest Execution**: Always execute tests using `uv run pytest` from the root of the worktree:
  ```bash
  uv run pytest
  ```
- **Single Root Virtual Environment**: Always execute all `uv` and Python commands strictly from the worktree root.
  Virtual environments must exist exclusively at `.venv`.
- **Prettier Markdown Formatting**: Always format markdown files using Prettier before committing:
  ```bash
  npx prettier --write "**/*.md"
  ```
- **Ruff Linting and Formatting**: Ensure Python code passes ruff checks:
  ```bash
  uv run ruff check .
  uv run ruff format .
  ```

---

## 🔒 Behavioral Invariants

1. **Zero Synthetic / Mock Data for Benchmarking**: Absolutely never use synthetic data, canned payloads, mock stream
   generators, or randomized simulation loops to measure the efficacy of token reduction methods or LLM performance. All
   evaluations, telemetry metrics, and scorecards must derive exclusively from authentic real data streams (live
   execution container runs, genuine captured wire logs in `transactions.jsonl`, or authentic production payloads).
2. **Inline Proxy Process Isolation**: When connecting agents or test runners to the proxy, use inline environment
   variables or `holon-coherence run -- <cmd>` rather than persistent `export HTTP_PROXY=...` to prevent terminal
   session contamination.
3. **Strict Repository Separation**: Commands targeting `holon-coherence` must be executed strictly inside
   `holon-coherence/` (or its git worktrees).
