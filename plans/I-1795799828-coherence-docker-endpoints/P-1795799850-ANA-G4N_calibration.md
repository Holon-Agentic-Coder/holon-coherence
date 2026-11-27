# Plan Calibration Report: P-1795799850-ANA-G4N

- **Plan Reference:** [`plans/I-1795799828-coherence-docker-endpoints/P-1795799850-ANA-G4N.md`](P-1795799850-ANA-G4N.md)
- **Execution ID:** `E-1795800022-ANA-G4N`
- **Execution Branch:** `I-1795799828-coherence-docker-endpoints/P-1795799850-ANA-G4N/E-1795800022-ANA-G4N/_`
- **Intent Branch:** `I-1795799828-coherence-docker-endpoints/_`
- **Evaluating Agent:** `antigravity-agent/gemini-4-neon`
- **Evaluation Timestamp:** `2026-11-27T17:31:13.000Z`
- **Evaluated Commit SHA:** `5b42a44f18c24e36cfaeb5f1434c1b006c3ce461`
- **Base SHA:** `13e9a094c657b3d410ed3fcefeb796789f7543a7`
- **Merge-Base SHA:** `13e9a094c657b3d410ed3fcefeb796789f7543a7`
- **Merged Commits:** `0`
- **Patch Size Base:** `plan`

---

## 1. Executive Calibration Summary

| Metric                                             | Predicted (`pred`) | Actual (`actual`) | Absolute Error (`abs(pred - actual)`) | Accuracy Rating | Bias Direction             |
| :------------------------------------------------- | :----------------- | :---------------- | :------------------------------------ | :-------------- | :------------------------- |
| **$P(\text{success})$**                            | `0.95`             | `1.00`            | `0.05`                                | High (≤ 0.05)   | Slight Underconfidence     |
| **Entropy ($\Delta S$)**                           | `5.00`             | `0.57`            | `4.43`                                | Moderate        | Overestimated Risk         |
| **Impact**                                         | `0.80`             | `0.80`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Cost**                                           | `0.18`             | `0.50`            | `0.32`                                | High (≤ 1.0)    | Highly Accurate            |
| **Learning Value**                                 | `0.30`             | `0.30`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Expected Value — Clean (without bugs)**          | `-0.77`            | `0.28`            | `1.05`                                | High            | Conservative Underestimate |
| **Expected Value — Observed (with bugs included)** | `-0.77`            | `0.28`            | `1.05`                                | High            | Conservative Underestimate |
| **Bug EV Drag**                                    | `0.00`             | `0.00`            | `0.00`                                | -               | Drag Penalty               |

---

## 2. Mathematical Derivations & Calibration Errors

- **Success Probability Error:** $|0.95 - 1.00| = 0.05$
- **Entropy Error:** $|5.00 - 0.57| = 4.43$
- **Impact Error:** $|0.80 - 0.80| = 0.00$
- **Cost Error:** $|0.18 - 0.50| = 0.32$
- **Learning Value Error:** $|0.30 - 0.30| = 0.00$
- **Expected Value Realization:**
  $$EV_{\text{pred}} = 0.95 \times 0.8 + 0.5 \times 0.3 - 0.3 \times 5.00 - 0.18 = -0.77$$
  $$EV_{\text{actual}} = EV_{\text{clean}} = 1.00 \times 0.8 + 0.5 \times 0.3 - 0.3 \times 0.57 - 0.50 = 0.28$$
  $$EV_{\text{with\_bugs}} = 1.00 \times 0.8 + 0.5 \times 0.3 - 0.3 \times 0.57 - 0.50 = 0.28$$
  $$\text{Bug EV Drag} = round(EV_{\text{clean}} - EV_{\text{with\_bugs}}, 2) = 0.00$$ $$\Delta EV = +1.05$$

---

## 3. Entropy Factor Breakdown

- **State Surface Area (SSA):** Predicted `0.6` vs Observed `1.8` (4 files modified).
- **Irreversibility (IRR):** Predicted `0.0` vs Observed `0.0` (Zero destructive or stateful changes).
- **Conflict Likelihood (CL):** Predicted `0.1` vs Observed `0.0` (Clean sequential branch merges).
- **Sandbox Escape Risk (SER):** Predicted `0.0` vs Observed `0.0` (Zero security exceptions).
- **Novelty (NOV):** Predicted `0.4` vs Observed `0.4` (Standard calibration reporting schema).

---

## 4. Calibration Assessment

Plan `P-1795799850-ANA-G4N` executed with minimal error ($p\_success\_error = 0.05$, $cost\_error = 0.32$). The
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
comment(s) across 9 changed file(s).

- Changed files checked: 9
- Added docstrings: 0
- Added comments (not '# why:'): 0
- Removed docstrings: 0
- Removed comments (not '# why:'): 0
