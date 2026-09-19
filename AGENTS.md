# Agent Operating Guidelines & Rules for holon-coherence

Welcome, Agent. This document defines the operational rules, development workflows, and behavioral constraints for
working on `holon-coherence`.

---

## 🌲 Git Worktree Workflow

When contributing or executing tasks in `holon-coherence`:

1. **Worktree Isolation**: Never make code changes directly on the `main` worktree. Always create a dedicated Git
   worktree branched off `origin/main`:
   ```bash
   # From the repository root (or any active worktree root):
   git fetch origin main
   git worktree add --no-track -b feat/<feature-name> ../feat-<feature-name> origin/main
   cd ../feat-<feature-name>
   ```
2. **Squash Commits**: Ensure all commits on your feature branch are squashed into a single logical commit relative to
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
  Virtual environments must exist exclusively at `.venv` local to the active worktree root (`<worktree-root>/.venv`).
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
3. **Coding Agent Runners & Automated Proxy**: Use `holon-coherence <agent>` (or `holon-coherence run-agent <agent>`) to
   launch agents (`agy`, `claude`, `codex`, `opencode`, `pi`) through the optimization proxy. The proxy runs in
   background daemon mode by default and supports `--ephemeral` for one-off task teardowns.
4. **Universal Credentials & Native Auth Fallback (Rule 4)**: Standardize host credentials on `HOLON_AGENT_KEY`. Never
   require vendor-specific API keys. If `HOLON_AGENT_KEY` is omitted, runners transparently fallback to native host auth
   sessions (such as `~/.gemini`, `~/.claude.json`).
5. **Strict Repository Separation**: Commands targeting `holon-coherence` must be executed strictly inside
   `holon-coherence/` (or its git worktrees).
