# Plan Calibration Report: P-1793246842-claude-agent-claude-opus-5-5

- **Plan Reference:**
  [`plans/P-1793246842-claude-agent-claude-opus-5-5.md`](P-1793246842-claude-agent-claude-opus-5-5.md)
- **Execution ID:** `E-1793247065-claude-agent-claude-opus-5-5`
- **Execution Branch:**
  `I-1793246826-coherence-ci-timing-regression-gate/P-1793246842-claude-agent-claude-opus-5-5/E-1793247065-claude-agent-claude-opus-5-5/_`
- **Intent Branch:** `I-1793246826-coherence-ci-timing-regression-gate/_`
- **Evaluating Agent:** `claude-agent/claude-opus-5-5`
- **Evaluation Timestamp:** `2026-10-29T06:57:20.000Z`
- **Evaluated Commit SHA:** `f6a2a7ef0463b34b759585eea1f533aa51a1e113`
- **Base SHA:** `b33b5f4490ab8150dedc3e9038adf4c9b212bb51`
- **Merge-Base SHA:** `b33b5f4490ab8150dedc3e9038adf4c9b212bb51`
- **Merged Commits:** `0`

---

## 1. Executive Calibration Summary

| Metric                    | Predicted (`pred`) | Actual (`actual`) | Absolute Error (`abs(pred - actual)`) | Accuracy Rating | Bias Direction             |
| :------------------------ | :----------------- | :---------------- | :------------------------------------ | :-------------- | :------------------------- |
| **$P(\text{success})$**   | `0.85`             | `1.00`            | `0.15`                                | Moderate        | Slight Underconfidence     |
| **Entropy ($\Delta S$)**  | `1.20`             | `2.44`            | `1.24`                                | Moderate        | Underestimated Risk        |
| **Impact**                | `7.00`             | `7.00`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Cost**                  | `0.30`             | `0.50`            | `0.20`                                | High (≤ 1.0)    | Highly Accurate            |
| **Learning Value**        | `1.50`             | `1.50`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Expected Value ($EV$)** | `6.04`             | `6.52`            | `0.48`                                | High            | Conservative Underestimate |

---

## 2. Mathematical Derivations & Calibration Errors

- **Success Probability Error:** $|0.85 - 1.00| = 0.15$
- **Entropy Error:** $|1.20 - 2.44| = 1.24$
- **Impact Error:** $|7.00 - 7.00| = 0.00$
- **Cost Error:** $|0.30 - 0.50| = 0.20$
- **Learning Value Error:** $|1.50 - 1.50| = 0.00$
- **Expected Value Realization:**
  $$EV_{\text{pred}} = 0.85 \times 7.0 + 0.5 \times 1.5 - 0.3 \times 1.20 - 0.30 = 6.04$$
  $$EV_{\text{actual}} = 1.00 \times 7.0 + 0.5 \times 1.5 - 0.3 \times 2.44 - 0.50 = 6.52$$ $$\Delta EV = +0.48$$

---

## 3. Entropy Factor Breakdown

- **State Surface Area (SSA):** Predicted `0.6` vs Observed `8.0` (8 files modified).
- **Irreversibility (IRR):** Predicted `0.0` vs Observed `0.0` (Zero destructive or stateful changes).
- **Conflict Likelihood (CL):** Predicted `0.1` vs Observed `0.0` (Clean sequential branch merges).
- **Sandbox Escape Risk (SER):** Predicted `0.0` vs Observed `0.0` (Zero security exceptions).
- **Novelty (NOV):** Predicted `0.4` vs Observed `0.4` (Standard calibration reporting schema).

---

## 4. Calibration Assessment

Plan `P-1793246842-claude-agent-claude-opus-5-5` executed with minimal error ($p\_success\_error = 0.15$,
$cost\_error = 0.20$). The calibration step successfully completed the execution lifecycle and delivered verified
post-execution analysis.
