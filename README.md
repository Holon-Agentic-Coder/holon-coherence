# holon-coherence

> **High-coherence, low-entropy optimization gateway for fractal coding agents.**

`holon-coherence` is part of the **Holon** family of self-improving, fractal intent coding agents, used to optimize LLM
usage, eliminate token waste, and drive informational entropy to zero across autonomous execution loops.

It operates as a wire-level HTTPS interception proxy and optimization layer, eliminating quadratic context bloat
($O(N^2)$) and cognitive friction transparently via standard proxy routing, requiring **zero code modifications** to the
client agent.

---

## ⚡ Key Capabilities

1. **Context Cleaning & Tool Deduplication**: Intercepts outbound conversation histories, hashes returned tool payloads
   (`cat`, `ls`, file reads via SHA-256), and replaces identical historical outputs with structural tombstones while
   preserving active turns and modified files verbatim.
2. **Hybrid & Semantic Local Cache**: Disk-backed SQLite exact and Jaccard semantic caching that short-circuits repeated
   requests locally at **0 prompt/output tokens and sub-5ms latency**.
3. **Provider Prompt Cache Optimization**: Anchors static context at the prefix and automatically injects
   provider-specific cache control breakpoints (`"cache_control": {"type": "ephemeral"}`) to unlock 80–90% cost
   discounts.
4. **AST & Keyword Codebase Indexing**: Symbol-based AST mapping to replace brute-force Turn 0 codebase dumping, cutting
   initial prompt sizes by $\ge 99\%$.
5. **OpenBrain Episodic Memory**: Persistent cross-session lesson registry that prevents repetitive trial-and-error
   loops across separate development trajectories.
6. **Ringer Multi-Agent Tiering**: Dynamic delegation between Tier 1 Flagship reasoning models (Architect) and Tier 2
   high-throughput execution models (Executor) with subtask result compression.
7. **Transparent Wire Telemetry**: Non-synthetic wire-level transaction logging (`transactions.jsonl`) capturing raw
   requests, cleaned requests, SSE streams, TTFT latency, and exact token counts.

---

## 📋 Prerequisites & Automated Setup

`holon-coherence` automates prerequisite verification and environment provisioning entirely through the
[`Makefile`](Makefile), avoiding manual installations.

### 1. Automated Prerequisite Verification

Run the automated check to verify all dependencies (Docker CLI, Docker Buildx, Docker daemon, and Conda):

```bash
make check-prerequisites
```

### 2. Automated Installation via Makefile

If any prerequisite is missing, install and configure it directly using the Makefile targets:

- **Docker (CLI, Buildx & Daemon)**:

  ```bash
  # Check Docker prerequisite and install/start if missing:
  make check-docker

  # Or install Docker directly for your OS (macOS Docker Desktop via Homebrew, or Linux Docker engine):
  make install-docker
  ```

  _(Because `holon-coherence` packages the complete interception proxy inside an isolated container, `mitmproxy` and
  `mitmdump` do NOT need to be installed on your host system)._

- **Conda Environment (`holon`) & `uv`**:

  ```bash
  # Installs Miniforge (if not installed) and provisions the 'holon' Conda environment:
  make create-conda-env

  # Activate the environment in your shell:
  conda activate holon
  ```

- **Build Docker Container**:
  ```bash
  make build-image
  ```

### 3. Local Directory Permissions

Read/write access to `~/.holon/` for certificate generation (`~/.holon/proxy-ca`), disk cache (`~/.holon/cache`), and
wire telemetry logs (`~/.holon/logs`).

---

## 🚀 Quick Start (Docker-First Architecture)

`holon-coherence` is designed as a lightweight CLI wrapper around Docker. This ensures **zero host system
dependencies**—the entire proxy engine (`mitmproxy`/`mitmdump`), TLS interceptor, and caching layers execute inside an
isolated container, eliminating host Python version conflicts, compilation issues, or proxy network pollution.

### 1. Install CLI Wrapper

Install `holon-coherence` into your system `$PATH` via `uv`:

```bash
# Install from local checkout
cd holon-coherence
uv tool install --editable .

# Or install directly from GitHub
uv tool install git+https://github.com/Holon-Agentic-Coder/holon-coherence.git
```

### 2. Manage the Proxy Container

The `holon-coherence` CLI automatically manages Docker images, volumes, and certificates for you:

```bash
# Start proxy container (port 8080)
holon-coherence start

# Run in background (detached)
holon-coherence start -d

# Start with interactive web inspection dashboard (port 8081)
holon-coherence start --web

# Check container status
holon-coherence status

# Stream container logs
holon-coherence logs -f

# Stop proxy container
holon-coherence stop
```

---

### 3. Automated Coding Agent Runners

`holon-coherence` provides first-class coding agent runners that automatically launch the optimization proxy in the
background, configure proxy routing and certificate trust, map universal credentials, and execute the agent with full
wire telemetry and token optimization enabled:

```bash
# Run Antigravity agent (interactive or CLI mode)
holon-coherence agy
holon-coherence agy -p "Refactor authentication flow"

# Run Claude Code agent
holon-coherence claude
holon-coherence claude --dangerously-skip-permissions

# Run OpenAI Codex / ChatGPT CLI agent
holon-coherence codex

# Run OpenCode agent
holon-coherence opencode

# Run Inflection Pi agent
holon-coherence pi

# Generic runner syntax
holon-coherence run-agent <agent> [agent_args...]
```

#### Universal Credentials (`HOLON_AGENT_KEY`) & Native Auth Fallback

- **Universal Credential**: Provide `HOLON_AGENT_KEY` in your host environment or inline:
  - `agy`: mapped internally to `GEMINI_API_KEY` and `AGY_USER_TOKEN`.
  - `claude`: mapped internally to `ANTHROPIC_API_KEY`.
  - `codex`: mapped internally to `OPENAI_API_KEY`.
  - `opencode`: mapped internally to `OPENCODE_API_KEY`.
  - `pi`: mapped internally to `PI_API_KEY`.
- **Native Auth Fallback**: If `HOLON_AGENT_KEY` is omitted, the runner does not inspect or require vendor API keys;
  child subprocesses transparently inherit existing host authentication sessions (such as `~/.gemini`, `~/.claude.json`,
  or native OAuth tokens).

#### Proxy Lifecycle & Teardown Policy

- **Background Daemon Mode (Default)**: The proxy container starts once in detached mode and stays running across
  invocations to eliminate container startup latency.
- **Ephemeral Teardown (`--ephemeral`)**: Pass `--ephemeral` to automatically stop and remove the proxy container when
  the agent process exits:
  ```bash
  holon-coherence agy --ephemeral -p "Run single task"
  ```
- **On-Demand Teardown (`holon-coherence stop`)**: Stops and removes the background container at any time:
  ```bash
  holon-coherence stop
  ```
- **Port Allocation & Conflict Detection**: Configure the proxy port via `--port <port>` or the `HOLON_PROXY_PORT`
  environment variable (default: `8080`). Port conflicts are detected during startup with actionable guidance.
- **Interactive TTY & Signal Forwarding**: Full interactive TTY attachment (`sys.stdin`, `sys.stdout`, `sys.stderr`)
  preserves ANSI styling, cursor controls, readline prompts, and terminal resize events (`SIGWINCH`), with clean exit
  code propagation.

---

### 4. Alternative: Direct Docker Invocation

If you prefer to invoke Docker directly without using the Python CLI wrapper:

```bash
# Build local container
docker build -t holon-coherence:latest .

# Run container
docker run --name holon-coherence --rm -it \
  -p 127.0.0.1:8080:8080 \
  -p 127.0.0.1:8081:8081 \
  -v ~/.holon/proxy-ca:/home/mitmproxy/.mitmproxy \
  -v ~/.holon/cache:/home/mitmproxy/.holon/cache \
  -v ~/.holon/logs:/tmp/wire_logs \
  holon-coherence:latest
```

### 4. Connect Any Agent (Inline Execution)

> [!IMPORTANT] **Why Inline Proxy Execution instead of `export`?**
>
> 1. **Prevents Terminal Session Contamination**: Running `export HTTP_PROXY=...` persists environment variables across
>    your entire interactive shell session. Subsequent unrelated CLI operations (such as `git clone`, `uv sync`,
>    `npm install`, `docker pull`, or `curl`) will attempt to route through the local proxy, failing or causing
>    connection errors if the proxy is stopped or if upstream registries reject MITM certificates.
> 2. **Deterministic Process Isolation**: Passing properties inline (or via `holon-coherence run`) binds proxy routing
>    and custom CA certificate bundles exclusively to the target agent process and its immediate subprocesses. Once the
>    agent exits, your terminal session remains in a clean, pristine state.
> 3. **Eliminates Cross-Tool Side Effects**: Different CLI runtimes handle proxy authentication, TLS trust, and timeouts
>    differently. Scoping proxy configuration strictly per command invocation eliminates elusive session-level debugging
>    issues.

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

All outbound LLM traffic (Anthropic, Google Gemini, OpenAI) is automatically optimized, cached, and recorded without
altering your terminal's persistent state.

---

## 🛠 Development & Worktree Workflow

When developing or executing tasks on `holon-coherence` within the Holon agentic workspace, use Git worktrees branched
off `origin/main` to maintain clean process and branch isolation:

```bash
# From the repository root (or any active worktree root), sync with origin:
git fetch origin main

# Create a dedicated worktree for your feature branch
git worktree add --no-track -b feat/<feature-name> ../feat-<feature-name> origin/main

# Navigate to worktree
cd ../feat-<feature-name>

# Run test suite
uv run task test
```

### Developer Tasks (`taskipy`)

Lifecycle and code quality tasks are managed via `taskipy`:

| Task Command              | Description                                                    |
| :------------------------ | :------------------------------------------------------------- |
| `uv run task test`        | Run unit test suite (excludes integration tests)               |
| `uv run task test-docker` | Run Docker integration test suite                              |
| `uv run task lint`        | Run Ruff linter and formatting checks                          |
| `uv run task fix-ruff`    | Automatically fix Ruff lint and format errors                  |
| `uv run task clean`       | Clean build, cache, and bytecode artifacts (preserves `.venv`) |

For agent behavioral rules, coding standards, and operational guidelines, see [AGENTS.md](AGENTS.md).

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
