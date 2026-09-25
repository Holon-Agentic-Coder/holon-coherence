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

# Pass flags directly to underlying agent CLI using '--'
holon-coherence agy -- --help
holon-coherence claude -- --dangerously-skip-permissions

# Generic runner syntax
holon-coherence run-agent <agent> [agent_args...]
```

#### Direct Flag Passthrough (`--`)

To pass flags directly to child agent binaries without them being intercepted or parsed as runner options, use the
standard `--` delimiter:

```bash
# Pass help flag to agent binary rather than holon-coherence runner
holon-coherence agy -- --help

# Forward agent-specific flags directly to child agent CLI
holon-coherence claude -- --dangerously-skip-permissions
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
  the agent process exits. Pre-existing proxy containers are preserved when `--ephemeral` is used to avoid disrupting
  concurrent sessions:
  ```bash
  holon-coherence agy --ephemeral -p "Run single task"
  ```
- **On-Demand Teardown (`holon-coherence stop`)**: Stops and removes the background container at any time:
  ```bash
  holon-coherence stop
  ```
- **Port Allocation & Conflict Detection**: Configure the proxy port via `--port <port>` or the `HOLON_PROXY_PORT`
  environment variable (default: `8080`). Port conflicts are detected during startup with actionable guidance.
- **Custom CA Certificate (`HOLON_CA_CERT`)**: Override the default CA certificate path used for TLS bundle merging by
  setting `HOLON_CA_CERT=/path/to/ca.pem`. Useful in CI/CD or containerized environments where the Holon CA certificate
  is mounted at a non-default location. Falls back to `~/.holon/proxy-ca/mitmproxy-ca-cert.pem` if unset or if the
  specified file does not exist.
- **Interactive TTY & Signal Forwarding**: Full interactive TTY attachment (`sys.stdin`, `sys.stdout`, `sys.stderr`)
  preserves ANSI styling, cursor controls, readline prompts, and terminal resize events (`SIGWINCH`), with clean exit
  code propagation.

#### Host-Local Model Servers (`--local-llm-base`)

A model server on your own machine (Ollama, vMLX, LM Studio, vLLM) is unreachable through a containerized proxy in two
separate ways: the runner's default `NO_PROXY` contains `localhost`, so the agent never asks the proxy at all, and even
when it does, `localhost` resolves to the container and the host's LAN address is unroutable from the Docker Desktop VM.
Declare the endpoint and both are handled:

```bash
holon-coherence pi --local-llm-base=localhost:11434 -- -p "Summarize this repo" --model=ollama/llama3
holon-coherence agy --local-llm-base=http://127.0.0.1:11434/v1 -- -p "Run single task" --model=ollama/llama3

# or configure via environment variable:
export HOLON_LOCAL_LLM_BASE=localhost:11434
holon-coherence pi -- -p "Summarize this repo" --model=ollama/llama3
```

> [!NOTE] `--local-llm-base` (or environment variable `HOLON_LOCAL_LLM_BASE`) configures **proxy routing, container
> gateway dialing and `NO_PROXY` pruning** only. It does not point the agent at the model: you still pass the agent's
> own model arguments (`--model`, `OPENAI_BASE_URL`, or the agent's config file) so its client library targets that
> endpoint. The flag decides what the proxy does with the requests that endpoint generates.

- **One endpoint, every spelling**: `localhost:11434`, `127.0.0.1:11434`, `[::1]:11434` and the host's own LAN address
  are treated as the same machine and are all routed to `host.docker.internal:<port>` inside the container, preserving
  the port. `--local-llm-base` accepts `host:port` or a whole base URL.
- **Interception, not bypass**: the matching `NO_PROXY` entries are removed from the agent's environment so requests
  reach the proxy and receive payload cleaning, response caching and wire telemetry. Requests keep their original
  authority in the wire logs (only the dial target changes), so `endpoint` still reads
  `http://localhost:11434/v1/chat/completions`.
- **Never hijacks a real peer**: only loopback plus the declared address (and the host's own detected addresses) are
  rewritten. Other RFC1918 hosts, public endpoints and link-local addresses are left untouched, so a genuinely remote
  inference box on the LAN cannot be silently redirected onto the host. The port the proxy itself is published on is
  also never rewritten -- do not run the model server on the proxy port.
- **Verified before it changes anything**: pruning happens only after the proxy container proves it can dial the
  endpoint through the host gateway. If it cannot, `NO_PROXY` is left alone and the CLI prints why -- a working direct
  call is preferred over a broken proxied one. A server bound only to `127.0.0.1` (Ollama's default on Linux) needs
  `OLLAMA_HOST=0.0.0.0` (or `systemctl edit ollama.service`) to become interceptable that way.
- **Shared proxy**: the allow list is part of the container's environment. When a running container does not cover a
  newly required endpoint, it is recreated with the union of existing and new targets. Use `--ephemeral` when running
  concurrent isolated sessions against different endpoints.
- **Standalone proxy**: `holon-coherence start` accepts `--local-llm-base` directly on the CLI, reads the fallback
  endpoint from `HOLON_LOCAL_LLM_BASE`, or reads the allow list from `HOLON_HOST_LOCAL_HOSTS`:
  ```bash
  holon-coherence start --local-llm-base localhost:11434
  # or via fallback environment variable:
  HOLON_LOCAL_LLM_BASE=localhost:11434 holon-coherence start
  # or via raw container allow list:
  HOLON_HOST_LOCAL_HOSTS="localhost:11434,127.0.0.1:11434" holon-coherence start
  ```
  Nothing prunes `NO_PROXY` for you in this mode, because no runner is launching the agent: your shell's `NO_PROXY` must
  not match the local endpoint (drop `localhost` / `127.0.0.1` from it) or the host client bypasses the proxy entirely.
  Note also that `start --web` publishes the dashboard on port 8081, so a model server on 8081 needs a different
  `--web-port` or a different server port.

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

### 5. Connect Any Agent (Inline Execution)

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
