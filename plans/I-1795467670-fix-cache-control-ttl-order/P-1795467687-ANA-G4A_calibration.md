# Plan Calibration Report: P-1795467687-ANA-G4A

- **Plan Reference:**
  [`plans/I-1795467670-fix-cache-control-ttl-order/P-1795467687-ANA-G4A.md`](P-1795467687-ANA-G4A.md)
- **Execution ID:** `E-1795493183-ANA-G4A`
- **Execution Branch:** `I-1795467670-fix-cache-control-ttl-order/P-1795467687-ANA-G4A/E-1795493183-ANA-G4A/_`
- **Intent Branch:** `I-1795467670-fix-cache-control-ttl-order/_`
- **Evaluating Agent:** `antigravity-agent/gemini-4-argon`
- **Evaluation Timestamp:** `2026-11-24T04:19:46.000Z`
- **Evaluated Commit SHA:** `f9e67f9cd4e56dd4d21bbf45cfebf5edeaccaa8e`
- **Base SHA:** `15119fd4b3480dc9bab939c5bc27b71eb4b6a6df`
- **Merge-Base SHA:** `15119fd4b3480dc9bab939c5bc27b71eb4b6a6df`
- **Merged Commits:** `0`
- **Patch Size Base:** `plan`

---

## 1. Executive Calibration Summary

| Metric                                             | Predicted (`pred`) | Actual (`actual`) | Absolute Error (`abs(pred - actual)`) | Accuracy Rating | Bias Direction             |
| :------------------------------------------------- | :----------------- | :---------------- | :------------------------------------ | :-------------- | :------------------------- |
| **$P(\text{success})$**                            | `0.98`             | `1.00`            | `0.02`                                | High (≤ 0.05)   | Slight Underconfidence     |
| **Entropy ($\Delta S$)**                           | `2.10`             | `0.91`            | `1.19`                                | Moderate        | Overestimated Risk         |
| **Impact**                                         | `8.80`             | `8.80`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Cost**                                           | `0.55`             | `0.50`            | `0.05`                                | High (≤ 1.0)    | Highly Accurate            |
| **Learning Value**                                 | `2.00`             | `2.00`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Expected Value — Clean (without bugs)**          | `8.44`             | `9.03`            | `0.59`                                | High            | Conservative Underestimate |
| **Expected Value — Observed (with bugs included)** | `8.44`             | `9.03`            | `0.59`                                | High            | Conservative Underestimate |
| **Bug EV Drag**                                    | `0.00`             | `0.00`            | `0.00`                                | -               | Drag Penalty               |

---

## 2. Mathematical Derivations & Calibration Errors

- **Success Probability Error:** $|0.98 - 1.00| = 0.02$
- **Entropy Error:** $|2.10 - 0.91| = 1.19$
- **Impact Error:** $|8.80 - 8.80| = 0.00$
- **Cost Error:** $|0.55 - 0.50| = 0.05$
- **Learning Value Error:** $|2.00 - 2.00| = 0.00$
- **Expected Value Realization:**
  $$EV_{\text{pred}} = 0.98 \times 8.8 + 0.5 \times 2.0 - 0.3 \times 2.10 - 0.55 = 8.44$$
  $$EV_{\text{actual}} = EV_{\text{clean}} = 1.00 \times 8.8 + 0.5 \times 2.0 - 0.3 \times 0.91 - 0.50 = 9.03$$
  $$EV_{\text{with\_bugs}} = 1.00 \times 8.8 + 0.5 \times 2.0 - 0.3 \times 0.91 - 0.50 = 9.03$$
  $$\text{Bug EV Drag} = round(EV_{\text{clean}} - EV_{\text{with\_bugs}}, 2) = 0.00$$ $$\Delta EV = +0.59$$

---

## 3. Entropy Factor Breakdown

- **State Surface Area (SSA):** Predicted `0.6` vs Observed `2.9` (5 files modified).
- **Irreversibility (IRR):** Predicted `0.0` vs Observed `0.0` (Zero destructive or stateful changes).
- **Conflict Likelihood (CL):** Predicted `0.1` vs Observed `0.0` (Clean sequential branch merges).
- **Sandbox Escape Risk (SER):** Predicted `0.0` vs Observed `0.0` (Zero security exceptions).
- **Novelty (NOV):** Predicted `0.4` vs Observed `0.4` (Standard calibration reporting schema).

---

## 4. Calibration Assessment

Plan `P-1795467687-ANA-G4A` executed with minimal error ($p\_success\_error = 0.02$, $cost\_error = 0.05$). The
calibration step successfully completed the execution lifecycle and delivered verified post-execution analysis.

---

## 5. Touch Set Accuracy

- **Precision (declared entries the diff touched):** `83.3%`
- **Recall (changed files the touch set covered):** `100.0%`

Changed files outside the touch set:

- none

Declared entries the diff did not touch:

- `src/holon_coherence/proxy/steps/clean_payload.py`
