# Plan Calibration Report: P-1795794410-ANA-G4N

- **Plan Reference:** [`plans/I-1795794388-coherence-prune-self-doc/P-1795794410-ANA-G4N.md`](P-1795794410-ANA-G4N.md)
- **Execution ID:** `E-1795794509-ANA-G4N`
- **Execution Branch:** `I-1795794388-coherence-prune-self-doc/P-1795794410-ANA-G4N/E-1795794509-ANA-G4N/_`
- **Intent Branch:** `I-1795794388-coherence-prune-self-doc/_`
- **Evaluating Agent:** `antigravity-agent/gemini-4-neon`
- **Evaluation Timestamp:** `2026-11-27T15:58:22.000Z`
- **Evaluated Commit SHA:** `13d4b4b5ac71ed9cd214714a1cd8400e5edbfa34`
- **Base SHA:** `0b5bc2ba3386d9c2dce0aea196304abea1f4deb2`
- **Merge-Base SHA:** `0b5bc2ba3386d9c2dce0aea196304abea1f4deb2`
- **Merged Commits:** `0`
- **Patch Size Base:** `plan`

---

## 1. Executive Calibration Summary

| Metric                                             | Predicted (`pred`) | Actual (`actual`) | Absolute Error (`abs(pred - actual)`) | Accuracy Rating | Bias Direction          |
| :------------------------------------------------- | :----------------- | :---------------- | :------------------------------------ | :-------------- | :---------------------- |
| **$P(\text{success})$**                            | `0.97`             | `1.00`            | `0.03`                                | High (≤ 0.05)   | Slight Underconfidence  |
| **Entropy ($\Delta S$)**                           | `2.60`             | `2.06`            | `0.54`                                | High (≤ 1.0)    | Overestimated Risk      |
| **Impact**                                         | `0.75`             | `0.75`            | `0.00`                                | Exact           | Perfectly Calibrated    |
| **Cost**                                           | `0.10`             | `0.50`            | `0.40`                                | High (≤ 1.0)    | Highly Accurate         |
| **Learning Value**                                 | `0.15`             | `0.15`            | `0.00`                                | Exact           | Perfectly Calibrated    |
| **Expected Value — Clean (without bugs)**          | `-0.08`            | `-0.29`           | `0.21`                                | High            | Optimistic Overestimate |
| **Expected Value — Observed (with bugs included)** | `-0.08`            | `-0.29`           | `0.21`                                | High            | Optimistic Overestimate |
| **Bug EV Drag**                                    | `0.00`             | `0.00`            | `0.00`                                | -               | Drag Penalty            |

---

## 2. Mathematical Derivations & Calibration Errors

- **Success Probability Error:** $|0.97 - 1.00| = 0.03$
- **Entropy Error:** $|2.60 - 2.06| = 0.54$
- **Impact Error:** $|0.75 - 0.75| = 0.00$
- **Cost Error:** $|0.10 - 0.50| = 0.40$
- **Learning Value Error:** $|0.15 - 0.15| = 0.00$
- **Expected Value Realization:**
  $$EV_{\text{pred}} = 0.97 \times 0.8 + 0.5 \times 0.1 - 0.3 \times 2.60 - 0.10 = -0.08$$
  $$EV_{\text{actual}} = EV_{\text{clean}} = 1.00 \times 0.8 + 0.5 \times 0.1 - 0.3 \times 2.06 - 0.50 = -0.29$$
  $$EV_{\text{with\_bugs}} = 1.00 \times 0.8 + 0.5 \times 0.1 - 0.3 \times 2.06 - 0.50 = -0.29$$
  $$\text{Bug EV Drag} = round(EV_{\text{clean}} - EV_{\text{with\_bugs}}, 2) = 0.00$$ $$\Delta EV = -0.21$$

---

## 3. Entropy Factor Breakdown

- **State Surface Area (SSA):** Predicted `0.6` vs Observed `6.7` (10 files modified).
- **Irreversibility (IRR):** Predicted `0.0` vs Observed `0.0` (Zero destructive or stateful changes).
- **Conflict Likelihood (CL):** Predicted `0.1` vs Observed `0.0` (Clean sequential branch merges).
- **Sandbox Escape Risk (SER):** Predicted `0.0` vs Observed `0.0` (Zero security exceptions).
- **Novelty (NOV):** Predicted `0.4` vs Observed `0.4` (Standard calibration reporting schema).

---

## 4. Calibration Assessment

Plan `P-1795794410-ANA-G4N` executed with minimal error ($p\_success\_error = 0.03$, $cost\_error = 0.40$). The
calibration step successfully completed the execution lifecycle and delivered verified post-execution analysis.

---

## 5. Touch Set Accuracy

- **Precision (declared entries the diff touched):** `100.0%`
- **Recall (changed files the touch set covered):** `100.0%`

Changed files outside the touch set:

- none

Declared entries the diff did not touch:

- none

---

## 6. Review Churn

- **Full reviews:** `1`
- **Scoped reviews:** `0`
- **Approval carry-overs:** `0`
- **Pipeline runs:** `1`
- **Pipeline reruns:** `0`
- **Non-defect churn (target merge):** `0`
- **Non-defect churn (bookkeeping):** `0`
- **Non-defect churn (CI noise):** `0`

---

## 7. Self-Explaining Code Counts

Against the merge base with origin/main: added 0 docstring(s), added 0 comment(s), removed 0 docstring(s) and removed 0
comment(s) across 6 changed file(s).

- Changed files checked: 6
- Added docstrings: 0
- Added comments (not '# why:'): 0
- Removed docstrings: 0
- Removed comments (not '# why:'): 0
