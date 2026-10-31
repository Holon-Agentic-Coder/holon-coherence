# Plan for I-1793334806-coherence-commands-register-their-own-parsers

- **Plan ID:** P-1793334823-antigravity-agent-gemini-3.8-flash-medium
- **Parent Intent ID:** NONE
- **Agent:** antigravity-agent (version: 1.4.10)
- **Created At:** 2026-10-30T04:33:44.494Z

---

## Overall Plan Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.95  |
| entropy_pred        | 3.20  |
| impact_pred         | 8.50  |
| cost_pred           | 0.90  |
| learning_value_pred | 2.00  |
| ev_pred             | 7.22  |

---

## Step 1: Define Command Protocol and Refactor `ca.py` and `runner.py`

### Step Intent & Git Integration

- **Sub-intent recommendation:** none (monolithic execution within intent scope)
- **Reasoning:** Establishing the standardized `register(subparsers)` and `handle(args)` signature on the first two
  command modules (`ca.py` and `runner.py`) provides the template for eliminating `commands/_dispatch.py` and replacing
  dynamic `get_cli()` lookups with clean collaborator injection.
- **Step type:** implementation
- **Exploration level:** 0.05
- **Git branch:** `I-1793334806-coherence-commands-register-their-own-parsers`

### Implementation Details

1. **Protocol Definition**:
   - Establish the standard command registration and invocation interface across all command modules:
     ```python
     def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> argparse.ArgumentParser: ...
     def handle(args: argparse.Namespace) -> int: ...
     ```
   - Each subparser sets `parser.set_defaults(handler=handle)` to enable direct subparser-to-handler dispatch.

2. **Refactor `src/holon_coherence/commands/ca.py`**:
   - Implement `register(subparsers: Any) -> argparse.ArgumentParser`:
     - Creates subparser for `"init-ca"` with description `"Bootstrap self-signed Root CA certificates"`.
     - Adds `--output-dir` argument with default `os.path.expanduser("~/.holon/proxy-ca")`.
     - Sets default handler `ca_parser.set_defaults(handler=handle)`.
   - Implement `handle(args: Any) -> int`:
     - Invokes `handle_init_ca(args)` and returns the exit code `0`.
   - Eliminate `from holon_coherence.commands._dispatch import get_cli`.
   - Refactor
     `get_or_create_merged_ca_bundle(ca_cert_path: str, find_bundle_fn: Callable[[], str | None] = find_system_ca_bundle)`:
     - Remove `cli = get_cli()`, `getattr(cli, "find_system_ca_bundle", find_system_ca_bundle)`.
     - Use `find_bundle_fn` directly.

3. **Refactor `src/holon_coherence/commands/runner.py`**:
   - Implement `register(subparsers: Any) -> argparse.ArgumentParser`:
     - Creates subparser for `"run"` with description
       `"Run a command with inline proxy properties (avoids terminal session contamination)"`.
     - Adds `--proxy-url` (default `"http://127.0.0.1:8080"`), `--ca-cert` (default
       `~/.holon/proxy-ca/mitmproxy-ca-cert.pem`), and positional `cmd` (`nargs=argparse.REMAINDER`).
     - Sets default handler `run_parser.set_defaults(handler=handle)`.
   - Implement `handle(args: Any) -> int`:
     - Dispatches directly to `handle_run(args)` returning the child process exit code.
   - Eliminate `from holon_coherence.commands._dispatch import get_cli`.
   - In `build_proxy_env`:
     - Replace dynamic lookups with explicit parameters having sensible defaults:
       ```python
       def build_proxy_env(
           proxy_url: str,
           ca_cert_path: str | None = None,
           drop_no_proxy: tuple[str, ...] = (),
           *,
           merge_no_proxy_fn: Callable[[dict[str, str] | None], str] = merge_no_proxy_values,
           bundle_getter_fn: Callable[[str], str] = get_or_create_merged_ca_bundle,
       ) -> dict[str, str]:
       ```
   - In `handle_run`:
     - Replace `get_cli()` dynamic lookups with explicit parameters:
       ```python
       def handle_run(
           args: Any,
           *,
           env_builder_fn: Callable[..., dict[str, str]] = build_proxy_env,
           exec_proc_fn: Callable[[list[str], dict[str, str]], int] = execute_interactive_process,
       ) -> int:
       ```
   - Enforce McCabe complexity $C901 \le 10$ across all refactored functions.

### Dependencies & Criticality

- **Dependencies:** None
- **Is bottleneck:** Yes — Establishes the decoupled dependency injection and command registration pattern for
  subsequent command modules.

### Safety & Constraint Considerations

- **Relevant rules:** §2 Coding Conventions & Standards (PEP 8, full typing, docstring preservation, Ruff cleanliness),
  Rule 2 (Inline Proxy Process Isolation).
- **Failure modes:** Circular imports between `ca.py` and `runner.py`, or broken argument parsing when `run` receives
  subcommands after `--`.
- **Guardrails:** Keep positional `cmd` argument parsing matching `nargs=argparse.REMAINDER` exactly. Use local function
  defaults rather than top-level cyclical module imports.

### Success & Discard Criteria

- **Success:** Both `ca.py` and `runner.py` export `register(subparsers)` and `handle(args)`, zero references to
  `_dispatch.py` or `get_cli()` remain in either module, and all unit tests for CA and Runner functionality pass.
- **Discard:** Discard if parameter defaults introduce circular import cycles at module load time.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.98  |
| entropy_pred        | 0.50  |
| impact_pred         | 8.00  |
| cost_pred           | 0.15  |
| learning_value_pred | 1.00  |
| ev_pred             | 8.04  |

### Step Metrics Rationale

- $\text{EV} = 0.98 \times 8.00 + 0.5 \times 1.00 - 0.3 \times 0.50 - 0.15 = 7.84 + 0.50 - 0.15 - 0.15 = 8.04$. Initial
  protocol standardization on two self-contained modules carries high clarity and minimal regression risk.

---

## Step 2: Refactor `docker_ops.py`, `endpoints.py`, and `web_token.py`

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Decouple Docker container lifecycle, endpoint formatting, and web-token management commands from the
  dynamic locator, migrating their subparser registrations directly into their respective modules.
- **Step type:** implementation
- **Exploration level:** 0.05
- **Git branch:** `I-1793334806-coherence-commands-register-their-own-parsers`

### Implementation Details

1. **Refactor `src/holon_coherence/commands/endpoints.py`**:
   - Eliminate `from holon_coherence.commands._dispatch import get_cli`.
   - Update `resolve_container_endpoints` signature to receive collaborators directly with defaults:
     ```python
     def resolve_container_endpoints(
         container_name: str,
         fallback_proxy_port: int | None = None,
         *,
         is_running_fn: Callable[[str], bool] = is_container_running,
         get_mapped_port_fn: Callable[[str, int], int | None] = get_container_mapped_port,
         get_token_fn: Callable[[str], str | None] = get_container_web_token,
     ) -> ExposedEndpoints:
     ```
   - Retain full docstrings and typing annotations.

2. **Refactor `src/holon_coherence/commands/docker_ops.py`**:
   - Implement `register(subparsers: Any) -> list[argparse.ArgumentParser]`:
     - Register `build` subparser (`--tag` option, default `"holon-coherence:latest"`).
     - Register `stop` subparser (`--name` option).
     - Register `status` subparser (`--name` option).
     - Register `logs` subparser (`-f`/`--follow` flag, `--name` option).
     - Set `parser.set_defaults(handler=handle)` on all 4 parsers.
   - Implement `handle(args: Any) -> int`:
     - Dispatch based on `args.command`:
       ```python
       def handle(args: Any) -> int:
           cmd = getattr(args, "command", None)
           if cmd == "build":
               return handle_build(args)
           if cmd == "stop":
               return handle_stop(args)
           if cmd == "status":
               return handle_status(args)
           if cmd == "logs":
               return handle_logs(args)
           return 1
       ```
   - Eliminate `from holon_coherence.commands._dispatch import get_cli`.
   - In `handle_status`:
     - Replace dynamic `cli` lookups with explicit parameters:
       ```python
       def handle_status(
           args: Any = None,
           *,
           is_running_fn: Callable[[str], bool] = is_container_running,
           resolve_endpoints_fn: Callable[..., ExposedEndpoints] = resolve_container_endpoints,
       ) -> int:
       ```
   - Comply with Ruff complexity limits ($C901 \le 10$, $PLR0912 \le 12$, $PLR0915 \le 50$).

3. **Refactor `src/holon_coherence/commands/web_token.py`**:
   - Implement `register(subparsers: Any) -> list[argparse.ArgumentParser]`:
     - Register both `"web-token"` and `"web-key"` subparsers with `--name` argument.
     - Set `parser.set_defaults(handler=handle)`.
   - Implement `handle(args: Any) -> int`:
     - Call `handle_web_token(args)`.
   - Eliminate `from holon_coherence.commands._dispatch import get_cli`.
   - In `handle_web_token`:
     - Provide explicit collaborator defaults:
       ```python
       def handle_web_token(
           args: Any = None,
           token_path: str = WEB_TOKEN_PATH,
           *,
           tok_getter_fn: Callable[[str], str | None] = get_active_web_token,
           container_tok_getter_fn: Callable[[str], str | None] = get_container_web_token,
           is_running_fn: Callable[[str], bool] = is_container_running,
           get_mapped_port_fn: Callable[[str, int], int | None] = get_container_mapped_port,
       ) -> int:
       ```

### Dependencies & Criticality

- **Dependencies:** Step 1
- **Is bottleneck:** No

### Safety & Constraint Considerations

- **Relevant rules:** §2 Coding Conventions & Standards, Rule 6 (Live Telemetry & Metrics Verification).
- **Failure modes:** Circular dependency between `endpoints.py` and `docker_ops.py`.
- **Guardrails:** Keep `endpoints.py` imports of `docker_ops.py` clean by passing functions as defaults or local imports
  where appropriate.

### Success & Discard Criteria

- **Success:** `docker_ops.py` and `web_token.py` export `register(subparsers)` and `handle(args)`, zero `get_cli()`
  calls remain in `docker_ops.py`, `endpoints.py`, and `web_token.py`, and container status/token reporting functions
  properly.
- **Discard:** Discard if circular import occurs upon importing `holon_coherence.commands.docker_ops` or
  `holon_coherence.commands.endpoints`.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.98  |
| entropy_pred        | 0.50  |
| impact_pred         | 8.00  |
| cost_pred           | 0.15  |
| learning_value_pred | 1.00  |
| ev_pred             | 8.04  |

### Step Metrics Rationale

- $\text{EV} = 0.98 \times 8.00 + 0.5 \times 1.00 - 0.3 \times 0.50 - 0.15 = 7.84 + 0.50 - 0.15 - 0.15 = 8.04$.
  Decoupling the container lifecycle and endpoint utilities removes 5 of the 15 `get_cli()` call sites without interface
  regressions.

---

## Step 3: Refactor `start.py`, `metrics.py`, `agents.py`, and `ab_test.py`

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Complete parser registration and collaborator decoupling across the remaining command modules (`start`,
  `metrics`, `agents`, `ab_test`), eliminating the final `get_cli()` call sites in the repository.
- **Step type:** implementation
- **Exploration level:** 0.05
- **Git branch:** `I-1793334806-coherence-commands-register-their-own-parsers`

### Implementation Details

1. **Refactor `src/holon_coherence/commands/start.py`**:
   - Implement `register(subparsers: Any) -> argparse.ArgumentParser`:
     - Register `start` subparser with help `"Start the optimization proxy sidecar (via Docker by default)"`.
     - Register arguments: `--port`, `--local-llm-base`, `--web` (`argparse.BooleanOptionalAction`), `--web-port`,
       `--web-password`, `-d`/`--detach`, `--name`, `--image`, `--passive`, `--build`.
     - Set `start_parser.set_defaults(handler=handle)`.
   - Implement `handle(args: Any) -> int`:
     - Dispatches to `handle_start(args)`.
   - Eliminate `from holon_coherence.commands._dispatch import get_cli`.
   - In `handle_start` and `ensure_proxy_running`:
     - Eliminate `cli = get_cli()` and `getattr(cli, ...)` calls.
     - Supply explicit parameters with direct default callables:
       - `in_use_fn: Callable[[int], bool] = is_port_in_use`
       - `find_port_fn: Callable[[int], int] = find_available_port`
       - `ensure_image_fn: Callable = ensure_docker_image`
       - `resolve_pwd_fn: Callable = resolve_web_password`
       - `save_tok_fn: Callable = save_web_token`
       - `wait_proxy_fn: Callable = wait_for_proxy_ready`
       - `stop_container_fn: Callable = stop_proxy_container`
       - `check_daemon_fn: Callable = check_docker_daemon`
   - Preserve complexity limits ($C901 \le 10$).

2. **Refactor `src/holon_coherence/commands/metrics.py`**:
   - Implement `register(subparsers: Any) -> argparse.ArgumentParser`:
     - Register `metrics` subparser with arguments `--port`, `--name`, `--offline`, `--json`.
     - Set `metrics_parser.set_defaults(handler=handle)`.
   - Implement `handle(args: Any) -> int`:
     - Dispatches to `handle_metrics(args)`.
   - Eliminate `from holon_coherence.commands._dispatch import get_cli`.
   - In `handle_metrics`:
     - Replace dynamic `get_cli()` resolution with explicit parameter default:
       ```python
       resolve_endpoints_fn: Callable[..., ExposedEndpoints] = resolve_container_endpoints
       ```

3. **Refactor `src/holon_coherence/commands/agents.py`**:
   - Implement `register(subparsers: Any) -> list[argparse.ArgumentParser]`:
     - Register `"run-agent"` subparser (`agent`, `--ephemeral`, `--port`, `--model`, `--local-llm-base`,
       `--local-llm-endpoint`, `agent_args`).
     - Register subparser for each agent alias in `SUPPORTED_AGENTS` (`agy`, `claude`, `codex`, `opencode`, `pi`).
     - Set `parser.set_defaults(handler=handle)` on all registered parsers.
   - Implement `handle(args: Any) -> int`:
     - Dispatches to `run_agent` based on `args.command` or `args.agent`.
   - Eliminate `from holon_coherence.commands._dispatch import get_cli`.
   - In `run_agent`:
     - Provide explicit collaborator defaults:
       ```python
       def run_agent(
           agent_name: str,
           agent_args: list[str],
           ephemeral: bool = False,
           port: int | None = None,
           local_llm_base: str | None = None,
           model: str | None = None,
           *,
           resolve_bin_fn: Callable[[str], str | None] = resolve_agent_binary,
           plan_route_fn: Callable[[str], LocalLlmRoute | None] = plan_local_llm_route,
           ensure_proxy_fn: Callable[..., bool] = ensure_proxy_running,
           probe_host_fn: Callable[[LocalLlmRoute], bool] = probe_host_local_reachable,
           report_route_fn: Callable[[LocalLlmRoute, bool], None] = report_local_llm_route,
           build_env_fn: Callable[..., dict[str, str]] = build_agent_env,
           exec_proc_fn: Callable[[list[str], dict[str, str]], int] = execute_interactive_process,
           stop_container_fn: Callable[[str | None], bool] = stop_proxy_container,
       ) -> int:
       ```

4. **Refactor `src/holon_coherence/commands/ab_test.py`**:
   - Implement `register(subparsers: Any) -> argparse.ArgumentParser`:
     - Register `ab-test` subparser with arguments `--command`/`-c`, `--trace-file`/`-f`, `--live`, `--baseline`,
       `--optimized`, `--rounds`/`-n`, `--fail-under-reduction`, `--json`.
     - Set `ab_parser.set_defaults(handler=handle)`.
   - Implement `handle(args: Any) -> int`:
     - Calls `handle_ab_test(args)`.

### Dependencies & Criticality

- **Dependencies:** Step 1, Step 2
- **Is bottleneck:** Yes — All command modules must be refactored before `_dispatch.py` can be removed.

### Safety & Constraint Considerations

- **Relevant rules:** Rule 1 (Zero Synthetic / Mock Data for Benchmarking), Rule 3 (Coding Agent Runners & Automated
  Proxy), Rule 4 (Universal Credentials & Native Auth Fallback).
- **Failure modes:** Subtle divergence in subparser help strings or default argument values break existing CLI options.
- **Guardrails:** Keep exact subparser argument names, choices, help strings, and default values identical to existing
  definitions.

### Success & Discard Criteria

- **Success:** All 8 command modules export `register(subparsers)` and `handle(args)`, zero occurrences of `get_cli`
  exist in any command module, and unit tests for start, metrics, agents, and ab-test run successfully.
- **Discard:** Discard if any command argument flag is dropped or altered.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.95  |
| entropy_pred        | 0.60  |
| impact_pred         | 8.50  |
| cost_pred           | 0.20  |
| learning_value_pred | 1.50  |
| ev_pred             | 8.45  |

### Step Metrics Rationale

- $\text{EV} = 0.95 \times 8.50 + 0.5 \times 1.50 - 0.3 \times 0.60 - 0.20 = 8.075 + 0.75 - 0.18 - 0.20 = 8.45$.
  Completes the core modularization across the largest modules in the codebase, enabling clean deletion of
  `_dispatch.py`.

---

## Step 4: Remove `_dispatch.py` and Refactor `cli.main` into Slim Dispatcher

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Delete the `commands/_dispatch.py` dynamic service locator completely, transform `cli.main` into a
  slim, low-complexity dispatcher, and ratchet down the Bean 0186 complexity ceiling.
- **Step type:** refactoring
- **Exploration level:** 0.05
- **Git branch:** `I-1793334806-coherence-commands-register-their-own-parsers`

### Implementation Details

1. **Delete `src/holon_coherence/commands/_dispatch.py`**:
   - Remove file `src/holon_coherence/commands/_dispatch.py`.
   - Ensure zero residual references to `_dispatch` or `get_cli` remain anywhere in `src/`.

2. **Slim Down `src/holon_coherence/cli.py`**:
   - Define canonical module registry:
     ```python
     COMMAND_MODULES = (
         start,
         docker_ops,
         agents,
         runner,
         ca,
         metrics,
         ab_test,
         web_token,
     )
     ```
   - Implement concise `build_parser() -> argparse.ArgumentParser`:
     ```python
     def build_parser() -> argparse.ArgumentParser:
         parser = argparse.ArgumentParser(
             prog="holon-coherence",
             description="High-coherence, low-entropy optimization gateway for fractal coding agents.",
         )
         subparsers = parser.add_subparsers(dest="command", help="Available commands")
         for cmd_mod in COMMAND_MODULES:
             cmd_mod.register(subparsers)
         return parser
     ```
   - Extract agent fast-path into a helper `_dispatch_agent_argv(argv: list[str]) -> bool`:
     - Checks if `argv[0] in SUPPORTED_AGENTS` or `argv[0] == "run-agent"` and dispatches using `extract_runner_flags`
       and `run_agent`.
   - Refactor `main(argv: list[str] | None = None) -> None`:

     ```python
     def main(argv: list[str] | None = None) -> None:
         if argv is None:
             argv = sys.argv[1:]

         if argv and _dispatch_agent_argv(argv):
             return

         parser = build_parser()
         args = parser.parse_args(argv)

         if not argv or args.command is None:
             parser.print_help(sys.stderr)
             sys.exit(1)

         handler = getattr(args, "handler", None)
         if handler is not None:
             res = handler(args)
             if isinstance(res, int) and res != 0:
                 sys.exit(res)
             return

         parser.print_help(sys.stderr)
         sys.exit(1)
     ```

   - Retain all public re-exports in `__all__` to guarantee 100% backward compatibility for downstream callers.
   - Remove `# noqa: C901, PLR0912, PLR0915` from `main`.

3. **Update Complexity Baseline Ratchet**:
   - In `tests/test_complexity_baseline.py`, update `BASELINE_CEILING` to reflect the removal of the 3 noqa suppressions
     from `cli.py` (e.g. from 43 to 40).
   - Verify `uv run pytest tests/test_complexity_baseline.py` passes cleanly.

### Dependencies & Criticality

- **Dependencies:** Step 1, Step 2, Step 3
- **Is bottleneck:** Yes — Core architectural goal of the intent.

### Safety & Constraint Considerations

- **Relevant rules:** Bean 0186 complexity thresholds ($C901 \le 10$, $PLR0911 \le 6$, $PLR0912 \le 12$, $PLR0915 \le
  50$), §2 Coding Conventions & Standards.
- **Failure modes:** Removing `_dispatch.py` prematurely if any module still references it; breaking existing CLI
  invocations with `--help` or invalid commands.
- **Guardrails:** Full grep check for `_dispatch` and `get_cli` before deletion; test `main([])` and `main(["--help"])`
  to ensure standard help and exit code 1 on empty input.

### Success & Discard Criteria

- **Success:** `_dispatch.py` is removed, `cli.main` CC is $\le 10$ with zero noqa suppressions,
  `test_complexity_baseline.py` passes with updated `BASELINE_CEILING`, and all CLI entrypoint tests pass.
- **Discard:** Discard if `_dispatch.py` deletion causes unhandled import errors.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.97  |
| entropy_pred        | 0.50  |
| impact_pred         | 9.00  |
| cost_pred           | 0.15  |
| learning_value_pred | 1.50  |
| ev_pred             | 9.18  |

### Step Metrics Rationale

- $\text{EV} = 0.97 \times 9.00 + 0.5 \times 1.50 - 0.3 \times 0.50 - 0.15 = 8.73 + 0.75 - 0.15 - 0.15 = 9.18$.
  Drastically simplifies `cli.py` (from 497 lines down to <120 lines), eliminates dynamic runtime lookups, and ratchets
  down technical debt.

---

## Step 5: Modularize and Split `tests/test_cli.py` into `tests/commands/`

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Disentangle the 3,728-line monolithic `tests/test_cli.py` test suite by migrating command-specific
  tests into dedicated, modular files under `tests/commands/`, updating patch targets directly to the command modules
  and guaranteeing test count preservation.
- **Step type:** test_refactoring
- **Exploration level:** 0.05
- **Git branch:** `I-1793334806-coherence-commands-register-their-own-parsers`

### Implementation Details

1. **Create Directory `tests/commands/`**:
   - Establish `tests/commands/__init__.py`.

2. **Decompose Test Suites into Dedicated Test Files**:
   - **`tests/commands/test_ca.py`**:
     - Migrate all CA certificate initialization, merging, and system bundle discovery tests (`find_system_ca_bundle`,
       `get_or_create_merged_ca_bundle`, `handle_init_ca`).
     - Update mock patch targets to `holon_coherence.commands.ca.*`.
   - **`tests/commands/test_runner.py`**:
     - Migrate tests for `build_proxy_env`, `merge_no_proxy_values`, `execute_interactive_process`, and `handle_run`.
     - Update patch targets to `holon_coherence.commands.runner.*`.
   - **`tests/commands/test_docker_ops.py`**:
     - Migrate tests for container status, logs, stop, build, daemon checks, and port binding (`handle_status`,
       `handle_logs`, `handle_stop`, `handle_build`, `is_container_running`, `is_container_bound_to_port`,
       `ensure_docker_image`).
     - Update patch targets to `holon_coherence.commands.docker_ops.*`.
   - **`tests/commands/test_web_token.py`**:
     - Migrate tests for token saving, permissions (0600), password generation, active token retrieval, and CLI
       reporting (`handle_web_token`, `save_web_token`, `resolve_web_password`, `get_active_web_token`).
     - Update patch targets to `holon_coherence.commands.web_token.*`.
   - **`tests/commands/test_endpoints.py`**:
     - Migrate tests for `ExposedEndpoints`, `format_endpoint_rows`, `print_endpoints`, and
       `resolve_container_endpoints`.
     - Update patch targets to `holon_coherence.commands.endpoints.*`.
   - **`tests/commands/test_start.py`**:
     - Migrate tests for `handle_start`, `ensure_proxy_running`, `wait_for_proxy_ready`, `plan_local_llm_route`, and
       container argument construction.
     - Update patch targets to `holon_coherence.commands.start.*`.
   - **`tests/commands/test_metrics.py`**:
     - Migrate tests for `handle_metrics` (live HTTP vs offline wire log fallbacks, table rendering, raw JSON).
     - Update patch targets to `holon_coherence.commands.metrics.*`.
   - **`tests/commands/test_agents.py`**:
     - Migrate tests for `extract_runner_flags`, `resolve_agent_binary`, `build_agent_env`, `run_agent`, and agent
       aliases.
     - Update patch targets to `holon_coherence.commands.agents.*`.
   - **`tests/commands/test_ab_test.py`**:
     - Migrate CLI dispatch and argument validation tests for `handle_ab_test`.
     - Update patch targets to `holon_coherence.commands.ab_test.*`.

3. **Retain Focused Core Tests in `tests/test_cli.py`**:
   - Keep tests for top-level entrypoint `main()`, parser building, subparser discovery across `COMMAND_MODULES`,
     `--help` rendering, missing command exit codes (code 1), and fast-path agent execution.

4. **Verify Test Count Preservation**:
   - Count total pytest items before and after modularization.
   - Assert `post_test_count >= pre_test_count`.

### Dependencies & Criticality

- **Dependencies:** Step 1, Step 2, Step 3, Step 4
- **Is bottleneck:** Yes — Fulfills Acceptance Criterion 5 and guarantees zero regressions across the refactored
  modules.

### Safety & Constraint Considerations

- **Relevant rules:** §3 Testing Constraints (Hermetic Test Isolation, Zero Unstaged Regressions), Rule 1 (Zero
  Synthetic / Mock Data for Benchmarking).
- **Failure modes:** Broken patch paths if tests still attempt to patch functions on `holon_coherence.cli` after
  functions were moved.
- **Guardrails:** Keep patch targets localized directly to the module defining the function under test.

### Success & Discard Criteria

- **Success:** `tests/test_cli.py` is split cleanly across `tests/commands/`, all test modules execute hermetically,
  total test count is $\ge$ initial count, and 100% of tests pass.
- **Discard:** Discard if any test suite fails or test count drops.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.95  |
| entropy_pred        | 0.70  |
| impact_pred         | 8.50  |
| cost_pred           | 0.15  |
| learning_value_pred | 2.00  |
| ev_pred             | 8.72  |

### Step Metrics Rationale

- $\text{EV} = 0.95 \times 8.50 + 0.5 \times 2.00 - 0.3 \times 0.70 - 0.15 = 8.075 + 1.00 - 0.21 - 0.15 = 8.72$.
  Splitting 3,700 lines into 9 modular test files dramatically improves maintainability, test execution
  parallelizability, and debugging clarity.

---

## Step 6: Comprehensive Verification, Quality Gates & Complexity Ratchet

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Validate that all refactored command modules and new test suites pass all quality, style, complexity,
  and hermetic isolation gates with 100% green status.
- **Step type:** verification
- **Exploration level:** 0.00
- **Git branch:** `I-1793334806-coherence-commands-register-their-own-parsers`

### Implementation Details

1. **Pytest Verification**:
   - Run full test suite:
     ```bash
     uv run pytest
     ```
   - Verify zero failures, zero errors, and that total test count is greater than or equal to baseline.
   - Run command unit tests specifically:
     ```bash
     uv run pytest tests/commands/ tests/test_cli.py
     ```

2. **Complexity and Hygiene Gates**:
   - Run Ruff checks:
     ```bash
     uv run ruff check .
     uv run ruff format --check .
     ```
   - Run complexity ratchet baseline verification:
     ```bash
     uv run pytest tests/test_complexity_baseline.py
     ```
   - Confirm `BASELINE_CEILING` accurately matches the lower number of inline noqa suppressions resulting from
     refactoring `cli.main`.

3. **Markdown and Repository Hygiene**:
   - Format all markdown documentation:
     ```bash
     npx prettier --write "**/*.md"
     ```
   - Confirm git worktree status is clean with zero untracked artifacts or temporary files:
     ```bash
     git status
     ```

4. **Git Commit Preparation**:
   - Squash all incremental feature commits into a single logical commit relative to `origin/main` according to the
     Holon git worktree rules.

### Dependencies & Criticality

- **Dependencies:** Step 1, Step 2, Step 3, Step 4, Step 5
- **Is bottleneck:** Yes — Final gate for acceptance criteria fulfillment.

### Safety & Constraint Considerations

- **Relevant rules:** §1 Runtime & Environment Specification, §2 Coding Conventions & Standards, §3 Testing Constraints,
  Worktree Isolation & Squash Commits.
- **Failure modes:** Uncaught Ruff formatting discrepancies, lingering unused imports, or broken Prettier markdown
  checks.
- **Guardrails:** Automated test execution via `uv run pytest` and linting with Ruff before declaring completion.

### Success & Discard Criteria

- **Success:** Full `uv run pytest` suite passes with 0 failures, Ruff checks report 0 errors, Prettier passes, and git
  history is squashed cleanly.
- **Discard:** Discard if any regression or broken test exists.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.99  |
| entropy_pred        | 0.40  |
| impact_pred         | 9.00  |
| cost_pred           | 0.10  |
| learning_value_pred | 1.00  |
| ev_pred             | 9.19  |

### Step Metrics Rationale

- $\text{EV} = 0.99 \times 9.00 + 0.5 \times 1.00 - 0.3 \times 0.40 - 0.10 = 8.91 + 0.50 - 0.12 - 0.10 = 9.19$. Final
  verification gate guarantees complete compliance with all intent acceptance criteria and repository quality
  invariants.

---

## Strategy Rationale

The overall plan metrics are computed using the physics-driven Expected Value (EV) formula:

$$\text{EV} = P(\text{success}) \times \text{Impact} + \mu \times \text{LearningValue} - \lambda \times \Delta S_{\text{intent}} - \text{Cost}$$

Using baseline calibration constants $\lambda = 0.3$ and $\mu = 0.5$:

$$\text{EV} = (0.95 \times 8.50) + (0.5 \times 2.00) - (0.3 \times 3.20) - 0.90 = 8.075 + 1.00 - 0.96 - 0.90 = 7.215 \approx 7.22$$

- **$P(\text{success})$ (0.95):** The refactoring uses standard Python standard library `argparse` patterns
  (`register(subparsers)` and `set_defaults(handler=handle)`), eliminating dynamic `sys.modules` introspection in favor
  of explicit argument injection.
- **$\text{Impact}$ (8.50):** Replaces a 349-line monolithic parser in `cli.main` (CC 31) with decentralized
  self-registering command modules, eliminates `_dispatch.py` (used across 15 call sites in 8 modules), and breaks down
  a 3,728-line test monolith into 9 modular test suites.
- **$\mu \times \text{LearningValue}$ ($0.5 \times 2.00 = 1.00$):** Establishes a clean, scalable architectural pattern
  for future commands in `holon-coherence` while lowering the project's technical debt and complexity ratchet ceiling.
- **$\lambda \times \Delta S\_{\text{intent}}$ ($0.3 \times 3.20 = 0.96$):** Bounded entropy across the 12 files in
  scope, well within the allocated 5.0 entropy budget.
- **$\text{Cost}$ (0.90):** Moderate execution cost covering comprehensive file editing, test modularization, patch
  target realignment, and multiple pytest/ruff validation runs.

---

## Planner Autonomy Summary

- **Intent handling:** `ACCEPT_AS_IS`
- **Reframed intent (if applicable):** NONE
- **Exploration stance:** Exploitation-dominant (0.05 exploration). The refactoring boundaries, acceptance criteria, and
  architecture are explicitly detailed in the intent specification. Standard Python dependency injection and `argparse`
  subparser patterns are deterministic and well understood.
- **Safety priority level:** `standard`
- **Priority Justification:** All modifications are confined to CLI command registration, argument handling,
  collaborator injection, and test modularization within `src/holon_coherence/commands/`, `src/holon_coherence/cli.py`,
  and `tests/`. No cryptographic CA generation logic, proxy network interception layers, or external runtime
  dependencies are modified.

---

## Exploration

- **Proportion of steps that are exploratory:** 0.05
- **Justification:** The `argparse` subparser registration protocol and dependency injection mechanisms are standard
  software engineering patterns. A minimal exploration allowance (0.05) is allocated for fine-tuning default parameter
  signatures for collaborators across interdependent modules and adjusting the exact complexity baseline count in
  `tests/test_complexity_baseline.py`.

---

## Safety & Constraint Alignment

- **Key world ruleset constraints that affect this plan:**
  - `holon-config/world/ruleset.md`: Runtime compatibility with Python 3.13, execution of tests strictly via
    `uv run pytest`, Ruff compliance (`ruff check` and `ruff format`), and static typing with docstring preservation.
  - Bean 0186 Complexity Limits: Enforce $C901 \le 10$, $PLR0911 \le 6$, $PLR0912 \le 12$, $PLR0913 \le 5$, $PLR0915 \le
    50$. Verify `tests/test_complexity_baseline.py` ratchet ceiling.
  - Testing constraints: Zero regressions across existing tests, hermetic test isolation, and preservation or increase
    of total test count.
  - Git flow constraints: Worktree isolation, single squashed commit relative to `main`, and no autonomous remote push.
- **Potential violations or edge cases:**
  - Argument parsing drift: Modifying subparser registration could accidentally change flag defaults, argument names, or
    help strings (e.g. `--local-llm-base` vs `--local-llm-endpoint`, `--web-token` vs `--web-key`).
  - Circular import deadlock: If command modules import each other to provide default collaborators at module top level,
    circular imports can fail at import time.
  - Broken mock patch targets: Moving functions out of `cli.py` or eliminating `_dispatch.py` could break existing tests
    that patch `holon_coherence.cli.<symbol>` if patch paths are not systematically updated.
  - Ratchet ceiling failure: `test_complexity_baseline.py` asserts that the number of inline noqa complexity
    suppressions exactly equals `BASELINE_CEILING`. If `cli.main` drops its `# noqa` comments without updating
    `BASELINE_CEILING`, the ratchet gate will fail.
- **Mitigations built into the plan:**
  - Strict parameter and alias fidelity: All subparser definitions maintain exact existing argument flags, types,
    defaults, and aliases (`web-key`, agent aliases).
  - Clean collaborator injection: Function/callable defaults are assigned using existing functions directly in
    signatures or internal module scopes without circular module-level references.
  - Systematic test split and patch target relocation: Tests under `tests/commands/` will directly patch the local
    command module (`holon_coherence.commands.<mod>.<symbol>`) rather than `holon_coherence.cli`.
  - Proactive ratchet adjustment: Step 4 explicitly accounts for recalculating and updating `BASELINE_CEILING` in
    `tests/test_complexity_baseline.py`.
- **Allocated Entropy Budget:** 5.0
- **Predicted Plan Entropy:** 3.20 (sum of step entropies: $0.50 + 0.50 + 0.60 + 0.50 + 0.70 + 0.40 = 3.20$)
- **Budget Compliance:** Full compliance ($3.20 \le 5.00$).

---

## Plan Description & Strategy

1. **Step 1: Define Command Protocol and Refactor `ca.py` and `runner.py`**: Establish standard `register(subparsers)`
   and `handle(args)` functions for `init-ca` and `run`, remove `_dispatch.get_cli()` calls in both modules, and inject
   collaborator functions as arguments with sensible defaults.
2. **Step 2: Refactor `docker_ops.py`, `endpoints.py`, and `web_token.py`**: Export `register(subparsers)` and
   `handle(args)` in `docker_ops.py` (covering `build`, `stop`, `status`, `logs`) and `web_token.py` (covering
   `web-token` and `web-key`). Remove all `get_cli()` calls in `docker_ops.py`, `endpoints.py`, and `web_token.py` with
   explicit collaborator arguments.
3. **Step 3: Refactor `start.py`, `metrics.py`, `agents.py`, and `ab_test.py`**: Export `register(subparsers)` and
   `handle(args)` in `start.py` (`start`), `metrics.py` (`metrics`), `agents.py` (`run-agent` and individual agent
   aliases), and `ab_test.py` (`ab-test`). Eliminate all remaining `get_cli()` calls.
4. **Step 4: Remove `_dispatch.py` and Refactor `cli.main` into Slim Dispatcher**: Delete
   `src/holon_coherence/commands/_dispatch.py`. Refactor `cli.py` to register all modules via a concise registry loop
   and delegate execution to `args.handler(args)`. Reduce `cli.main` cyclomatic complexity to $\le 10$, remove inline
   noqa comments, and ratchet down `BASELINE_CEILING` in `tests/test_complexity_baseline.py`.
5. **Step 5: Modularize and Split `tests/test_cli.py` into `tests/commands/`**: Decompose the 3,728-line
   `tests/test_cli.py` into modular files under `tests/commands/` (`test_ca.py`, `test_runner.py`, `test_docker_ops.py`,
   `test_web_token.py`, `test_endpoints.py`, `test_start.py`, `test_metrics.py`, `test_agents.py`, `test_ab_test.py`).
   Retain core CLI entrypoint tests in `tests/test_cli.py` and ensure total test count is maintained or increased.
6. **Step 6: Comprehensive Verification, Quality Gates & Complexity Ratchet**: Run full `uv run pytest`, verify test
   count preservation, execute Ruff checks and formatting, confirm complexity ratchet compliance, format markdown
   documentation with Prettier, and squash feature branch commits cleanly.
