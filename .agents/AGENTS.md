# Behavioral Rules for holon-coherence

- **Pytest execution**: Always execute `pytest` commands using `uv run pytest` (e.g., `uv run pytest <args>`) to ensure
  environment consistency and dependencies are resolved correctly.
- **Single Root Virtual Environment**: Always execute all `uv` and Python commands strictly from the worktree root
  directory. Virtual environments must exist exclusively at the root `.venv`.
- **Worktree Isolation**: Always develop features on a dedicated Git worktree branched off `origin/main`.
- **Zero Synthetic / Mock Data for Benchmarking**: Absolutely never use synthetic data, canned payloads, mock stream
  generators, or randomized simulation loops to measure the efficacy of token reduction methods or LLM performance.
  Benchmarking and scorecards must derive exclusively from authentic real data streams (live execution container runs,
  genuine captured wire logs in `transactions.jsonl`, or authentic production payload JSON files).
