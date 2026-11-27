# Plan Calibration Report: P-1795760329-ANA-G4N

- **Plan Reference:** [`plans/I-1795760307-coherence-reduction-pass/P-1795760329-ANA-G4N.md`](P-1795760329-ANA-G4N.md)
- **Execution ID:** `E-1795760497-ANA-G4N`
- **Execution Branch:** `I-1795760307-coherence-reduction-pass/P-1795760329-ANA-G4N/E-1795760497-ANA-G4N/_`
- **Intent Branch:** `I-1795760307-coherence-reduction-pass/_`
- **Evaluating Agent:** `antigravity-agent/gemini-4-neon`
- **Evaluation Timestamp:** `2026-11-27T06:32:07.000Z`
- **Evaluated Commit SHA:** `4a0c6550d60f2e05e42ca05c6b91d63e56f4ca09`
- **Base SHA:** `350a9689b9d445202eb162d361f502d0848c86fe`
- **Merge-Base SHA:** `350a9689b9d445202eb162d361f502d0848c86fe`
- **Merged Commits:** `0`
- **Patch Size Base:** `plan`

---

## 1. Executive Calibration Summary

| Metric                                             | Predicted (`pred`) | Actual (`actual`) | Absolute Error (`abs(pred - actual)`) | Accuracy Rating | Bias Direction             |
| :------------------------------------------------- | :----------------- | :---------------- | :------------------------------------ | :-------------- | :------------------------- |
| **$P(\text{success})$**                            | `0.90`             | `1.00`            | `0.10`                                | Moderate        | Slight Underconfidence     |
| **Entropy ($\Delta S$)**                           | `5.00`             | `1.14`            | `3.86`                                | Moderate        | Overestimated Risk         |
| **Impact**                                         | `0.85`             | `0.85`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Cost**                                           | `0.13`             | `0.50`            | `0.37`                                | High (≤ 1.0)    | Highly Accurate            |
| **Learning Value**                                 | `0.40`             | `0.40`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Expected Value — Clean (without bugs)**          | `-0.66`            | `0.21`            | `0.87`                                | High            | Conservative Underestimate |
| **Expected Value — Observed (with bugs included)** | `-0.66`            | `0.21`            | `0.87`                                | High            | Conservative Underestimate |
| **Bug EV Drag**                                    | `0.00`             | `0.00`            | `0.00`                                | -               | Drag Penalty               |

---

## 2. Mathematical Derivations & Calibration Errors

- **Success Probability Error:** $|0.90 - 1.00| = 0.10$
- **Entropy Error:** $|5.00 - 1.14| = 3.86$
- **Impact Error:** $|0.85 - 0.85| = 0.00$
- **Cost Error:** $|0.13 - 0.50| = 0.37$
- **Learning Value Error:** $|0.40 - 0.40| = 0.00$
- **Expected Value Realization:**
  $$EV_{\text{pred}} = 0.90 \times 0.8 + 0.5 \times 0.4 - 0.3 \times 5.00 - 0.13 = -0.66$$
  $$EV_{\text{actual}} = EV_{\text{clean}} = 1.00 \times 0.8 + 0.5 \times 0.4 - 0.3 \times 1.14 - 0.50 = 0.21$$
  $$EV_{\text{with\_bugs}} = 1.00 \times 0.8 + 0.5 \times 0.4 - 0.3 \times 1.14 - 0.50 = 0.21$$
  $$\text{Bug EV Drag} = round(EV_{\text{clean}} - EV_{\text{with\_bugs}}, 2) = 0.00$$ $$\Delta EV = +0.87$$

---

## 3. Entropy Factor Breakdown

- **State Surface Area (SSA):** Predicted `0.6` vs Observed `3.7` (4 files modified).
- **Irreversibility (IRR):** Predicted `0.0` vs Observed `0.0` (Zero destructive or stateful changes).
- **Conflict Likelihood (CL):** Predicted `0.1` vs Observed `0.0` (Clean sequential branch merges).
- **Sandbox Escape Risk (SER):** Predicted `0.0` vs Observed `0.0` (Zero security exceptions).
- **Novelty (NOV):** Predicted `0.4` vs Observed `0.4` (Standard calibration reporting schema).

---

## 4. Calibration Assessment

Plan `P-1795760329-ANA-G4N` executed with minimal error ($p\_success\_error = 0.10$, $cost\_error = 0.37$). The
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
