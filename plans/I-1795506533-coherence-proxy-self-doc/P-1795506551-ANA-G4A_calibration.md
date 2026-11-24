# Plan Calibration Report: P-1795506551-ANA-G4A

- **Plan Reference:** [`plans/I-1795506533-coherence-proxy-self-doc/P-1795506551-ANA-G4A.md`](P-1795506551-ANA-G4A.md)
- **Execution ID:** `E-1795506788-ANA-G4A`
- **Execution Branch:** `I-1795506533-coherence-proxy-self-doc/P-1795506551-ANA-G4A/E-1795506788-ANA-G4A/_`
- **Intent Branch:** `I-1795506533-coherence-proxy-self-doc/_`
- **Evaluating Agent:** `antigravity-agent/gemini-4-argon`
- **Evaluation Timestamp:** `2026-11-24T09:06:12.000Z`
- **Evaluated Commit SHA:** `e6b54e949fe398b37bfc48fb71f3cd9d0c9625fd`
- **Base SHA:** `91e94cc92ddb0a3936572736041282fc481476a8`
- **Merge-Base SHA:** `91e94cc92ddb0a3936572736041282fc481476a8`
- **Merged Commits:** `0`
- **Patch Size Base:** `plan`

---

## 1. Executive Calibration Summary

| Metric                                             | Predicted (`pred`) | Actual (`actual`) | Absolute Error (`abs(pred - actual)`) | Accuracy Rating | Bias Direction          |
| :------------------------------------------------- | :----------------- | :---------------- | :------------------------------------ | :-------------- | :---------------------- |
| **$P(\text{success})$**                            | `0.99`             | `1.00`            | `0.01`                                | High (≤ 0.05)   | Slight Underconfidence  |
| **Entropy ($\Delta S$)**                           | `2.40`             | `3.04`            | `0.64`                                | High (≤ 1.0)    | Underestimated Risk     |
| **Impact**                                         | `9.00`             | `9.00`            | `0.00`                                | Exact           | Perfectly Calibrated    |
| **Cost**                                           | `0.55`             | `0.50`            | `0.05`                                | High (≤ 1.0)    | Highly Accurate         |
| **Learning Value**                                 | `1.90`             | `1.90`            | `0.00`                                | Exact           | Perfectly Calibrated    |
| **Expected Value — Clean (without bugs)**          | `8.59`             | `8.54`            | `0.05`                                | High            | Optimistic Overestimate |
| **Expected Value — Observed (with bugs included)** | `8.59`             | `8.54`            | `0.05`                                | High            | Optimistic Overestimate |
| **Bug EV Drag**                                    | `0.00`             | `0.00`            | `0.00`                                | -               | Drag Penalty            |

---

## 2. Mathematical Derivations & Calibration Errors

- **Success Probability Error:** $|0.99 - 1.00| = 0.01$
- **Entropy Error:** $|2.40 - 3.04| = 0.64$
- **Impact Error:** $|9.00 - 9.00| = 0.00$
- **Cost Error:** $|0.55 - 0.50| = 0.05$
- **Learning Value Error:** $|1.90 - 1.90| = 0.00$
- **Expected Value Realization:**
  $$EV_{\text{pred}} = 0.99 \times 9.0 + 0.5 \times 1.9 - 0.3 \times 2.40 - 0.55 = 8.59$$
  $$EV_{\text{actual}} = EV_{\text{clean}} = 1.00 \times 9.0 + 0.5 \times 1.9 - 0.3 \times 3.04 - 0.50 = 8.54$$
  $$EV_{\text{with\_bugs}} = 1.00 \times 9.0 + 0.5 \times 1.9 - 0.3 \times 3.04 - 0.50 = 8.54$$
  $$\text{Bug EV Drag} = round(EV_{\text{clean}} - EV_{\text{with\_bugs}}, 2) = 0.00$$ $$\Delta EV = -0.05$$

---

## 3. Entropy Factor Breakdown

- **State Surface Area (SSA):** Predicted `0.6` vs Observed `10.0` (37 files modified).
- **Irreversibility (IRR):** Predicted `0.0` vs Observed `0.0` (Zero destructive or stateful changes).
- **Conflict Likelihood (CL):** Predicted `0.1` vs Observed `0.0` (Clean sequential branch merges).
- **Sandbox Escape Risk (SER):** Predicted `0.0` vs Observed `0.0` (Zero security exceptions).
- **Novelty (NOV):** Predicted `0.4` vs Observed `0.4` (Standard calibration reporting schema).

---

## 4. Calibration Assessment

Plan `P-1795506551-ANA-G4A` executed with minimal error ($p\_success\_error = 0.01$, $cost\_error = 0.05$). The
calibration step successfully completed the execution lifecycle and delivered verified post-execution analysis.

---

## 5. Touch Set Accuracy

- **Precision (declared entries the diff touched):** `100.0%`
- **Recall (changed files the touch set covered):** `100.0%`

Changed files outside the touch set:

- none

Declared entries the diff did not touch:

- none
