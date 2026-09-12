# holon-coherence

> **High-coherence, low-entropy optimization gateway for fractal coding agents.**

`holon-coherence` is part of the **Holon** family of self-improving, fractal intent coding agents, used to optimize LLM usage, eliminate token waste, and drive informational entropy to zero across autonomous execution loops.

It operates as a wire-level HTTPS interception proxy and optimization layer, eliminating quadratic context bloat ($O(N^2)$) and cognitive friction transparently via standard proxy routing, requiring **zero code modifications** to the client agent.

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

### 1. Install as Global CLI Command (Recommended)

Install `holon-coherence` directly into your system `$PATH` using `uv`:

```bash
# Install from local checkout
cd holon-coherence
uv tool install --editable .

# Or install directly from GitHub
uv tool install git+https://github.com/Holon-Agentic-Coder/holon-coherence.git
```

Once installed, `holon-coherence` is immediately executable anywhere in your terminal:

```bash
# Start in headless mode (port 8080)
holon-coherence start

# Or with interactive web dashboard on port 8081
holon-coherence start --web
```

---

### 2. Run Directly from Source

```bash
git clone https://github.com/Holon-Agentic-Coder/holon-coherence.git
cd holon-coherence
uv sync

# Run proxy
uv run holon-coherence start
```

### 3. Run via Docker

```bash
# Build local container
docker build -t holon-coherence:latest .

# Run container
docker run --rm -it \
  -p 127.0.0.1:8080:8080 \
  -p 127.0.0.1:8081:8081 \
  -v ~/.holon/proxy-ca:/home/mitmproxy/.mitmproxy \
  -v ~/.holon/cache:/home/mitmproxy/.holon/cache \
  holon-coherence:latest
```

### 4. Connect Any Agent (Inline Execution)

To prevent proxy variables from contaminating your current interactive shell session (which could disrupt unrelated tools, `git clone`, or package downloads), always pass proxy settings **inline** for your agent command, or use the `holon-coherence run` helper:

#### Method A: Using `holon-coherence run` (Recommended)

```bash
# Wraps your agent process with isolated proxy settings and CA trust
holon-coherence run -- <your-agent-command>
```

#### Method B: Inline Shell Environment Variables

```bash
HTTP_PROXY="http://127.0.0.1:8080" \
HTTPS_PROXY="http://127.0.0.1:8080" \
NO_PROXY="localhost,127.0.0.1,api.github.com,github.com" \
SSL_CERT_FILE="${HOME}/.holon/proxy-ca/mitmproxy-ca-cert.pem" \
REQUESTS_CA_BUNDLE="${HOME}/.holon/proxy-ca/mitmproxy-ca-cert.pem" \
NODE_EXTRA_CA_CERTS="${HOME}/.holon/proxy-ca/mitmproxy-ca-cert.pem" \
<your-agent-command>
```

All outbound LLM traffic (Anthropic, Google Gemini, OpenAI) is automatically optimized, cached, and recorded without altering your terminal's persistent state.

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

Licensed under the [Apache License, Version 2.0](LICENSE).
