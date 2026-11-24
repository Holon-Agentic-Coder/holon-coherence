# Plan Calibration Report: P-1795515010-ANA-G4N

- **Plan Reference:** [`plans/I-1795514992-coherence-core-self-doc/P-1795515010-ANA-G4N.md`](P-1795515010-ANA-G4N.md)
- **Execution ID:** `E-1795515179-ANA-G4N`
- **Execution Branch:** `I-1795514992-coherence-core-self-doc/P-1795515010-ANA-G4N/E-1795515179-ANA-G4N/_`
- **Intent Branch:** `I-1795514992-coherence-core-self-doc/_`
- **Evaluating Agent:** `antigravity-agent/gemini-4-neon`
- **Evaluation Timestamp:** `2026-11-24T10:28:02.000Z`
- **Evaluated Commit SHA:** `24f6a79cb893290d06dbf692ceb16f8aeb693ba2`
- **Base SHA:** `9c9310fc9ad546937dc5ce2c681515ee36ed2bad`
- **Merge-Base SHA:** `9c9310fc9ad546937dc5ce2c681515ee36ed2bad`
- **Merged Commits:** `1`
- **Patch Size Base:** `target_merge_base` (merge-base `9c9310fc9ad546937dc5ce2c681515ee36ed2bad` with the target
  branch)

---

## 1. Executive Calibration Summary

| Metric                                             | Predicted (`pred`) | Actual (`actual`) | Absolute Error (`abs(pred - actual)`) | Accuracy Rating | Bias Direction             |
| :------------------------------------------------- | :----------------- | :---------------- | :------------------------------------ | :-------------- | :------------------------- |
| **$P(\text{success})$**                            | `0.99`             | `1.00`            | `0.01`                                | High (≤ 0.05)   | Slight Underconfidence     |
| **Entropy ($\Delta S$)**                           | `2.20`             | `1.63`            | `0.57`                                | High (≤ 1.0)    | Overestimated Risk         |
| **Impact**                                         | `9.00`             | `9.00`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Cost**                                           | `0.55`             | `0.50`            | `0.05`                                | High (≤ 1.0)    | Highly Accurate            |
| **Learning Value**                                 | `1.90`             | `1.90`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Expected Value — Clean (without bugs)**          | `8.65`             | `8.96`            | `0.31`                                | High            | Conservative Underestimate |
| **Expected Value — Observed (with bugs included)** | `8.65`             | `8.96`            | `0.31`                                | High            | Conservative Underestimate |
| **Bug EV Drag**                                    | `0.00`             | `0.00`            | `0.00`                                | -               | Drag Penalty               |

---

## 2. Mathematical Derivations & Calibration Errors

- **Success Probability Error:** $|0.99 - 1.00| = 0.01$
- **Entropy Error:** $|2.20 - 1.63| = 0.57$
- **Impact Error:** $|9.00 - 9.00| = 0.00$
- **Cost Error:** $|0.55 - 0.50| = 0.05$
- **Learning Value Error:** $|1.90 - 1.90| = 0.00$
- **Expected Value Realization:**
  $$EV_{\text{pred}} = 0.99 \times 9.0 + 0.5 \times 1.9 - 0.3 \times 2.20 - 0.55 = 8.65$$
  $$EV_{\text{actual}} = EV_{\text{clean}} = 1.00 \times 9.0 + 0.5 \times 1.9 - 0.3 \times 1.63 - 0.50 = 8.96$$
  $$EV_{\text{with\_bugs}} = 1.00 \times 9.0 + 0.5 \times 1.9 - 0.3 \times 1.63 - 0.50 = 8.96$$
  $$\text{Bug EV Drag} = round(EV_{\text{clean}} - EV_{\text{with\_bugs}}, 2) = 0.00$$ $$\Delta EV = +0.31$$

---

## 3. Entropy Factor Breakdown

- **State Surface Area (SSA):** Predicted `0.6` vs Observed `5.3` (11 files modified).
- **Irreversibility (IRR):** Predicted `0.0` vs Observed `0.0` (Zero destructive or stateful changes).
- **Conflict Likelihood (CL):** Predicted `0.1` vs Observed `0.0` (Clean sequential branch merges).
- **Sandbox Escape Risk (SER):** Predicted `0.0` vs Observed `0.0` (Zero security exceptions).
- **Novelty (NOV):** Predicted `0.4` vs Observed `0.4` (Standard calibration reporting schema).

---

## 4. Calibration Assessment

Plan `P-1795515010-ANA-G4N` executed with minimal error ($p\_success\_error = 0.01$, $cost\_error = 0.05$). The
calibration step successfully completed the execution lifecycle and delivered verified post-execution analysis.

---

## 5. Touch Set Accuracy

- **Precision (declared entries the diff touched):** `91.7%`
- **Recall (changed files the touch set covered):** `100.0%`

Changed files outside the touch set:

- none

Declared entries the diff did not touch:

- `src/holon_coherence/metrics_math.py`
