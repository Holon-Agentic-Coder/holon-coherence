# Plan Calibration Report: P-1791537711-antigravity-agent-gemini-3.8-flash-medium

- **Plan Reference:**
  [`plans/P-1791537711-antigravity-agent-gemini-3.8-flash-medium.md`](P-1791537711-antigravity-agent-gemini-3.8-flash-medium.md)
- **Execution Reference:** `E-1791537961-antigravity-agent-gemini-3.8-flash-medium` (recorded in
  `holon-knowledge/ledger/executions.jsonl`)
- **Intent Branch:** `I-1791537698-coherence-security-and-network-hardening/_`
- **Evaluating Agent:** `antigravity-agent/gemini-3.8-flash-medium`
- **Evaluation Timestamp:** `2026-10-09T11:40:52.000Z`
- **Evaluated Commit SHA:** `27ddeda3c7efdaa7987113d2d7e1db433bdc987b`

---

## 1. Executive Calibration Summary

| Metric                    | Predicted (`pred`) | Actual (`actual`) | Absolute Error (`abs(pred - actual)`) | Accuracy Rating | Bias Direction             |
| :------------------------ | :----------------- | :---------------- | :------------------------------------ | :-------------- | :------------------------- |
| **$P(\text{success})$**   | `0.99`             | `1.00`            | `0.01`                                | High (≤ 0.05)   | Slight Underconfidence     |
| **Entropy ($\Delta S$)**  | `0.10`             | `1.50`            | `1.40`                                | Moderate        | Underestimated Risk        |
| **Impact**                | `88.00`            | `88.00`           | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Cost**                  | `0.50`             | `0.50`            | `0.00`                                | Exact           | Highly Accurate            |
| **Learning Value**        | `1.00`             | `1.00`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Expected Value ($EV$)** | `87.09`            | `87.55`           | `0.46`                                | High            | Conservative Underestimate |

---

## 2. Mathematical Derivations & Calibration Errors

- **Success Probability Error:** $|0.99 - 1.00| = 0.01$
- **Entropy Error:** $|0.10 - 1.50| = 1.40$
- **Impact Error:** $|88.00 - 88.00| = 0.00$
- **Cost Error:** $|0.50 - 0.50| = 0.00$
- **Learning Value Error:** $|1.00 - 1.00| = 0.00$
- **Expected Value Realization:**
  $$EV_{\text{pred}} = 0.99 \times 88.0 + 0.5 \times 1.0 - 0.3 \times 0.10 - 0.50 = 87.09$$
  $$EV_{\text{actual}} = 1.00 \times 88.0 + 0.5 \times 1.0 - 0.3 \times 1.50 - 0.50 = 87.55$$ $$\Delta EV = +0.46$$

---

## 3. Entropy Factor Breakdown

- **State Surface Area (SSA):** Predicted `0.6` vs Observed `4.9` (11 files modified).
- **Irreversibility (IRR):** Predicted `0.0` vs Observed `0.0` (Zero destructive or stateful changes).
- **Conflict Likelihood (CL):** Predicted `0.1` vs Observed `0.0` (Clean sequential branch merges).
- **Sandbox Escape Risk (SER):** Predicted `0.0` vs Observed `0.0` (Zero security exceptions).
- **Novelty (NOV):** Predicted `0.4` vs Observed `0.4` (Standard calibration reporting schema).

---

## 4. Calibration Assessment

Plan `P-1791537711-antigravity-agent-gemini-3.8-flash-medium` executed with minimal error ($p\_success\_error = 0.01$,
$cost\_error = 0.00$). The calibration step successfully completed the execution lifecycle and delivered verified
post-execution analysis.
