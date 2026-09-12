# holon-coherence

> **High-coherence, low-entropy optimization gateway for fractal coding agents.**

`holon-coherence` is a wire-level HTTPS interception proxy and optimization layer designed to eliminate token waste, quadratic context bloat ($\mathcal{O}(N^2)$), and redundant cognitive friction in autonomous AI coding agents.

It operates transparently via standard proxy routing (`HTTP_PROXY="http://127.0.0.1:8080"`), requiring **zero code modifications** to the client agent.

---

## ⚡ Key Capabilities

1. **Context Cleaning & Tool Deduplication**: Intercepts outbound conversation histories, hashes returned tool payloads (`cat`, `ls`, file reads via SHA-256), and replaces identical historical outputs with structural tombstones while preserving active turns and modified files verbatim.
2. **Hybrid & Semantic Local Cache**: Disk-backed SQLite exact and Jaccard semantic caching that short-circuits repeated requests locally at **0 prompt/output tokens and sub-5ms latency**.
3. **Provider Prompt Cache Optimization**: Anchors static context at the prefix and automatically injects provider-specific cache control breakpoints (`"cache_control": {"type": "ephemeral"}`) to unlock 80–90% cost discounts.
4. **AST & Keyword Codebase Indexing**: Symbol-based AST mapping to replace brute-force Turn 0 codebase dumping, cutting initial prompt sizes by $\ge 99\%$.
5. **OpenBrain Episodic Memory**: Persistent cross-session lesson registry that prevents repetitive trial-and-error loops across separate development trajectories.
6. **Ringer Multi-Agent Tiering**: Dynamic delegation between Tier 1 Flagship reasoning models (Architect) and Tier 2 high-throughput execution models (Executor) with subtask result compression.
7. **Transparent Wire Telemetry**: Non-synthetic wire-level transaction logging (`transactions.jsonl`) capturing raw requests, cleaned requests, SSE streams, TTFT latency, and exact token counts.

---

## 🚀 Quick Start

### 1. Install via pip / uv

```bash
pip install holon-coherence
# Or with proxy dependencies:
pip install "holon-coherence[proxy]"
```

### 2. Run the Optimization Proxy

```bash
# Start in headless mode (port 8080)
holon-coherence start

# Or with interactive web dashboard on port 8081
holon-coherence start --web
```

### 3. Run via Docker

```bash
docker run --rm -it \
  -p 127.0.0.1:8080:8080 \
  -p 127.0.0.1:8081:8081 \
  -v ~/.holon/proxy-ca:/home/mitmproxy/.mitmproxy \
  -v ~/.holon/cache:/home/mitmproxy/.holon/cache \
  ghcr.io/holon-agentic-coder/holon-coherence:latest
```

### 4. Connect Any Agent

Configure standard environment variables:

```bash
export HTTP_PROXY="http://127.0.0.1:8080"
export HTTPS_PROXY="http://127.0.0.1:8080"
export SSL_CERT_FILE="${HOME}/.holon/proxy-ca/mitmproxy-ca-cert.pem"
export REQUESTS_CA_BUNDLE="${HOME}/.holon/proxy-ca/mitmproxy-ca-cert.pem"
export NODE_EXTRA_CA_CERTS="${HOME}/.holon/proxy-ca/mitmproxy-ca-cert.pem"
```

All outbound LLM traffic (Anthropic, Google Gemini, OpenAI) is now automatically optimized, cached, and recorded.

---

## 📚 Documentation

- [System Architecture](docs/token_reduction_architecture.md)
- [Measurement Plan & Empirical Telemetry](docs/token_reduction_measurement_plan.md)
- [A/B Testing & Efficacy Verification](docs/token_reduction_ab_testing.md)
- **Methodical How-To Guides**:
  - [Context Cleaning & Deduplication](docs/methods/context_cleaning.md)
  - [Hybrid & Semantic Local Cache](docs/methods/local_cache_layer.md)
  - [Provider Prompt Cache Optimization](docs/methods/prompt_cache_optimization.md)
  - [AST & BM25 Codebase Indexer](docs/methods/rag_codebase_indexer.md)
  - [OpenBrain Episodic Memory Layer](docs/methods/openbrain_memory.md)
  - [Ringer Multi-Agent Tiering](docs/methods/ringer_framework.md)

---

## 📄 License

Apache-2.0
