# Plan Calibration Report: P-1795500046-ANA-G4A

- **Plan Reference:**
  [`plans/I-1795500029-coherence-providers-self-doc/P-1795500046-ANA-G4A.md`](P-1795500046-ANA-G4A.md)
- **Execution ID:** `E-1795500223-ANA-G4A`
- **Execution Branch:** `I-1795500029-coherence-providers-self-doc/P-1795500046-ANA-G4A/E-1795500223-ANA-G4A/_`
- **Intent Branch:** `I-1795500029-coherence-providers-self-doc/_`
- **Evaluating Agent:** `antigravity-agent/gemini-4-argon`
- **Evaluation Timestamp:** `2026-11-24T07:30:22.000Z`
- **Evaluated Commit SHA:** `23a259149c738a78e2cd19f081525814a1a96ec8`
- **Base SHA:** `1b18f146758f2c29066ea0689a847590062c1159`
- **Merge-Base SHA:** `1b18f146758f2c29066ea0689a847590062c1159`
- **Merged Commits:** `1`
- **Patch Size Base:** `target_merge_base` (merge-base `1b18f146758f2c29066ea0689a847590062c1159` with the target
  branch)

---

## 1. Executive Calibration Summary

| Metric                                             | Predicted (`pred`) | Actual (`actual`) | Absolute Error (`abs(pred - actual)`) | Accuracy Rating | Bias Direction             |
| :------------------------------------------------- | :----------------- | :---------------- | :------------------------------------ | :-------------- | :------------------------- |
| **$P(\text{success})$**                            | `0.99`             | `1.00`            | `0.01`                                | High (≤ 0.05)   | Slight Underconfidence     |
| **Entropy ($\Delta S$)**                           | `1.80`             | `1.72`            | `0.08`                                | High (≤ 1.0)    | Overestimated Risk         |
| **Impact**                                         | `8.70`             | `8.70`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Cost**                                           | `0.45`             | `0.50`            | `0.05`                                | High (≤ 1.0)    | Highly Accurate            |
| **Learning Value**                                 | `1.80`             | `1.80`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Expected Value — Clean (without bugs)**          | `8.52`             | `8.58`            | `0.06`                                | High            | Conservative Underestimate |
| **Expected Value — Observed (with bugs included)** | `8.52`             | `8.58`            | `0.06`                                | High            | Conservative Underestimate |
| **Bug EV Drag**                                    | `0.00`             | `0.00`            | `0.00`                                | -               | Drag Penalty               |

---

## 2. Mathematical Derivations & Calibration Errors

- **Success Probability Error:** $|0.99 - 1.00| = 0.01$
- **Entropy Error:** $|1.80 - 1.72| = 0.08$
- **Impact Error:** $|8.70 - 8.70| = 0.00$
- **Cost Error:** $|0.45 - 0.50| = 0.05$
- **Learning Value Error:** $|1.80 - 1.80| = 0.00$
- **Expected Value Realization:**
  $$EV_{\text{pred}} = 0.99 \times 8.7 + 0.5 \times 1.8 - 0.3 \times 1.80 - 0.45 = 8.52$$
  $$EV_{\text{actual}} = EV_{\text{clean}} = 1.00 \times 8.7 + 0.5 \times 1.8 - 0.3 \times 1.72 - 0.50 = 8.58$$
  $$EV_{\text{with\_bugs}} = 1.00 \times 8.7 + 0.5 \times 1.8 - 0.3 \times 1.72 - 0.50 = 8.58$$
  $$\text{Bug EV Drag} = round(EV_{\text{clean}} - EV_{\text{with\_bugs}}, 2) = 0.00$$ $$\Delta EV = +0.06$$

---

## 3. Entropy Factor Breakdown

- **State Surface Area (SSA):** Predicted `0.6` vs Observed `5.6` (16 files modified).
- **Irreversibility (IRR):** Predicted `0.0` vs Observed `0.0` (Zero destructive or stateful changes).
- **Conflict Likelihood (CL):** Predicted `0.1` vs Observed `0.0` (Clean sequential branch merges).
- **Sandbox Escape Risk (SER):** Predicted `0.0` vs Observed `0.0` (Zero security exceptions).
- **Novelty (NOV):** Predicted `0.4` vs Observed `0.4` (Standard calibration reporting schema).

---

## 4. Calibration Assessment

Plan `P-1795500046-ANA-G4A` executed with minimal error ($p\_success\_error = 0.01$, $cost\_error = 0.05$). The
calibration step successfully completed the execution lifecycle and delivered verified post-execution analysis.

---

## 5. Touch Set Accuracy

- **Precision (declared entries the diff touched):** `100.0%`
- **Recall (changed files the touch set covered):** `100.0%`

Changed files outside the touch set:

- none

Declared entries the diff did not touch:

- none
