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

All six methods can be evaluated concurrently in an authentic end-to-end multi-turn session using the unified benchmark
script located in `todo/`:

```bash
# Execute the high-volume benchmark across real LLMs
python3 todo/ab_measure_all_methods.py
```

This harness executes real multi-turn coding tasks, produces full production application deliverables, extracts genuine
wire telemetry, and generates the consolidated scorecard report at `todo/scorecard_report.md`.
