# holon-coherence

> **High-coherence, low-entropy optimisation gateway for fractal coding agents.**

`holon-coherence` is part of the **Holon** family of self-improving, fractal intent coding agents, used to optimise LLM
usage, eliminate token waste, and drive informational entropy to zero across autonomous execution loops.

It operates as a wire-level HTTPS interception proxy and optimisation layer, eliminating quadratic context bloat
($O(N^2)$) and cognitive friction transparently via standard proxy routing, requiring **zero code modifications** to the
client agent.

---

## ⚡ Key Capabilities

1. **Context Cleaning & Tool Deduplication**: Intercepts outbound conversation histories, hashes returned tool payloads
   (`cat`, `ls`, file reads via SHA-256), and replaces identical historical outputs with structural tombstones while
   preserving active turns and modified files verbatim.
2. **Hybrid & Semantic Local Cache**: Disk-backed SQLite exact and Jaccard semantic caching that short-circuits repeated
   requests locally at **0 prompt/output tokens and sub-5ms latency**.
3. **Provider Prompt Cache Optimisation**: Anchors static context at the prefix and automatically injects
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
8. **Live Telemetry & Local LLM Adapters**: In-memory cumulative metrics dashboard served at `/holon/`, CLI reporting
   (`holon-coherence metrics`), and transparent protocol translation (Gemini v1beta <-> OpenAI ChatCompletions and
   Anthropic local normalisation) for self-hosted LLM runners.

---

## 📋 Prerequisites & Automated Setup

`holon-coherence` automates prerequisite verification and environment provisioning entirely through the
[`Makefile`](Makefile), avoiding manual installations.

### 1. Automated Prerequisite Verification

Run the automated check to verify all dependencies (Docker CLI, Docker Buildx, Docker daemon, Conda, `uv` inside a Conda
environment, OpenSSL, and `npx` for Prettier). A missing Docker, Conda, `uv` or OpenSSL is a failure (exit 1); a missing
`npx`, or `uv` found on `PATH` only, is an advisory warning (exit 0):

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

- **Conda Environment & `uv`**:

  ```bash
  # Installs Miniforge (if not installed) and provisions the target Conda environment
  # ('holon' unless you ask for another one):
  make create-conda-env

  # Provision a differently named environment instead:
  make create-conda-env CONDA_ENV=custom_dev

  # Activate the environment in your shell:
  conda activate holon
  ```

  The conda targets read the following variables (also listed by `make help`):

  | Variable               | Effect                                                                                                                                                                                                                                                                                                                                               |
  | ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
  | `CONDA_ENV`            | Environment to **read** / report in `make check-prerequisites`. Defaults to the active `$CONDA_DEFAULT_ENV`, or to `holon` when no environment is active.                                                                                                                                                                                            |
  | `CONDA_WRITE_ENV`      | **Derived, not a knob** - set `CONDA_ENV` instead. Environment `make create-conda-env` **writes** to. Defaults to `holon`, and follows `CONDA_ENV` when you pass it (`make create-conda-env CONDA_ENV=<name>`); it never follows an activated `base`.                                                                                                |
  | `CONDA_ALLOW_BASE`     | Deliberate consent to write into `base`. Only counts when typed on the make command line (`make create-conda-env CONDA_ALLOW_BASE=1`); an inherited `CONDA_ALLOW_BASE=1` is ignored, exactly like an inherited `CONDA_ENV=base`.                                                                                                                     |
  | `CONDA_PRUNE`          | `CONDA_PRUNE=1` (or `true`) **on the make command line** adds `--prune` to `conda env update` when the target environment already exists. Off by default, because pruning can remove packages you installed by hand; a `CONDA_PRUNE=1` exported in your shell is ignored, since it would strip an environment this target may never have created.    |
  | `CONDA_PROMPT_TIMEOUT` | Seconds the interactive prompt waits for an answer (default `20`). No answer is a refusal: the target prints what it would have run and exits non-zero. A shell whose `read` cannot time out (`dash`, the Debian/Ubuntu `/bin/sh`) is refused the same way rather than answered on your behalf — run `make create-conda-env CONDA_ENV=<name>` there. |
  | `NONINTERACTIVE`       | `NONINTERACTIVE=1` skips the interactive target-environment prompt and uses the requested `CONDA_ENV` (or the `holon` default). `CI=true` and a non-terminal stdin skip the prompt too.                                                                                                                                                              |

  An existing environment is updated with `conda env update -n <env> -f environment.yml`, a new one is created with
  `conda env create -n <env> -f environment.yml`. Writing to the shared `base` environment stays opt-in and must be
  asked for **in that same invocation**: either `make create-conda-env CONDA_ENV=base` / `CONDA_ALLOW_BASE=1` on the
  command line, or a typed `yes` at the prompt. A variable inherited from the shell (`export CONDA_ENV=base`) is not
  consent — the target refuses and says why. The three knobs differ on purpose: `CONDA_ENV` also honours an exported
  value, because naming the environment you work on is not consent to write to `base`, while `CONDA_ALLOW_BASE` and
  `CONDA_PRUNE` require command-line origin. One qualification to "inherited is never consent": make carries
  command-line assignments into sub-makes through `MAKEFLAGS`, so a value arriving that way still counts as command-line
  origin — `export MAKEFLAGS='CONDA_ENV=base'` is a deliberate act, not inherited state. The `base` route installs `uv`
  and `python=3.13` with `conda install -y -n base -c conda-forge` instead of the full `environment.yml`.

- **Build Docker Container**:

  ```bash
  make build-image
  # Or using the build-images alias:
  make build-images
  ```

- **Toolbelt Inspection & Code Quality**:

  ```bash
  # Inspect OS toolbelt dependencies (git, jq, shellcheck, uv, gh, npx, openssl):
  make tools

  # Run pre-commit secret leak prevention and scratch file detection:
  make pre-commit-check

  # Run comprehensive linters (Prettier, shellcheck, pre-commit-check):
  make lint

  # Run pre-commit checks and linters:
  make check
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

Install `holon-coherence` into your system `$PATH` via `uv` (recommended):

```bash
# Standard installation directly from GitHub repository
uv tool install git+https://github.com/Holon-Agentic-Coder/holon-coherence.git
```

> **Shell Rehashing**: If your shell does not immediately find `holon-coherence` after installation:
>
> - For **zsh**: run `rehash` to immediately refresh command hashing.
> - For **bash**: run `hash -r` to reset remembered shell command locations.

#### For Local Contributors & Development:

For local contributors modifying `holon-coherence`, install from a local checkout using `--editable`:

```bash
git clone https://github.com/Holon-Agentic-Coder/holon-coherence.git
cd holon-coherence
uv tool install --editable .
```

### 2. Manage the Proxy Container

The `holon-coherence` CLI automatically manages Docker images, volumes, certificates, and web credentials for you:

```bash
# Start proxy container (proxy on 8080, token-protected mitmweb inspector on 8081)
holon-coherence start

# Run in background (detached)
holon-coherence start -d

# Headless start: mitmdump only, no inspector port and no token
holon-coherence start --no-web

# Start with an explicit inspector token (defaults to HOLON_COHERENCE_WEB_PASSWORD or an auto-generated token)
holon-coherence start --web-password "custom-secret-key"

# Publish the inspector on another host port (falls back to the next free port if occupied)
holon-coherence start --web-port 9090

# Display the active inspector token and its URL
holon-coherence web-token
# (alias: holon-coherence web-key)

# Check container status (prints every exposed endpoint and a live optimisation summary)
holon-coherence status

# Display cumulative optimisation metrics (tool calls pruned, cache hit rate, TTFT, tokens reduced)
holon-coherence metrics

# Display optimisation metrics as raw JSON (reads from live proxy or falls back to transactions.jsonl)
holon-coherence metrics --json

# Stream container logs
holon-coherence logs -f

# Stop proxy container
holon-coherence stop
```

---

### 3. Automated Coding Agent Runners

`holon-coherence` provides first-class coding agent runners that automatically launch the optimisation proxy in the
background, configure proxy routing and certificate trust, map universal credentials, and execute the agent with full
wire telemetry and token optimisation enabled:

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
  setting `HOLON_CA_CERT=/path/to/ca.pem`. Useful in CI/CD or containerised environments where the Holon CA certificate
  is mounted at a non-default location. Falls back to `~/.holon/proxy-ca/mitmproxy-ca-cert.pem` if unset or if the
  specified file does not exist.
- **Interactive TTY & Signal Forwarding**: Full interactive TTY attachment (`sys.stdin`, `sys.stdout`, `sys.stderr`)
  preserves ANSI styling, cursor controls, readline prompts, and terminal resize events (`SIGWINCH`), with clean exit
  code propagation.

#### Host-Local Model Servers (`--local-llm-base`)

#### Host-Local Model Servers & Protocol Adapters (`--local-llm-base`, `--local-llm-endpoint`, `--model`)

A model server on your own machine (Ollama, vLLM, LM Studio, vMLX, aphrodite, llama.cpp server) can be used as the
inference backend for supported coding agents.

When `--local-llm-base` (or `--local-llm-endpoint`) and `--model` are supplied:

- **Automatic Runner Environment Configuration**:
  - **Claude Code (`claude`)**: The runner sets `ANTHROPIC_BASE_URL` to route through the proxy, supplies a dummy
    `ANTHROPIC_AUTH_TOKEN="local"`, sets `USER="holon"`, and disables telemetry / prompt caching fallbacks.
  - **Antigravity (`agy`)**: The runner routes to the proxy using `AGY_GATEWAY_URL="http://127.0.0.1.nip.io:{port}"`.
    Go's `net/http` client standard library automatically bypasses `HTTP_PROXY` for literal `localhost` and `127.0.0.1`;
    using the `127.0.0.1.nip.io` alias ensures Go routes all requests through the proxy while resolving to loopback.
- **Anthropic Protocol Normaliser**: Local OpenAI/Anthropic-compatible engines often reject proprietary Claude API
  parameters. The proxy automatically normalises outbound requests targeting local endpoints by stripping unsupported
  fields (`thinking`, `output_config`, `context_management`, prompt caching `cache_control` annotations) and removing
  `anthropic-beta` headers.
- **Gemini v1beta <-> OpenAI ChatCompletions Bridge**: For agents emitting Google Gemini v1beta REST requests (such as
  `agy`) targeting OpenAI-compatible local engines:
  - Translates `generateContent` and `streamGenerateContent` into OpenAI `/v1/chat/completions`.
  - Translates function calling declarations (`tools[].functionDeclarations`) to OpenAI `tools[].function`.
  - Translates assistant tool calls (`functionCall`) and user tool outputs (`functionResponse`) bidirectionally.
  - Translates OpenAI Server-Sent Events (SSE) streaming chunks and final finish reasons back to Gemini candidates
    format.
  - Zero modifications to cloud Gemini API calls (`generativelanguage.googleapis.com`).

```bash
# Run Claude Code with local model server
holon-coherence claude --local-llm-base http://localhost:8000/v1 --model qwen2.5-coder-32b

# Run AGY with local model server
holon-coherence agy --local-llm-base http://localhost:8000/v1 --model qwen2.5-coder-32b

# Run Pi with local model server
holon-coherence pi --local-llm-base localhost:11434 --model ollama/llama3
```

A model server on your own machine is unreachable through a containerized proxy in two separate ways: the runner's
default `NO_PROXY` contains `localhost`, so the agent never asks the proxy at all, and even when it does, `localhost`
resolves to the container and the host's LAN address is unroutable from the Docker Desktop VM. Declaring the endpoint
handles both:

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
  Note also that `start` publishes the mitmweb inspector on port 8081 by default. When `--local-llm-base` names a port,
  the inspector never takes it and falls back to the next free port instead, so a model server on 8081 keeps its port.
  Pass `--web-port` to choose another inspector port, or `--no-web` to publish none.

---

### 4. Real-Time Web & CLI Metrics Dashboard

`holon-coherence` includes an in-memory cumulative optimisation metrics engine and real-time dashboard served directly
by the proxy without requiring external databases or third-party monitoring stacks.

#### Interactive Web Dashboard

Open `http://127.0.0.1:8080/holon/` in your browser (substituting your configured proxy port) to view the live dark-mode
dashboard:

- **Optimisation Cards**: Real-time counters for tool calls pruned/saved, tokens reduced, cache hit rate, average TTFT
  latency, prefill throughput, and decode throughput.
- **Token Usage Breakdown**: Input tokens, model output tokens, cache read tokens, and characters saved.
- **Live Updating**: Polls the proxy's lightweight JSON endpoint (`/holon/api/metrics`) every 3 seconds.

#### Terminal Metrics CLI

Inspect cumulative optimisation performance directly in the terminal:

```bash
# Formatted terminal summary
holon-coherence metrics

# Raw JSON telemetry output (ideal for automation, scripts, and scorecards)
holon-coherence metrics --json
```

If the proxy is offline, `holon-coherence metrics` automatically falls back to calculating cumulative statistics from
the persisted wire transaction ledger (`transactions.jsonl`).

#### Inspecting Live Traffic with mitmweb

A plain `holon-coherence start` also runs the plain mitmweb request/response inspector next to the proxy. Use it to
look at individual flows as they happen, before any aggregation:

- **Requests**: method, full URL, request headers and the request body as Coherence forwards it, after payload
  cleaning.
- **Responses**: status code, response headers and the response body. Streamed (SSE) responses are relayed to the
  agent as they arrive, so for those mitmweb shows the status and headers but not the streamed body.
- **Cache status**: responses carry `X-Holon-*` telemetry headers. A response served from the Coherence cache has a
  `200` status with `X-Holon-TTFT-Ms: 0.00` and `X-Holon-Total-Time-Ms: 0.00`, while an upstream response carries the
  measured `X-Holon-TTFT-Ms`, `X-Holon-Streaming` and throughput headers. `X-Holon-Cache-Hit-Rate` shows the running
  hit rate. Provider-side prompt caching shows up in the response body's `usage` block.
- **TLS details**: the flow's Connection tab shows the client and server connections, including TLS version, cipher,
  SNI and the upstream server certificate.

**Opening it.** `start` prints the URL, in the form `http://127.0.0.1:<web_port>/?token=<token>`, in its endpoint
block. Open that URL in a browser. `holon-coherence web-token` (or `status`) prints it again later.

**How the token is resolved.** The first of these wins: `--web-password`, then the `HOLON_COHERENCE_WEB_PASSWORD`
environment variable, then a freshly generated random token (`secrets.token_urlsafe(16)`). It is saved to
`~/.holon/web-token` with mode `0600` and passed to mitmweb as `web_password`, so the UI never runs unauthenticated.
The full URL with the token is printed only to your terminal by `start`, `status`, the `metrics` table and `web-token`.
It is never printed in `metrics --json` output, in the container's own output (`docker logs` shows the token as
hidden), or in the wire logs, where `token=` query values are redacted by the existing secret scrubbing.

> [!WARNING] The inspector shows **raw, unscrubbed traffic**, including `Authorization` headers and API keys, because
> it renders the live flows themselves. Wire-log scrubbing applies to what is persisted and is unaffected. The inspector
> is published on `127.0.0.1` only and is token-gated. Do not re-publish it on another interface. Use `--no-web` when
> you do not need it, for example on shared machines.

**Opting out.** `holon-coherence start --no-web` runs a headless, mitmdump-only proxy with no inspector port and no
token. The background proxies started by `holon-coherence run`, `run-agent` and the agent shortcuts (for example
`holon-coherence claude`) are always headless. `--web` is still accepted and has the same meaning as the default.

**How endpoints and ports are reported.** The inspector defaults to host port `8081` (`--web-port` overrides it). If
that port is busy, or it is the proxy port or the `--local-llm-base` port, `start` falls back to the next free port
and says so. `start`, `status` and `metrics` print the ports actually in use, in the same table layout:

```text
----------------------------------------------------------------
  Exposed Endpoints
  Proxy Listen Address         : 127.0.0.1:8080
  Coherence Live Dashboard     : http://127.0.0.1:8080/holon/
  mitmweb Req/Resp Inspector   : http://127.0.0.1:8081/?token=<token>
----------------------------------------------------------------
```

`status` and `metrics` read the ports from the running container's Docker port mappings. When the container is down,
or was started with `--no-web`, the inspector row reads `not running` rather than repeating an old URL from
`~/.holon/web-token`.

---

### 5. A/B Testing & Token Reduction Verification Suite

`holon-coherence ab-test` runs differential benchmarking over recorded authentic transaction traces to empirically
validate token reduction, character savings, tool output deduplication, and TTFT deltas between raw baseline and
optimized requests.

```bash
# Run A/B differential benchmark over recorded trace transactions
holon-coherence ab-test -f ~/.holon/wire_logs/transactions.jsonl

# Enforce minimum token reduction gate in CI (fails if reduction < 15%)
holon-coherence ab-test -f transactions.jsonl --fail-under-reduction 15.0

# Export structured JSON scorecard for analytics pipelines
holon-coherence ab-test -f transactions.jsonl --json > scorecard.json
```

See the [A/B Testing Guide](docs/ab_testing_guide.md) for full benchmark configuration, scorecard metric definitions,
and CI integration patterns.

---

### 6. Alternative: Direct Docker Invocation

If you prefer to invoke Docker directly without using the Python CLI wrapper:

```bash
# Build local container
docker build -t holon-coherence:latest .

# Run container (headless: the image's default command runs mitmdump only)
docker run --name holon-coherence --rm -it \
  -p 127.0.0.1:8080:8080 \
  -v ~/.holon/proxy-ca:/home/mitmproxy/.mitmproxy \
  -v ~/.holon/cache:/home/mitmproxy/.holon/cache \
  -v ~/.holon/logs:/tmp/wire_logs \
  holon-coherence:latest

# Run container with the mitmweb inspector at http://127.0.0.1:8081/?token=<token>
docker run --name holon-coherence --rm -it \
  -p 127.0.0.1:8080:8080 \
  -p 127.0.0.1:8081:8081 \
  -e HOLON_COHERENCE_WEB_PASSWORD="<token>" \
  -v ~/.holon/proxy-ca:/home/mitmproxy/.mitmproxy \
  -v ~/.holon/cache:/home/mitmproxy/.holon/cache \
  -v ~/.holon/logs:/tmp/wire_logs \
  holon-coherence:latest start --port 8080 --web --web-port 8081
```

### 7. Connect Any Agent (Inline Execution)

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

All outbound LLM traffic (Anthropic, Google Gemini, OpenAI) is automatically optimised, cached, and recorded without
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
- [A/B Testing & Token Reduction Verification Guide](docs/ab_testing_guide.md)
- [A/B Testing & Efficacy Verification (Background)](docs/token_reduction_ab_testing.md)
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
