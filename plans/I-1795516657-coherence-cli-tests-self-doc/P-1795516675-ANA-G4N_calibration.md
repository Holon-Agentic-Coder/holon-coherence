# Plan Calibration Report: P-1795516675-ANA-G4N

- **Plan Reference:**
  [`plans/I-1795516657-coherence-cli-tests-self-doc/P-1795516675-ANA-G4N.md`](P-1795516675-ANA-G4N.md)
- **Execution ID:** `E-1795516949-ANA-G4N`
- **Execution Branch:** `I-1795516657-coherence-cli-tests-self-doc/P-1795516675-ANA-G4N/E-1795516949-ANA-G4N/_`
- **Intent Branch:** `I-1795516657-coherence-cli-tests-self-doc/_`
- **Evaluating Agent:** `antigravity-agent/gemini-4-neon`
- **Evaluation Timestamp:** `2026-11-24T11:01:53.000Z`
- **Evaluated Commit SHA:** `b38fd3431a1a86f691a8d6f0b5e2577facc14116`
- **Base SHA:** `c38beea5ac762922024e9ca1c59758d40576735f`
- **Merge-Base SHA:** `c38beea5ac762922024e9ca1c59758d40576735f`
- **Merged Commits:** `1`
- **Patch Size Base:** `target_merge_base` (merge-base `c38beea5ac762922024e9ca1c59758d40576735f` with the target
  branch)

---

## 1. Executive Calibration Summary

| Metric                                             | Predicted (`pred`) | Actual (`actual`) | Absolute Error (`abs(pred - actual)`) | Accuracy Rating | Bias Direction             |
| :------------------------------------------------- | :----------------- | :---------------- | :------------------------------------ | :-------------- | :------------------------- |
| **$P(\text{success})$**                            | `0.99`             | `1.00`            | `0.01`                                | High (≤ 0.05)   | Slight Underconfidence     |
| **Entropy ($\Delta S$)**                           | `2.00`             | `0.86`            | `1.14`                                | Moderate        | Overestimated Risk         |
| **Impact**                                         | `8.80`             | `8.80`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Cost**                                           | `0.55`             | `0.50`            | `0.05`                                | High (≤ 1.0)    | Highly Accurate            |
| **Learning Value**                                 | `1.80`             | `1.80`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Expected Value — Clean (without bugs)**          | `8.46`             | `8.94`            | `0.48`                                | High            | Conservative Underestimate |
| **Expected Value — Observed (with bugs included)** | `8.46`             | `8.94`            | `0.48`                                | High            | Conservative Underestimate |
| **Bug EV Drag**                                    | `0.00`             | `0.00`            | `0.00`                                | -               | Drag Penalty               |

---

## 2. Mathematical Derivations & Calibration Errors

- **Success Probability Error:** $|0.99 - 1.00| = 0.01$
- **Entropy Error:** $|2.00 - 0.86| = 1.14$
- **Impact Error:** $|8.80 - 8.80| = 0.00$
- **Cost Error:** $|0.55 - 0.50| = 0.05$
- **Learning Value Error:** $|1.80 - 1.80| = 0.00$
- **Expected Value Realization:**
  $$EV_{\text{pred}} = 0.99 \times 8.8 + 0.5 \times 1.8 - 0.3 \times 2.00 - 0.55 = 8.46$$
  $$EV_{\text{actual}} = EV_{\text{clean}} = 1.00 \times 8.8 + 0.5 \times 1.8 - 0.3 \times 0.86 - 0.50 = 8.94$$
  $$EV_{\text{with\_bugs}} = 1.00 \times 8.8 + 0.5 \times 1.8 - 0.3 \times 0.86 - 0.50 = 8.94$$
  $$\text{Bug EV Drag} = round(EV_{\text{clean}} - EV_{\text{with\_bugs}}, 2) = 0.00$$ $$\Delta EV = +0.48$$

---

## 3. Entropy Factor Breakdown

- **State Surface Area (SSA):** Predicted `0.6` vs Observed `2.8` (5 files modified).
- **Irreversibility (IRR):** Predicted `0.0` vs Observed `0.0` (Zero destructive or stateful changes).
- **Conflict Likelihood (CL):** Predicted `0.1` vs Observed `0.0` (Clean sequential branch merges).
- **Sandbox Escape Risk (SER):** Predicted `0.0` vs Observed `0.0` (Zero security exceptions).
- **Novelty (NOV):** Predicted `0.4` vs Observed `0.4` (Standard calibration reporting schema).

---

## 4. Calibration Assessment

Plan `P-1795516675-ANA-G4N` executed with minimal error ($p\_success\_error = 0.01$, $cost\_error = 0.05$). The
calibration step successfully completed the execution lifecycle and delivered verified post-execution analysis.

---

## 5. Touch Set Accuracy

- **Precision (declared entries the diff touched):** `100.0%`
- **Recall (changed files the touch set covered):** `100.0%`

Changed files outside the touch set:

- none

Declared entries the diff did not touch:

- none
