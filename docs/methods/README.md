# AI Agent Token Reduction Methods — Index & Execution Guides

This directory contains standalone, methodical how-to guides for running and verifying each of the six token reduction
techniques implemented in the Holon Agentic Coder architecture.

Each guide details the architectural mechanisms, real LLM execution procedures (with strict zero synthetic/mock data
invariants), telemetry extraction commands, and verification criteria.

---

## 📚 Token Reduction Methods Index

| Technique            | Documentation Guide                                                | Core Focus & Mechanism                                                                                              | Primary Empirical Impact                                                                       |
| :------------------- | :----------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------ | :--------------------------------------------------------------------------------------------- |
| **Context Cleaning** | [Context Cleaning & Deduplication](context_cleaning.md)            | Prunes redundant historical tool outputs via SHA-256 payload hashing; preserves modified files and mutated listings | **140,851 bytes pruned** across turns; collapses $\mathcal{O}(N^2) \to \mathcal{O}(N)$ history |
| **Local Cache**      | [Hybrid & Semantic Local Cache](local_cache_layer.md)              | SQLite exact prefix & Jaccard semantic caching with proxy short-circuiting                                          | **0 tokens billed & 0 latency** on cache hits; 50% hit rate on repeated turns                  |
| **Prompt Cache**     | [Provider Prompt Cache Optimization](prompt_cache_optimization.md) | Stable prefix anchoring & provider cache control breakpoints                                                        | **273,678 tokens** billed at 90% discount; 72.2% peak cache hit rate                           |
| **RAG Indexer**      | [AST & BM25 Codebase Indexer](rag_codebase_indexer.md)             | Symbol-based AST mapping to replace brute-force codebase prompt dumping                                             | **-99.7% Turn 0 prompt size** (from 55,842 to 150 tokens)                                      |
| **OpenBrain Memory** | [OpenBrain Episodic Memory Layer](openbrain_memory.md)             | Cross-session memory registry to avoid repeated trial-and-error turns                                               | **8 turns saved (-61.5%)** by recalling established fixes on Turn 1                            |
| **Ringer Framework** | [Ringer Multi-Agent Tiering Framework](ringer_framework.md)        | Dynamic Tier 1 Architect / Tier 2 Executor delegation and output compression                                        | **34.8% of execution offloaded** to low-cost models; **-34.5% total cost**                     |

---

## 🚀 Unified Benchmark Runner

Each method is measured on an authentic multi-turn agent session routed through the proxy, once with the method enabled
and once with it disabled:

```bash
# `--command` hands the proxy on port 8080 a host temp dir as its wire-log dir, so it needs a proxy that writes to the
# host filesystem: from a source checkout, start the addon host-side, then run the same real workload twice through it
# (baseline vs optimised) and compare the captured turns
uv run mitmdump -s src/holon_coherence/mitm_addon.py --listen-port 8080 --set confdir=~/.holon/proxy-ca
holon-coherence ab-test --command "<agent workload command>"

# The container proxy (`holon-coherence start -d`) can only write to `~/.holon/logs/`: run the same workload once
# under the passive proxy and once under the optimised one, then score the mode-tagged log
# Start from a stopped proxy and an empty log so the scorecard pairs only these two passes (the old log is kept)
holon-coherence stop
mv ~/.holon/logs/transactions.jsonl ~/.holon/logs/transactions.$(date +%s).jsonl 2>/dev/null || true
holon-coherence start --passive -d
holon-coherence run -- <client command>
holon-coherence stop && holon-coherence start -d
holon-coherence run -- <client command>
holon-coherence ab-test --trace-file ~/.holon/logs/transactions.jsonl

# Or compare two previously captured wire-log directories
holon-coherence ab-test --baseline <baseline wire-log dir> --optimized <optimised wire-log dir>
```

Individual sessions can also be run directly: `holon-coherence run -- <cmd>` routes a command through an already
running proxy, while `holon-coherence start` and `holon-coherence <agent>` run the proxy container. That container
records turn telemetry in `~/.holon/logs/transactions.jsonl` (the host directory mounted as
the container's `WIRE_LOG_DIR`); an addon run directly without `WIRE_LOG_DIR` writes to
`.holon/mitm_wire_logs/transactions.jsonl` instead. Live cumulative totals come from `holon-coherence metrics --json`.
The comparison scorecard is printed to the terminal (or as JSON with `--json`); keep any saved copy under `.holon/`, for
example `.holon/scorecard_report.md`.
