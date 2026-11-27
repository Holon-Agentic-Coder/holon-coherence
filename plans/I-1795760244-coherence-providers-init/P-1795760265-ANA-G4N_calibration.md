# Plan Calibration Report: P-1795760265-ANA-G4N

- **Plan Reference:** [`plans/I-1795760244-coherence-providers-init/P-1795760265-ANA-G4N.md`](P-1795760265-ANA-G4N.md)
- **Execution ID:** `E-1795760411-ANA-G4N`
- **Execution Branch:** `I-1795760244-coherence-providers-init/P-1795760265-ANA-G4N/E-1795760411-ANA-G4N/_`
- **Intent Branch:** `I-1795760244-coherence-providers-init/_`
- **Evaluating Agent:** `antigravity-agent/gemini-4-neon`
- **Evaluation Timestamp:** `2026-11-27T06:26:59.000Z`
- **Evaluated Commit SHA:** `04e8ffe0d9e7f0f43c8c1a04255a18d959bb1c70`
- **Base SHA:** `180cdac1c136e8e0f9825584c0227b65ace1f126`
- **Merge-Base SHA:** `180cdac1c136e8e0f9825584c0227b65ace1f126`
- **Merged Commits:** `0`
- **Patch Size Base:** `plan`

---

## 1. Executive Calibration Summary

| Metric                                             | Predicted (`pred`) | Actual (`actual`) | Absolute Error (`abs(pred - actual)`) | Accuracy Rating | Bias Direction             |
| :------------------------------------------------- | :----------------- | :---------------- | :------------------------------------ | :-------------- | :------------------------- |
| **$P(\text{success})$**                            | `0.95`             | `1.00`            | `0.05`                                | High (≤ 0.05)   | Slight Underconfidence     |
| **Entropy ($\Delta S$)**                           | `2.40`             | `0.76`            | `1.64`                                | Moderate        | Overestimated Risk         |
| **Impact**                                         | `9.00`             | `9.00`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Cost**                                           | `0.80`             | `0.68`            | `0.12`                                | High (≤ 1.0)    | Highly Accurate            |
| **Learning Value**                                 | `1.80`             | `1.80`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Expected Value — Clean (without bugs)**          | `7.93`             | `8.99`            | `1.06`                                | High            | Conservative Underestimate |
| **Expected Value — Observed (with bugs included)** | `7.93`             | `8.99`            | `1.06`                                | High            | Conservative Underestimate |
| **Bug EV Drag**                                    | `0.00`             | `0.00`            | `0.00`                                | -               | Drag Penalty               |

---

## 2. Mathematical Derivations & Calibration Errors

- **Success Probability Error:** $|0.95 - 1.00| = 0.05$
- **Entropy Error:** $|2.40 - 0.76| = 1.64$
- **Impact Error:** $|9.00 - 9.00| = 0.00$
- **Cost Error:** $|0.80 - 0.68| = 0.12$
- **Learning Value Error:** $|1.80 - 1.80| = 0.00$
- **Expected Value Realization:**
  $$EV_{\text{pred}} = 0.95 \times 9.0 + 0.5 \times 1.8 - 0.3 \times 2.40 - 0.80 = 7.93$$
  $$EV_{\text{actual}} = EV_{\text{clean}} = 1.00 \times 9.0 + 0.5 \times 1.8 - 0.3 \times 0.76 - 0.68 = 8.99$$
  $$EV_{\text{with\_bugs}} = 1.00 \times 9.0 + 0.5 \times 1.8 - 0.3 \times 0.76 - 0.68 = 8.99$$
  $$\text{Bug EV Drag} = round(EV_{\text{clean}} - EV_{\text{with\_bugs}}, 2) = 0.00$$ $$\Delta EV = +1.06$$

---

## 3. Entropy Factor Breakdown

- **State Surface Area (SSA):** Predicted `0.6` vs Observed `2.4` (4 files modified).
- **Irreversibility (IRR):** Predicted `0.0` vs Observed `0.0` (Zero destructive or stateful changes).
- **Conflict Likelihood (CL):** Predicted `0.1` vs Observed `0.0` (Clean sequential branch merges).
- **Sandbox Escape Risk (SER):** Predicted `0.0` vs Observed `0.0` (Zero security exceptions).
- **Novelty (NOV):** Predicted `0.4` vs Observed `0.4` (Standard calibration reporting schema).

---

## 4. Calibration Assessment

Plan `P-1795760265-ANA-G4N` executed with minimal error ($p\_success\_error = 0.05$, $cost\_error = 0.12$). The
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
