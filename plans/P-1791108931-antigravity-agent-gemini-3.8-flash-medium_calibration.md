# Plan Calibration Report: P-1791108931-antigravity-agent-gemini-3.8-flash-medium

- **Plan Reference:**
  [`plans/P-1791108931-antigravity-agent-gemini-3.8-flash-medium.md`](P-1791108931-antigravity-agent-gemini-3.8-flash-medium.md)
- **Execution Reference:** `E-1791109052-antigravity-agent-gemini-3.8-flash-medium` (recorded in
  `holon-knowledge/ledger/executions.jsonl`)
- **Intent Branch:** `I-1791108912-remove-coherence-executable-entrypoint/_`
- **Evaluating Agent:** `antigravity-agent/gemini-3.8-flash-medium`
- **Evaluation Timestamp:** `2026-10-04T14:57:35.000Z`

---

## 1. Executive Calibration Summary

| Metric                    | Predicted (`pred`) | Actual (`actual`) | Absolute Error (`abs(pred - actual)`) | Accuracy Rating | Bias Direction             |
| :------------------------ | :----------------- | :---------------- | :------------------------------------ | :-------------- | :------------------------- |
| **$P(\text{success})$**   | `0.98`             | `1.00`            | `0.02`                                | High (≤ 0.05)   | Slight Underconfidence     |
| **Entropy ($\Delta S$)**  | `0.50`             | `0.10`            | `0.40`                                | High (≤ 1.0)    | Overestimated Risk         |
| **Impact**                | `85.00`            | `85.00`           | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Cost**                  | `1.00`             | `0.85`            | `0.15`                                | High (≤ 1.0)    | Highly Accurate            |
| **Learning Value**        | `1.50`             | `1.50`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Expected Value ($EV$)** | `82.90`            | `84.87`           | `1.97`                                | High            | Conservative Underestimate |

---

## 2. Mathematical Derivations & Calibration Errors

- **Success Probability Error:** $|0.98 - 1.00| = 0.02$
- **Entropy Error:** $|0.50 - 0.10| = 0.40$
- **Impact Error:** $|85.00 - 85.00| = 0.00$
- **Cost Error:** $|1.00 - 0.85| = 0.15$
- **Learning Value Error:** $|1.50 - 1.50| = 0.00$
- **Expected Value Realization:**
  $$EV_{\text{pred}} = 0.98 \times 85.0 + 0.5 \times 1.5 - 0.3 \times 0.50 - 1.00 = 82.90$$
  $$EV_{\text{actual}} = 1.00 \times 85.0 + 0.5 \times 1.5 - 0.3 \times 0.10 - 0.85 = 84.87$$ $$\Delta EV = +1.97$$

---

## 3. Entropy Factor Breakdown

- **State Surface Area (SSA):** Predicted `0.6` vs Observed `0.2` (0 files modified).
- **Irreversibility (IRR):** Predicted `0.0` vs Observed `0.0` (Zero destructive or stateful changes).
- **Conflict Likelihood (CL):** Predicted `0.1` vs Observed `0.0` (Clean sequential branch merges).
- **Sandbox Escape Risk (SER):** Predicted `0.0` vs Observed `0.0` (Zero security exceptions).
- **Novelty (NOV):** Predicted `0.4` vs Observed `0.4` (Standard calibration reporting schema).

---

## 4. Calibration Assessment

Plan `P-1791108931-antigravity-agent-gemini-3.8-flash-medium` executed with minimal error ($p\_success\_error = 0.02$,
$cost\_error = 0.15$). The calibration step successfully completed the execution lifecycle and delivered verified
post-execution analysis.
