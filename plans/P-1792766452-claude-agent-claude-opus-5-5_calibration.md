# Plan Calibration Report: P-1792766452-claude-agent-claude-opus-5-5

- **Plan Reference:**
  [`plans/P-1792766452-claude-agent-claude-opus-5-5.md`](P-1792766452-claude-agent-claude-opus-5-5.md)
- **Execution ID:** `E-1792767369-claude-agent-claude-opus-5-5`
- **Execution Branch:**
  `I-1792762893-coherence-mitmweb-inspection-and-monotonic-readiness/P-1792766452-claude-agent-claude-opus-5-5/E-1792767369-claude-agent-claude-opus-5-5/_`
- **Intent Branch:** `I-1792762893-coherence-mitmweb-inspection-and-monotonic-readiness/_`
- **Evaluating Agent:** `claude-agent/claude-opus-5-5`
- **Evaluation Timestamp:** `2026-10-23T21:25:56.000Z`
- **Evaluated Commit SHA:** `de60a6db8663f81dcbc49fcfa383b7d388f0d389`
- **Base SHA:** `1c5f0d807dff07f28e07c74a2471e7c1f844601b`
- **Merge-Base SHA:** `1c5f0d807dff07f28e07c74a2471e7c1f844601b`
- **Merged Commits:** `0`

---

## 1. Executive Calibration Summary

| Metric                    | Predicted (`pred`) | Actual (`actual`) | Absolute Error (`abs(pred - actual)`) | Accuracy Rating | Bias Direction          |
| :------------------------ | :----------------- | :---------------- | :------------------------------------ | :-------------- | :---------------------- |
| **$P(\text{success})$**   | `0.93`             | `1.00`            | `0.07`                                | Moderate        | Slight Underconfidence  |
| **Entropy ($\Delta S$)**  | `0.30`             | `2.73`            | `2.43`                                | Moderate        | Underestimated Risk     |
| **Impact**                | `6.00`             | `6.00`            | `0.00`                                | Exact           | Perfectly Calibrated    |
| **Cost**                  | `0.15`             | `0.50`            | `0.35`                                | High (≤ 1.0)    | Highly Accurate         |
| **Learning Value**        | `1.00`             | `1.00`            | `0.00`                                | Exact           | Perfectly Calibrated    |
| **Expected Value ($EV$)** | `5.84`             | `5.18`            | `0.66`                                | High            | Optimistic Overestimate |

---

## 2. Mathematical Derivations & Calibration Errors

- **Success Probability Error:** $|0.93 - 1.00| = 0.07$
- **Entropy Error:** $|0.30 - 2.73| = 2.43$
- **Impact Error:** $|6.00 - 6.00| = 0.00$
- **Cost Error:** $|0.15 - 0.50| = 0.35$
- **Learning Value Error:** $|1.00 - 1.00| = 0.00$
- **Expected Value Realization:**
  $$EV_{\text{pred}} = 0.93 \times 6.0 + 0.5 \times 1.0 - 0.3 \times 0.30 - 0.15 = 5.84$$
  $$EV_{\text{actual}} = 1.00 \times 6.0 + 0.5 \times 1.0 - 0.3 \times 2.73 - 0.50 = 5.18$$ $$\Delta EV = -0.66$$

---

## 3. Entropy Factor Breakdown

- **State Surface Area (SSA):** Predicted `0.6` vs Observed `9.0` (14 files modified).
- **Irreversibility (IRR):** Predicted `0.0` vs Observed `0.0` (Zero destructive or stateful changes).
- **Conflict Likelihood (CL):** Predicted `0.1` vs Observed `0.0` (Clean sequential branch merges).
- **Sandbox Escape Risk (SER):** Predicted `0.0` vs Observed `0.0` (Zero security exceptions).
- **Novelty (NOV):** Predicted `0.4` vs Observed `0.4` (Standard calibration reporting schema).

---

## 4. Calibration Assessment

Plan `P-1792766452-claude-agent-claude-opus-5-5` executed with minimal error ($p\_success\_error = 0.07$, $cost\_error =
0.35$). The calibration step successfully completed the execution lifecycle and delivered verified post-execution
analysis.

---

## 5. Review-Loop Annotation: Known-Wrong Predicted Metrics (Bean 0146)

> Added during the Stage 4 review loop, after `holon calibrate` produced sections 1–4 above (unchanged on the
> `/calibrated` branch).

The `plans.jsonl` row for `P-1792766452-claude-agent-claude-opus-5-5` was written by a planner whose metrics parser let
the last metrics table in the plan win (fixed in holon-agentic-coder PR #91), so it records a per-step table instead of
the plan's `## Overall Plan Metrics`. Calibration reads that row, so every **Predicted** value and every delta in
sections 1–2 is computed against the wrong baseline. The plan file's Overall values are:

| Metric         | Overall (plan file) | Recorded row (used above) |
| :------------- | :------------------ | :------------------------ |
| p_success_pred | 0.90                | 0.93                      |
| entropy_pred   | 4.40                | 0.30                      |
| impact_pred    | 8.50                | 6.00                      |
| cost_pred      | 1.60                | 0.15                      |
| learning_value | 3.50                | 1.00                      |
| ev_pred        | 6.48                | 5.84                      |

The ledger row is append-only and is not rewritten. A plans-ledger correction row, and calibration that prefers it, are
tracked by Bean 0146; recompute this report's deltas once that lands.
