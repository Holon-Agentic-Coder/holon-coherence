# Methodical How-To: Ringer Multi-Agent Tiering Framework

## 🎯 Objective & Architectural Overview

In conventional monolithic agent architectures, a single flagship model executes all tasks across the entire development
lifecycle—from high-level system architecture and security design down to boilerplate styling, shell command execution,
and test log parsing.

Flagship reasoning models (Tier 1) feature exceptional cognitive capabilities but incur significant cost and latency
penalties. Conversely, high-throughput models (Tier 2) operate with sub-second token generation at a fraction of the
cost, making them ideal for high-volume, structured execution tasks.

**Ringer Multi-Agent Framework** implements a hierarchical division of labor:

1. **Tier 1 (Flagship Architect)**: Performs high-level architectural planning, system RFC authoring, interface design,
   and final quality verification.
2. **Tier 2 (High-Throughput Executor)**: Receives discrete, structured subtasks from the Architect and handles bulk
   implementation code, CSS styling, unit test authoring, and test execution.
3. **Subtask Result Compression**: The Executor summarizes verbose shell outputs, build logs, and test traces into
   compact structural status reports before returning control to the Architect, preventing child execution logs from
   bloating the Architect's parent context window.

---

## 🏛️ Codebase Architecture & Source Locations

| Component                     | Repository Path                                                                     | Core Function / Class                                  |
| :---------------------------- | :---------------------------------------------------------------------------------- | :----------------------------------------------------- |
| **Ringer Orchestrator**       | `apps/sandbox-executor/src/sandbox_executor/token_reduction/ringer_orchestrator.py` | `RingerOrchestrator.plan_subtask()`, `record_result()` |
| **Subtask Result Summarizer** | `apps/sandbox-executor/src/sandbox_executor/token_reduction/ringer_orchestrator.py` | `SubtaskResult._summarize()`                           |
| **Unified Benchmark Harness** | `todo/ab_measure_all_methods.py`                                                    | Multi-turn tiered execution suites                     |

---

## ⚙️ Prerequisites & Environment Setup

### 1. Dynamic Model Discovery (Zero Hardcoded Models)

In compliance with repository invariants, never hardcode model names. Execute `agy models` at runtime:

```bash
agy models
```

Categorize discovered models into operational tiers:

- **Tier 1 (Architect)**: Select the highest reasoning model in the catalog (e.g., `gemini-3.8-flash-high` or
  `claude-sonnet-4-6`).
- **Tier 2 (Executor)**: Select the high-throughput execution model (e.g., `gemini-3.8-flash-low` or
  `gemini-3.7-flash-low`).

```python
import subprocess


def get_active_tiers() -> tuple[str, str]:
    output = subprocess.run(
        ["agy", "models"], capture_output=True, text=True, check=True
    ).stdout
    lines = [
        line.split()[0]
        for line in output.splitlines()
        if line.strip() and not line.startswith("Fetching")
    ]

    # In AGY, gemini-3.8-flash-high is the flagship reasoning tier
    tier1 = next(
        (m for m in ["gemini-3.8-flash-high", "claude-sonnet-4-6"] if m in lines),
        lines[0],
    )
    # Tier 2 is the high-throughput executor tier
    tier2 = next(
        (
            m
            for m in ["gemini-3.8-flash-low", "gemini-3.7-flash-low"]
            if m in lines
        ),
        lines[-1],
    )

    return tier1, tier2


tier1_model, tier2_model = get_active_tiers()
print(f"Tier 1 Architect: {tier1_model}")
print(f"Tier 2 Executor:  {tier2_model}")
```

### 2. Verify Deliverable Workspace Directories

Ensure the output directories exist for tangible artifacts:

```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
mkdir -p "${REPO_ROOT}/todo/artifacts/generate_website"
mkdir -p "${REPO_ROOT}/todo/artifacts/ideate_holon"
```

---

## 🔬 High-Volume Workload Execution (Real LLMs)

The Ringer framework executes authentic multi-turn workflows where both input and output context exceed 10,000 tokens.

### Step 1: Initialize the Ringer Orchestrator

```python
import sys
from pathlib import Path

repo_root = Path(".").resolve()
sys.path.insert(0, str(repo_root / "apps/sandbox-executor/src"))
from sandbox_executor.token_reduction import RingerOrchestrator

orchestrator = RingerOrchestrator(
    architect_model=tier1_model,
    executor_model=tier2_model,
)
```

### Step 2: Turn 1 — Architectural Specification (Tier 1 Architect)

The Architect analyzes the codebase and generates the full design specification (`dashboard_design.md`) and semantic
HTML5 skeleton (`index.html`):

```bash
agy exec --model "${tier1_model}" << 'EOF'
Role: System Architect (Tier 1)
Analyze the Holon token reduction proxy and draft the complete architectural specification in todo/artifacts/generate_website/dashboard_design.md with Mermaid diagrams.
Next, produce the standalone HTML5 dashboard structure in todo/artifacts/generate_website/index.html.
EOF
```

_Telemetry Result_: **39,816 input tokens**, **33,764 output tokens**, 4,111 thinking tokens.

### Step 3: Turn 2 — Bulk Code Implementation (Tier 2 Executor)

The Architect delegates styling and client logic implementation to the low-cost Tier 2 Executor:

```bash
agy exec --model "${tier2_model}" << 'EOF'
Role: High-Throughput Executor (Tier 2)
Implement complete dark-mode responsive styling in todo/artifacts/generate_website/styles.css.
Implement the real-time telemetry streaming simulation and SVG token savings graph in todo/artifacts/generate_website/app.js.
Output full production code without placeholders.
EOF
```

_Telemetry Result_: **26,012 input tokens**, **12,066 output tokens**, **0 thinking tokens**.

### Step 4: Turn 3 — Test Suite Authoring & Execution (Tier 2 Executor)

The Executor writes and runs an automated Python unit test suite:

```bash
agy exec --model "${tier2_model}" << 'EOF'
Role: High-Throughput Executor (Tier 2)
Write an automated unit test suite in todo/artifacts/generate_website/test_dashboard.py asserting:
1. index.html contains <!DOCTYPE html>, links styles.css, and imports app.js.
2. styles.css includes dark mode styling rules.
3. app.js contains DOM event listeners and telemetry logic.
Run the test suite and verify 100% pass rate.
EOF
```

_Telemetry Result_: **16,257 input tokens**, **1,010 output tokens**.

### Step 5: Subtask Result Compression

Instead of passing the raw 50-line terminal test output back to the Architect, `SubtaskResult` compresses the execution
log:

```python
from sandbox_executor.token_reduction.ringer_orchestrator import SubtaskResult

raw_test_output = """
test_01_html_structure (test_dashboard.TestDashboard) ... ok
test_02_styles_css_presence (test_dashboard.TestDashboard) ... ok
test_03_styles_css_dark_mode (test_dashboard.TestDashboard) ... ok
test_04_app_js_event_listeners (test_dashboard.TestDashboard) ... ok

----------------------------------------------------------------------
Ran 4 tests in 0.001s

OK
"""

result = SubtaskResult(
    task_id="test_suite", success=True, raw_output=raw_test_output
)
print("Compressed Output passed to Architect:\n", result.summary)
```

---

## 📊 Verification & Telemetry Extraction

### 1. Empirical Workload Telemetry Log

From our live benchmark run across both workload suites (`ab_measure_all_methods.py`):

|   Turn #   | Model                   |      Role      | Input Tokens | Output Tokens | Thinking Tokens | Cache Reads |
| :--------: | :---------------------- | :------------: | :----------: | :-----------: | :-------------: | :---------: |
| **Turn 1** | `gemini-3.8-flash-high` | Architect (T1) |    39,816    |    33,764     |      4,111      |    8,174    |
| **Turn 2** | `gemini-3.8-flash-low`  | Executor (T2)  |    26,012    |    12,066     |        0        |    8,167    |
| **Turn 3** | `gemini-3.8-flash-low`  | Executor (T2)  |    16,257    |     1,010     |        0        |      0      |
| **Turn 4** | `gemini-3.8-flash-high` | Architect (T1) |    99,098    |    32,342     |      4,430      |   257,337   |
| **Turn 5** | `gemini-3.8-flash-low`  | Executor (T2)  |    49,156    |     4,900     |        0        |      0      |

### 2. Token Distribution & Cost Savings Calculation

- **Total Execution Tokens**: 314,421 tokens.
- **Tier 1 Tokens**: 205,020 tokens (**65.2%**).
- **Tier 2 Tokens**: 109,401 tokens (**34.8%**).

**Monetary Financial Impact**:

- **Baseline Cost (100% Tier 1 Monolith)**: **$3.1060**
- **Optimized Cost (Ringer Multi-Agent Tiering)**: **$2.0344**
- **Net Monetary Savings**: **-$1.0716 per task run (-34.5% cost reduction)**

### 3. Acceptance Criteria & Functional Guardrails

1. **Tier 2 Delegation Ratio**: $\ge 30\%$ of total execution tokens successfully offloaded to low-cost Executor models
   (achieved **34.8%**).
2. **Functional Quality Guarantee**: All generated code must pass 100% of automated tests:
   ```bash
   DASHBOARD_DIR=todo/artifacts/generate_website python3 -m unittest todo/artifacts/generate_website/test_dashboard.py
   # Output: Ran 4 tests in 0.001s ... OK (100% pass)
   ```
3. **Artifact Completeness**: Full-scale deliverables generated without truncations:
   - `dashboard_design.md` (94 KB)
   - `index.html` (61 KB)
   - `styles.css` (12 KB)
   - `app.js` (20 KB)
   - `holon_architecture_rfc.md` (105 KB)

---

## 🛠️ Troubleshooting & Failure Modes

- **Over-Delegation**: Delegating ambiguous system design decisions to Tier 2 models can cause architectural drift. Tier
  2 should receive explicit, well-scoped prompts (e.g., "Implement this specific CSS file matching the design doc").
- **Loss of Critical Error Details**: If a subtask fails, `SubtaskResult` must retain the complete error traceback and
  failing test name so the Architect can diagnose the failure without having to re-run the commands.
