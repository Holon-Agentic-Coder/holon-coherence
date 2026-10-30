# Plan Calibration Report: P-1793349738-antigravity-agent-gemini-3.8-flash-medium

- **Plan Reference:**
  [`plans/P-1793349738-antigravity-agent-gemini-3.8-flash-medium.md`](P-1793349738-antigravity-agent-gemini-3.8-flash-medium.md)
- **Execution ID:** `E-1793349989-antigravity-agent-gemini-3.8-flash-medium`
- **Execution Branch:**
  `I-1793349723-coherence-split-mitm-addon-into-proxy-package/P-1793349738-antigravity-agent-gemini-3.8-flash-medium/E-1793349989-antigravity-agent-gemini-3.8-flash-medium/_`
- **Intent Branch:** `I-1793349723-coherence-split-mitm-addon-into-proxy-package/_`
- **Evaluating Agent:** `antigravity-agent/gemini-3.8-flash-medium`
- **Evaluation Timestamp:** `2026-10-30T09:21:40.000Z`
- **Evaluated Commit SHA:** `920e4d9a79e0b7a9925a3e6a62d4aec7af28b9e0`
- **Base SHA:** `eb3152764a269f91f6565ef69e435337482c159d`
- **Merge-Base SHA:** `eb3152764a269f91f6565ef69e435337482c159d`
- **Merged Commits:** `0`

---

## 1. Executive Calibration Summary

| Metric                    | Predicted (`pred`) | Actual (`actual`) | Absolute Error (`abs(pred - actual)`) | Accuracy Rating | Bias Direction             |
| :------------------------ | :----------------- | :---------------- | :------------------------------------ | :-------------- | :------------------------- |
| **$P(\text{success})$**   | `0.96`             | `1.00`            | `0.04`                                | High (≤ 0.05)   | Slight Underconfidence     |
| **Entropy ($\Delta S$)**  | `3.30`             | `3.04`            | `0.26`                                | High (≤ 1.0)    | Overestimated Risk         |
| **Impact**                | `8.50`             | `8.50`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Cost**                  | `0.85`             | `0.72`            | `0.13`                                | High (≤ 1.0)    | Highly Accurate            |
| **Learning Value**        | `2.00`             | `2.00`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Expected Value ($EV$)** | `7.32`             | `7.87`            | `0.55`                                | High            | Conservative Underestimate |

---

## 2. Mathematical Derivations & Calibration Errors

- **Success Probability Error:** $|0.96 - 1.00| = 0.04$
- **Entropy Error:** $|3.30 - 3.04| = 0.26$
- **Impact Error:** $|8.50 - 8.50| = 0.00$
- **Cost Error:** $|0.85 - 0.72| = 0.13$
- **Learning Value Error:** $|2.00 - 2.00| = 0.00$
- **Expected Value Realization:**
  $$EV_{\text{pred}} = 0.96 \times 8.5 + 0.5 \times 2.0 - 0.3 \times 3.30 - 0.85 = 7.32$$
  $$EV_{\text{actual}} = 1.00 \times 8.5 + 0.5 \times 2.0 - 0.3 \times 3.04 - 0.72 = 7.87$$ $$\Delta EV = +0.55$$

---

## 3. Entropy Factor Breakdown

- **State Surface Area (SSA):** Predicted `0.6` vs Observed `10.0` (22 files modified).
- **Irreversibility (IRR):** Predicted `0.0` vs Observed `0.0` (Zero destructive or stateful changes).
- **Conflict Likelihood (CL):** Predicted `0.1` vs Observed `0.0` (Clean sequential branch merges).
- **Sandbox Escape Risk (SER):** Predicted `0.0` vs Observed `0.0` (Zero security exceptions).
- **Novelty (NOV):** Predicted `0.4` vs Observed `0.4` (Standard calibration reporting schema).

---

## 4. Calibration Assessment

Plan `P-1793349738-antigravity-agent-gemini-3.8-flash-medium` executed with minimal error ($p\_success\_error = 0.04$,
$cost\_error = 0.13$). The calibration step successfully completed the execution lifecycle and delivered verified
post-execution analysis.
