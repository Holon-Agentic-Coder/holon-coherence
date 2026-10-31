# Plan for I-1793405506-coherence-one-provider-module-per-wire-format

- **Plan ID:** P-1793405520-antigravity-agent-gemini-3.8-flash-medium
- **Parent Intent ID:** NONE
- **Agent:** antigravity-agent (version: 1.4.11)
- **Created At:** 2026-10-31T00:12:01.578Z

---

## Overall Plan Metrics

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.98  |
| entropy_pred        | 3.80  |
| impact_pred         | 8.90  |
| cost_pred           | 0.85  |
| learning_value_pred | 2.50  |
| ev_pred             | 7.98  |

---

## Step 1: Provider Architecture, Protocol Specification & Registry (`src/holon_coherence/providers/`)

### Step Intent & Git Integration

- **Sub-intent recommendation:** none (monolithic execution within intent scope)
- **Reasoning:** Establish the foundational `src/holon_coherence/providers/` package, defining the `ProviderFormat` protocol in `base.py` and the provider resolution registry in `__init__.py`. This provides the typed contract against which all concrete format implementations and consumer delegates will build.
- **Step type:** implementation
- **Exploration level:** 0.05
- **Git branch:** `I-1793405506-coherence-one-provider-module-per-wire-format`

### Implementation Details

1. **Initialize Package Structure**:
   - Create package directory `src/holon_coherence/providers/`.
   - Create `src/holon_coherence/providers/base.py` and `src/holon_coherence/providers/__init__.py`.

2. **Define `ProviderFormat` Protocol (`base.py`)**:
   - Create `runtime_checkable` Protocol `ProviderFormat` specifying the common interface:
     - `clean(self, cleaner: Any, payload: dict[str, Any], seen_content_hashes: dict[str, tuple[int, str]], stats: dict[str, int] | None = None) -> dict[str, Any]`: Formats and cleans request payloads (tool deduplication, turn truncation/summarization, cache breakpoint injection).
     - `token_counts_from_sse(self, resp_text: str, req_data: dict[str, Any]) -> TokenCounts`: Extracts input, output, and cache read token counts from raw SSE text stream.
     - `token_counts_from_dict(self, req_data: dict[str, Any], resp_data: dict[str, Any]) -> TokenCounts`: Extracts token counts from a parsed dictionary response.
     - `extract_sse_content(self, resp_text: str) -> str`: Extracts aggregated completion text or tool call strings from SSE chunks.
     - `extract_cache_key_parts(self, payload: dict[str, Any], max_recent_turns: int = 2) -> tuple[str, str]`: Extracts `(user_content, system_prompt)` for hybrid semantic cache key generation.
   - Define abstract base helper methods or shared data structures (e.g. `ProviderName` type alias: `"anthropic" | "openai" | "gemini"`).

3. **Implement Provider Registry (`__init__.py`)**:
   - Maintain an internal registry mapping provider names (`"anthropic"`, `"openai"`, `"gemini"`) to singleton instances of their respective format implementations.
   - Provide factory and lookup functions:
     - `get_provider(name: str) -> ProviderFormat`: Returns the provider instance for the given identifier, defaulting safely to `openai` if unrecognized.
     - `resolve_provider(url_or_path: str, payload: dict[str, Any] | None = None) -> ProviderFormat`: Resolves provider using URL heuristics and payload signatures.
   - Expose explicit `__all__ = ["ProviderFormat", "get_provider", "resolve_provider"]`.

### Dependencies & Criticality

- **Dependencies:** None
- **Is bottleneck:** Yes — Defines the core contract and registry imported by all concrete provider implementations and consumer refactorings.

### Safety & Constraint Considerations

- **Relevant rules:** §2 Coding Conventions & Standards (PEP 8, docstring preservation, strict typing, Ruff cleanliness), Rule 1 (Zero Synthetic / Mock Data).
- **Failure modes:** Circular imports between `providers/` and `parsers/` or `payload_cleaner.py`.
- **Guardrails:** Keep `base.py` pure, importing only `typing`, standard library primitives, and `TokenCounts` from `holon_coherence.parsers.tokens`. Use lazy resolution or runtime registration if necessary to eliminate circular dependencies.

### Success & Discard Criteria

- **Success:** `src/holon_coherence/providers/base.py` and `__init__.py` compile cleanly, export `ProviderFormat` protocol and `get_provider`, and comply with Bean 0186 complexity limits (McCabe C901 <= 10).
- **Discard:** Discard if circular dependencies or protocol incompatibilities occur.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.99  |
| entropy_pred        | 0.40  |
| impact_pred         | 7.50  |
| cost_pred           | 0.10  |
| learning_value_pred | 1.00  |
| ev_pred             | 7.71  |

### Step Metrics Rationale

- $\text{EV} = 0.99 \times 7.50 + 0.5 \times 1.00 - 0.3 \times 0.40 - 0.10 = 7.425 + 0.50 - 0.12 - 0.10 = 7.705 \approx 7.71$. Creating the abstract protocol and provider registry establishes the foundational architectural contract with minimal risk.

---

## Step 2: Implement Anthropic Format Module (`src/holon_coherence/providers/anthropic.py`)

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Encapsulate all Anthropic wire format handling (request cleaning, tool output deduplication, history summarization, prompt cache breakpoint injection, SSE token and content parsing, and cache key generation) into `src/holon_coherence/providers/anthropic.py`. Ensure every internal helper strictly complies with Bean 0186 complexity thresholds.
- **Step type:** implementation
- **Exploration level:** 0.05
- **Git branch:** `I-1793405506-coherence-one-provider-module-per-wire-format`

### Implementation Details

1. **Create `src/holon_coherence/providers/anthropic.py`**:
   - Implement `AnthropicProvider(ProviderFormat)` class implementing all required methods.

2. **Clean Operation (`clean`)**:
   - Move Anthropic payload cleaning logic from `payload_cleaner.py`:
     - Tool deduplication: `_deduplicate_anthropic_tool_outputs`. Deconstruct into small helper functions (e.g. `_hash_tool_content`, `_is_turn_eligible_for_dedup`) to reduce cyclomatic complexity well below $C901 \le 10$.
     - Turn summarization: `_summarize_anthropic_history`. Split boundary resolution and summary message creation into focused sub-functions.
     - Role merging: `_merge_consecutive_roles`. Ensure consecutive `user` or `assistant` turns are cleanly concatenated without nested branch spikes.
     - Prompt cache injection: `_inject_anthropic_cache_control` and `_count_existing_cache_controls`. Break down top-level system, tools, and message turn injection into isolated helpers to keep statement count $PLR0915 \le 50$ and branch count $PLR0912 \le 12$.

3. **SSE & Token Count Extraction (`token_counts_from_sse`, `token_counts_from_dict`, `extract_sse_content`)**:
   - Move Anthropic stream parsing logic from `parsers/sse.py`:
     - Handle `message_start` events: parse `input_tokens`, `cache_read_input_tokens`, and `cache_creation_input_tokens`.
     - Handle `message_delta` events: parse `output_tokens` and `thinking_tokens`.
     - Handle `content_block_delta` events: extract text and partial JSON tokens.
     - Extract completion content: parse `content_block` (`tool_use`), `delta` (`text`, `thinking`, `partial_json`), and handle `content_block_stop`.
   - Move dictionary usage parsing from `parsers/tokens.py`:
     - Extract `usage.input_tokens`, `usage.output_tokens`, `usage.cache_read_input_tokens`, `usage.cache_creation_input_tokens`. Return unified `TokenCounts`.

4. **Cache Key Parts Extraction (`extract_cache_key_parts`)**:
   - Move Anthropic extraction from `hybrid_cache.py`:
     - Extract user message text: parse `messages` array for `role == "user"`, resolving string contents, block lists, and `tool_result` content.
     - Extract system prompt: parse top-level `system` string or array of system text blocks.

5. **Complexity & Interface Verification**:
   - Verify every helper in `anthropic.py` satisfies McCabe $C901 \le 10$, $PLR0911 \le 6$, $PLR0912 \le 12$, $PLR0913 \le 5$, $PLR0915 \le 50$.

### Dependencies & Criticality

- **Dependencies:** Step 1
- **Is bottleneck:** No — Implements the first concrete provider conforming to `ProviderFormat`.

### Safety & Constraint Considerations

- **Relevant rules:** §2 Coding Conventions & Standards, Bean 0186 Complexity Limits, Rule 1 (Zero Synthetic Data).
- **Failure modes:** Subtle regressions in cache control breakpoint budgets (max 4 breakpoints in Anthropic API); dropped tool result blocks during history summarization.
- **Guardrails:** Port exact existing logic with granular sub-function extraction; mirror all edge cases from `payload_cleaner.py` and `parsers/sse.py`.

### Success & Discard Criteria

- **Success:** `AnthropicProvider` conforms to `ProviderFormat`, passes all lint and complexity checks without any `# noqa` suppressions, and reproduces identical cleaning and parsing outputs.
- **Discard:** Discard if complexity thresholds are violated or behavioral discrepancies emerge.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.98  |
| entropy_pred        | 0.60  |
| impact_pred         | 8.00  |
| cost_pred           | 0.15  |
| learning_value_pred | 1.50  |
| ev_pred             | 8.26  |

### Step Metrics Rationale

- $\text{EV} = 0.98 \times 8.00 + 0.5 \times 1.50 - 0.3 \times 0.60 - 0.15 = 7.84 + 0.75 - 0.18 - 0.15 = 8.26$. Isolating Anthropic format logic into a dedicated provider eliminates multiple legacy `# noqa` complexity hotspots while establishing a clean reference pattern for OpenAI and Gemini modules.

---

## Step 3: Implement OpenAI & Gemini Format Modules & Encapsulate Translation (`openai.py`, `gemini.py`, `translation.py`)

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Implement `OpenAIProvider` in `src/holon_coherence/providers/openai.py` and `GeminiProvider` in `src/holon_coherence/providers/gemini.py` conforming to `ProviderFormat`. Migrate bidirectional Gemini $\leftrightarrow$ OpenAI protocol translation into `src/holon_coherence/providers/translation.py`, refactoring monolithic translation functions into modular subroutines strictly below Bean 0186 complexity thresholds.
- **Step type:** implementation
- **Exploration level:** 0.05
- **Git branch:** `I-1793405506-coherence-one-provider-module-per-wire-format`

### Implementation Details

1. **Implement `src/holon_coherence/providers/openai.py`**:
   - Class `OpenAIProvider(ProviderFormat)`:
     - `clean`: Port `_clean_openai` from `payload_cleaner.py`. Break out tool output hashing (`role == "tool"`), turn truncation, clean user turn boundary search, and summary insertion into distinct helper functions ($C901 \le 10$).
     - `token_counts_from_sse`: Port OpenAI SSE usage extraction (`prompt_tokens`, `completion_tokens`, `prompt_tokens_details.cached_tokens`, and reasoning token breakdowns).
     - `token_counts_from_dict`: Extract dictionary `usage` metadata with character-fallback calculation.
     - `extract_sse_content`: Parse `choices[].delta` stream chunks, tracking tool calls (`name`, `arguments`) and finish reasons (`tool_calls`, `stop`).
     - `extract_cache_key_parts`: Extract user content from `messages` (`role == "user"`) and system prompt from `messages` (`role == "system"`).

2. **Implement `src/holon_coherence/providers/gemini.py`**:
   - Class `GeminiProvider(ProviderFormat)`:
     - `clean`: Port `_clean_gemini` from `payload_cleaner.py`. Decompose `contents` array parsing, parts inspection, deduplication hashing, and turn truncation into focused subroutines ($C901 \le 10$).
     - `token_counts_from_sse`: Port Gemini SSE parsing for `usageMetadata` (`promptTokenCount`, `candidatesTokenCount`, `cachedContentTokenCount`).
     - `token_counts_from_dict`: Extract `usageMetadata` from response dicts.
     - `extract_sse_content`: Extract `candidates[].content.parts` text and serialized `functionCall` dictionaries.
     - `extract_cache_key_parts`: Extract user messages from `contents` (`role in ("user", None, "")`) and system instructions from `system_instruction`.

3. **Encapsulate Protocol Translation (`src/holon_coherence/providers/translation.py`)**:
   - Port Gemini $\leftrightarrow$ OpenAI bidirectional translation from `src/holon_coherence/proxy/translation/gemini_openai.py`:
     - Deconstruct `translate_gemini_to_openai_request` into modular helpers:
       - `_translate_system_instruction(payload: dict) -> list[dict]`
       - `_translate_contents(contents: list[dict]) -> list[dict]`
       - `_translate_tools(tools: list[dict], tool_config: dict | None) -> tuple[list[dict] | None, Any]`
     - Deconstruct `translate_openai_to_gemini_response`:
       - `_translate_choices(choices: list[dict]) -> list[dict]`
       - `_translate_usage_to_gemini(usage: dict) -> dict`
     - Deconstruct `translate_openai_sse_chunk_to_gemini`:
       - `_translate_sse_delta(delta: dict) -> list[dict]`
       - `_translate_sse_usage(usage: dict) -> dict`
   - Ensure all translation functions comply strictly with $C901 \le 10$, $PLR0912 \le 12$, $PLR0915 \le 50$, removing legacy `# noqa` comments.
   - Update `src/holon_coherence/proxy/translation/gemini_openai.py` and `proxy/translation/__init__.py` to import and re-export the translation functions from `providers/translation.py` for full backward compatibility.

4. **Register Concrete Providers (`src/holon_coherence/providers/__init__.py`)**:
   - Register instances of `AnthropicProvider`, `OpenAIProvider`, and `GeminiProvider` in the provider registry.

### Dependencies & Criticality

- **Dependencies:** Step 1, Step 2
- **Is bottleneck:** No — Completes the full set of format provider modules.

### Safety & Constraint Considerations

- **Relevant rules:** §2 Coding Conventions & Standards, Bean 0186 Complexity Limits, Backward-Compatibility Invariants.
- **Failure modes:** Subtle translation regressions in Gemini functionCall arguments or OpenAI tool_call_id alignment; missing SSE chunk usage chunks.
- **Guardrails:** Validate against existing extensive test suites in `tests/test_mitm_addon.py` and `tests/proxy/test_translation.py`. Keep function signatures and return types 100% identical.

### Success & Discard Criteria

- **Success:** `OpenAIProvider`, `GeminiProvider`, and `translation.py` implemented cleanly with 0 complexity `# noqa` suppressions, all unit tests in `test_translation.py` pass without modification.
- **Discard:** Discard if translation logic breaks existing golden parity fixtures or exceeds complexity limits.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.97  |
| entropy_pred        | 0.80  |
| impact_pred         | 8.50  |
| cost_pred           | 0.20  |
| learning_value_pred | 2.00  |
| ev_pred             | 8.81  |

### Step Metrics Rationale

- $\text{EV} = 0.97 \times 8.50 + 0.5 \times 2.00 - 0.3 \times 0.80 - 0.20 = 8.245 + 1.00 - 0.24 - 0.20 = 8.805 \approx 8.81$. Decomposing legacy high-complexity translation routines into dedicated, well-bounded provider helpers yields high architectural value and eliminates major technical debt.

---

## Step 4: Refactor Consumer Subsystems (`payload_cleaner.py`, `parsers/sse.py`, `parsers/tokens.py`, `hybrid_cache.py`)

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Refactor consumer components (`JSONContextCleaner`, `parsers/sse.py`, `parsers/tokens.py`, and `HybridCacheStore`) to resolve the target `ProviderFormat` instance once via the provider registry and delegate format-specific branching directly to the provider. Eliminate all legacy provider branching blocks and `# noqa` suppressions across these core files.
- **Step type:** implementation
- **Exploration level:** 0.05
- **Git branch:** `I-1793405506-coherence-one-provider-module-per-wire-format`

### Implementation Details

1. **Refactor `JSONContextCleaner` in `src/holon_coherence/payload_cleaner.py`**:
   - Update `process_payload_with_stats`:
     - Resolve the format object: `provider_format = get_provider(provider)`.
     - Delegate payload cleaning: `cleaned_payload = provider_format.clean(self, cleaned_payload, seen_content_hashes, stats=stats)`.
   - Keep legacy private methods (`_clean_anthropic`, `_clean_openai`, `_clean_gemini`) as thin delegating wrappers for any direct external or test callers.
   - Remove redundant legacy monoliths (`_deduplicate_anthropic_tool_outputs`, `_count_existing_cache_controls`, `_inject_anthropic_cache_control`), transferring their logic entirely to `providers/anthropic.py`.
   - Remove associated `# noqa: C901, PLR0912, PLR0915` comments.

2. **Refactor SSE & Token Parsers in `src/holon_coherence/parsers/`**:
   - `src/holon_coherence/parsers/sse.py`:
     - Refactor `extract_sse_content(resp_text: str, provider: str) -> str`:
       - Resolve provider: `return get_provider(provider).extract_sse_content(resp_text)`.
     - Refactor `extract_sse_token_counts(resp_text: str, req_data: dict[str, Any], provider: str) -> TokenCounts`:
       - Resolve provider: `return get_provider(provider).token_counts_from_sse(resp_text, req_data)`.
     - Remove `# noqa: C901, PLR0912, PLR0915` comments from `extract_sse_content` and `extract_sse_token_counts`.
   - `src/holon_coherence/parsers/tokens.py`:
     - Refactor `extract_token_counts(req_data, resp_data, provider)`:
       - Check if `resp_data` is `str` (delegating to `get_provider(provider).token_counts_from_sse`) or `dict` (delegating to `get_provider(provider).token_counts_from_dict`).
     - Remove `# noqa: C901, PLR0912, PLR0915` comment from `extract_token_counts`.

3. **Refactor `HybridCacheStore` in `src/holon_coherence/hybrid_cache.py`**:
   - Update `_extract_user_content` and `_extract_system_prompt`:
     - Detect provider schema from payload or use default resolution.
     - Delegate to `provider_format.extract_cache_key_parts(payload, max_recent_turns)`.
     - Provide fallback for unformatted payload strings or schemas.
   - Remove `# noqa: C901, PLR0912` from `_extract_user_content` and `_extract_system_prompt`.

4. **Preserve External API & Signatures**:
   - Maintain identical function and method signatures across all touched public APIs to ensure 100% backward compatibility for all existing callers, test suites, and proxy interceptors.

### Dependencies & Criticality

- **Dependencies:** Step 1, Step 2, Step 3
- **Is bottleneck:** Yes — Connects the new provider format architecture to the active runtime pipeline.

### Safety & Constraint Considerations

- **Relevant rules:** §2 Coding Conventions & Standards, Bean 0186 Complexity Limits, Backward-Compatibility Invariants.
- **Failure modes:** Regressions in character savings calculations in `payload_cleaner.py`; subtle token estimation differences on malformed SSE lines.
- **Guardrails:** Keep character counting fallback identical in `tokens.py`; maintain full test coverage against original test cases.

### Success & Discard Criteria

- **Success:** Consumer modules delegate cleanly to `get_provider(name)`, all legacy `# noqa` complexity suppressions are eliminated from modified files, and existing unit tests pass without error.
- **Discard:** Discard if any consumer method deviates from historical input/output behavior.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.97  |
| entropy_pred        | 0.90  |
| impact_pred         | 9.00  |
| cost_pred           | 0.22  |
| learning_value_pred | 2.00  |
| ev_pred             | 9.24  |

### Step Metrics Rationale

- $\text{EV} = 0.97 \times 9.00 + 0.5 \times 2.00 - 0.3 \times 0.90 - 0.22 = 8.73 + 1.00 - 0.27 - 0.22 = 9.24$. Replacing duplicated, multi-branch conditional blocks with polymorphic delegation drastically simplifies core subsystems and enforces the Open-Closed Principle.

---

## Step 5: Provider Test Suite & Backward-Compatibility Verification (`tests/providers/`)

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Construct a dedicated unit test suite in `tests/providers/` targeting each provider module and the translation layer directly. Verify that all existing unit tests in `tests/` pass with zero regression.
- **Step type:** testing
- **Exploration level:** 0.05
- **Git branch:** `I-1793405506-coherence-one-provider-module-per-wire-format`

### Implementation Details

1. **Create Test Directory `tests/providers/`**:
   - Create `tests/providers/__init__.py`.

2. **Implement Unit Tests for Providers**:
   - `tests/providers/test_registry.py`:
     - Test `get_provider` for `"anthropic"`, `"openai"`, `"gemini"`.
     - Test fallback behavior for unknown provider strings.
     - Verify all registered instances satisfy `isinstance(p, ProviderFormat)`.
   - `tests/providers/test_anthropic.py`:
     - Test payload cleaning: deduplication of identical tool results, history summarization above `max_turns`, role merging, and cache control breakpoint injection budget.
     - Test SSE parsing: `message_start` (cache read/creation), `message_delta` (thinking/output tokens), `content_block_delta`.
     - Test content extraction: tool_use name, partial JSON, text deltas.
     - Test cache key extraction: user messages and system instructions.
   - `tests/providers/test_openai.py`:
     - Test payload cleaning: deduplication of tool outputs (`role: "tool"`), turn truncation, and role merging.
     - Test SSE parsing: `choices[].delta` text accumulation, tool call name and arguments buffering, finish reasons (`tool_calls`, `stop`).
     - Test cache key extraction: user and system messages.
   - `tests/providers/test_gemini.py`:
     - Test payload cleaning: `contents` turn deduplication and summarization.
     - Test SSE parsing: `candidates[].content.parts` text and `functionCall` json string serialization, `usageMetadata`.
     - Test cache key extraction: `contents` user turns and `system_instruction`.
   - `tests/providers/test_translation.py`:
     - Test `translate_gemini_to_openai_request`: basic messages, tool declarations, tool call IDs.
     - Test `translate_openai_to_gemini_response`: choices and usage metadata.
     - Test `translate_openai_sse_chunk_to_gemini`: text chunks, tool fragments, usage metadata.

3. **Verify Regression & Golden Parity**:
   - Run existing proxy and cache test suites:
     - `tests/test_hybrid_cache.py`
     - `tests/test_mitm_addon.py`
     - `tests/test_mitm_addon_sse.py`
     - `tests/proxy/test_translation.py`
     - `tests/proxy/test_addon_pipeline_parity.py`
   - Confirm 100% test pass rate with zero behavioral drift.

### Dependencies & Criticality

- **Dependencies:** Step 1, Step 2, Step 3, Step 4
- **Is bottleneck:** Yes — Confirms correctness and behavioral invariance across all providers before finalizing gates.

### Safety & Constraint Considerations

- **Relevant rules:** §3 Testing Constraints, Rule 1 (Zero Synthetic Data for Benchmarking).
- **Failure modes:** Subtle fixture mismatch between original tests and provider direct tests.
- **Guardrails:** Use existing verified wire fixtures and payload patterns for all assertions.

### Success & Discard Criteria

- **Success:** All new tests in `tests/providers/` pass cleanly; all existing test suites pass with 0 failures under `uv run pytest`.
- **Discard:** Discard if regressions are found in legacy test assertions.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.99  |
| entropy_pred        | 0.60  |
| impact_pred         | 8.50  |
| cost_pred           | 0.10  |
| learning_value_pred | 1.50  |
| ev_pred             | 8.89  |

### Step Metrics Rationale

- $\text{EV} = 0.99 \times 8.50 + 0.5 \times 1.50 - 0.3 \times 0.60 - 0.10 = 8.415 + 0.75 - 0.18 - 0.10 = 8.885 \approx 8.89$. Comprehensive unit test coverage directly targeting provider format implementations validates protocol compliance and guarantees regression-free operations.

---

## Step 6: Complexity Ratchet Audit, Hygiene & Full Gate Verification

### Step Intent & Git Integration

- **Sub-intent recommendation:** none
- **Reasoning:** Audit the entire repository for strict Bean 0186 complexity compliance, update the ratchet ceiling in `tests/test_complexity_baseline.py` to lock in the elimination of legacy `# noqa` suppressions, format markdown documentation with Prettier, verify Ruff checks, and ensure a single clean squashed commit.
- **Step type:** validation
- **Exploration level:** 0.05
- **Git branch:** `I-1793405506-coherence-one-provider-module-per-wire-format`

### Implementation Details

1. **Complexity Ratchet Audit**:
   - Inspect all eliminated `# noqa` complexity suppressions in `payload_cleaner.py`, `parsers/sse.py`, `parsers/tokens.py`, `hybrid_cache.py`, and `proxy/translation/gemini_openai.py`.
   - Verify that all newly created modules in `src/holon_coherence/providers/` have zero `# noqa` complexity suppressions and satisfy:
     - McCabe cyclomatic complexity: $C901 \le 10$
     - Maximum function returns: $PLR0911 \le 6$
     - Maximum branches: $PLR0912 \le 12$
     - Maximum function arguments: $PLR0913 \le 5$
     - Maximum function statements: $PLR0915 \le 50$
   - Run `test_complexity_baseline_ratchet_ceiling`:
     ```bash
     uv run pytest tests/test_complexity_baseline.py
     ```
   - Update `BASELINE_CEILING` in `tests/test_complexity_baseline.py` to match the exact newly reduced count of inline complexity suppressions (ratcheting down from 38).

2. **Full Pytest Suite Execution**:
   - Execute the entire test suite from the root of the worktree:
     ```bash
     uv run pytest
     ```
   - Confirm 100% passing tests with zero regressions.

3. **Ruff Linting and Formatting**:
   - Run Ruff linter and formatter:
     ```bash
     uv run ruff check .
     uv run ruff format --check .
     ```

4. **Documentation and Markdown Formatting**:
   - Format all markdown documentation and plan artifacts using Prettier:
     ```bash
     npx prettier --write "**/*.md"
     ```

5. **Squash Commits & Clean Working Tree**:
   - Ensure all feature changes are squashed into a single logical commit relative to `origin/main` according to Holon git workflow rules.

### Dependencies & Criticality

- **Dependencies:** Step 1, Step 2, Step 3, Step 4, Step 5
- **Is bottleneck:** Yes — Final gate for acceptance criteria fulfillment.

### Safety & Constraint Considerations

- **Relevant rules:** §1 Runtime & Environment, §2 Coding Conventions & Standards, §3 Testing Constraints, Worktree Isolation & Squash Commits.
- **Failure modes:** Unintended ratchet drift or unformatted markdown.
- **Guardrails:** Automated test execution via `uv run pytest` and static checks with Ruff prior to completion.

### Success & Discard Criteria

- **Success:** Full `uv run pytest` suite passes, Ruff checks report 0 errors, ratchet ceiling updated and passing, Prettier passes, and git history is squashed cleanly.
- **Discard:** Discard if any test failure, complexity violation, or lint error persists.

### Step Metrics Table

| metric              | value |
| :------------------ | :---- |
| p_success_pred      | 0.99  |
| entropy_pred        | 0.50  |
| impact_pred         | 9.00  |
| cost_pred           | 0.08  |
| learning_value_pred | 1.00  |
| ev_pred             | 9.18  |

### Step Metrics Rationale

- $\text{EV} = 0.99 \times 9.00 + 0.5 \times 1.00 - 0.3 \times 0.50 - 0.08 = 8.91 + 0.50 - 0.15 - 0.08 = 9.18$. Final validation gate enforces the permanent complexity ratchet reduction, validates full test suite integrity, and guarantees pristine repository hygiene.

---

## Strategy Rationale

The overall plan metrics are computed using the physics-driven Expected Value (EV) formula:

$$\text{EV} = P(\text{success}) \times \text{Impact} + \mu \times \text{LearningValue} - \lambda \times \Delta S_{\text{intent}} - \text{Cost}$$

Using baseline calibration constants $\lambda = 0.3$ and $\mu = 0.5$:

$$\text{EV} = (0.98 \times 8.90) + (0.5 \times 2.50) - (0.3 \times 3.80) - 0.85 = 8.722 + 1.25 - 1.14 - 0.85 = 7.982 \approx 7.98$$

- **$P(\text{success})$ (0.98):** The refactoring strategy relies on clean polymorphic delegation conforming to a well-defined `ProviderFormat` protocol. Because existing behavior is comprehensively pinned by existing test suites in `tests/test_mitm_addon.py`, `tests/test_mitm_addon_sse.py`, and `tests/test_hybrid_cache.py`, regressions are prevented systematically.
- **$\text{Impact}$ (8.90):** Deconstructs duplicated multi-branch conditional cascades across 5 critical files (`parsers/sse.py`, `parsers/tokens.py`, `hybrid_cache.py`, `payload_cleaner.py`, and `proxy/translation/gemini_openai.py`), eliminating up to 13 legacy `# noqa` complexity suppressions and establishing the Open-Closed Principle for future provider wire format additions.
- **$\mu \times \text{LearningValue}$ ($0.5 \times 2.50 = 1.25$):** Codifies reusable provider protocol design, granular function decomposition patterns for strict Bean 0186 compliance, and complexity ratchet reduction practices.
- **$\lambda \times \Delta S\_{\text{intent}}$ ($0.3 \times 3.80 = 1.14$):** Bounded entropy distribution across the 6 execution steps totaling 3.80, remaining safely below the allocated 5.0 entropy budget.
- **$\text{Cost}$ (0.85):** Direct implementation cost covering module creation, protocol wiring, granular function decomposition, comprehensive test suite authoring under `tests/providers/`, and multi-gate pytest/ruff execution.

---

## Planner Autonomy Summary

- **Intent handling:** `ACCEPT_AS_IS`
- **Reframed intent (if applicable):** NONE
- **Exploration stance:** Exploitation-dominant (0.05 exploration). The boundaries of the provider modules (`anthropic.py`, `openai.py`, `gemini.py`, `translation.py`, `base.py`), the consumer files, and the acceptance criteria are clearly specified in the intent. The task requires structural consolidation and polymorphic delegation with zero behavioral drift.
- **Safety priority level:** `standard`
- **Priority Justification:** All refactoring operations are purely structural, architectural, and complexity-reducing. No network interception routes, MITM certificate handling, or wire logging guarantees are modified. All public entry points remain fully backward-compatible.

---

## Exploration

- **Proportion of steps that are exploratory:** 0.05
- **Justification:** The wire formats for Anthropic, OpenAI, and Gemini are already mature and thoroughly exercised in the codebase. Minimal exploration (0.05) is allocated for verifying internal helper signatures across consumers and ensuring seamless import compatibility across packages.

---

## Safety & Constraint Alignment

- **Key world ruleset constraints that affect this plan:**
  - `holon-config/world/ruleset.md`: Runtime compatibility with Python 3.13, execution of tests strictly via `uv run pytest`, Ruff lint and format cleanliness, docstring and comment preservation.
  - Bean 0186 Complexity Limits: Enforce McCabe $C901 \le 10$, $PLR0911 \le 6$, $PLR0912 \le 12$, $PLR0913 \le 5$, $PLR0915 \le 50$. Verify and ratchet down `BASELINE_CEILING` in `tests/test_complexity_baseline.py`.
  - Testing constraints: Zero test failures under `uv run pytest`, 100% preservation of existing test cases, and authentic non-synthetic test fixtures (Rule 1).
  - Git workflow constraints: Dedicated worktree branching off `origin/main`, single squashed commit relative to `main`, no autonomous remote push.
- **Potential violations or edge cases:**
  - Circular import cycles: Dependencies between `holon_coherence.providers` and `holon_coherence.parsers` or `payload_cleaner.py`.
  - Ratchet ceiling mismatch: Eliminating `# noqa` suppressions without ratcheting down `BASELINE_CEILING` in `tests/test_complexity_baseline.py`, triggering test failure.
  - Subtle token fallback divergence: Breaking the `chars // 4` fallback heuristic when SSE or dictionary payloads lack explicit usage metadata.
  - Cache key drift: Differences in `extract_cache_key_parts` altering semantic hashing in `HybridCacheStore`.
- **Mitigations built into the plan:**
  - Pure protocol base: `base.py` imports only typing primitives and `TokenCounts`, avoiding any upward dependency on consumers.
  - Backward-compatible facades: Existing module functions (`extract_sse_content`, `extract_sse_token_counts`, `extract_token_counts`, `process_payload`) retain identical public signatures and delegate to `get_provider(provider)`.
  - Complexity ratchet update: Step 6 audits all eliminated `# noqa` comments and updates `BASELINE_CEILING` in `tests/test_complexity_baseline.py`.
  - Extensive regression testing: Steps 5 and 6 validate golden parity fixtures (`test_addon_pipeline_parity.py`) and existing cache/SSE test suites.
- **Allocated Entropy Budget:** 5.0
- **Predicted Plan Entropy:** 3.80 (sum of step entropies: $0.40 + 0.60 + 0.80 + 0.90 + 0.60 + 0.50 = 3.80$)
- **Budget Compliance:** Full compliance ($3.80 \le 5.00$).

---

## Plan Description & Strategy

1. **Step 1: Provider Architecture, Protocol Specification & Registry (`src/holon_coherence/providers/`)**:
   Establish `src/holon_coherence/providers/base.py` with runtime-checkable `ProviderFormat` protocol defining `clean`, `token_counts_from_sse`, `token_counts_from_dict`, `extract_sse_content`, and `extract_cache_key_parts`. Implement provider registry and resolution factory in `src/holon_coherence/providers/__init__.py`.
2. **Step 2: Implement Anthropic Format Module (`src/holon_coherence/providers/anthropic.py`)**:
   Migrate Anthropic payload cleaning (tool deduplication, turn truncation/summarization, cache breakpoint injection), SSE stream parsing, token counting, and cache key extraction into `AnthropicProvider`, decomposing all helpers strictly below Bean 0186 complexity limits.
3. **Step 3: Implement OpenAI & Gemini Format Modules & Encapsulate Translation (`openai.py`, `gemini.py`, `translation.py`)**:
   Implement `OpenAIProvider` and `GeminiProvider`. Encapsulate bidirectional protocol translation in `src/holon_coherence/providers/translation.py`, decomposing monolithic functions into modular subroutines with zero `# noqa` suppressions and re-exporting via `proxy/translation/gemini_openai.py`.
4. **Step 4: Refactor Consumer Subsystems (`payload_cleaner.py`, `parsers/sse.py`, `parsers/tokens.py`, `hybrid_cache.py`)**:
   Refactor `JSONContextCleaner`, `parsers/sse.py`, `parsers/tokens.py`, and `HybridCacheStore` to resolve the provider object once via `get_provider(provider)` and delegate format operations polymorphically, eliminating legacy branching blocks and `# noqa` suppressions.
5. **Step 5: Provider Test Suite & Backward-Compatibility Verification (`tests/providers/`)**:
   Create direct unit test modules in `tests/providers/` (`test_anthropic.py`, `test_openai.py`, `test_gemini.py`, `test_translation.py`, `test_registry.py`). Verify that all existing test suites continue to pass cleanly.
6. **Step 6: Complexity Ratchet Audit, Hygiene & Full Gate Verification**:
   Audit the elimination of legacy `# noqa` suppressions, update `BASELINE_CEILING` in `tests/test_complexity_baseline.py`, run full `uv run pytest`, execute Ruff linter/formatter, format markdown with Prettier, and prepare squashed git commit.
