# Plan Calibration Report: P-1795781448-ANA-G4N

- **Plan Reference:**
  [`plans/I-1795781426-coherence-metrics-unification/P-1795781448-ANA-G4N.md`](P-1795781448-ANA-G4N.md)
- **Execution ID:** `E-1795781614-ANA-G4N`
- **Execution Branch:** `I-1795781426-coherence-metrics-unification/P-1795781448-ANA-G4N/E-1795781614-ANA-G4N/_`
- **Intent Branch:** `I-1795781426-coherence-metrics-unification/_`
- **Evaluating Agent:** `antigravity-agent/gemini-4-neon`
- **Evaluation Timestamp:** `2026-11-27T12:32:36.000Z`
- **Evaluated Commit SHA:** `a0fe97cea1f1d8a3e3ef8f5f767013abe27ac28b`
- **Base SHA:** `63a6bf3f7977e19bf70a1c4f777b3817428fc919`
- **Merge-Base SHA:** `9eddccdc341ee24d7156ce8e5c32ba35434b65f3`
- **Merged Commits:** `1`
- **Patch Size Base:** `target_merge_base` (merge-base `9eddccdc341ee24d7156ce8e5c32ba35434b65f3` with the target
  branch)

---

## 1. Executive Calibration Summary

| Metric                                             | Predicted (`pred`) | Actual (`actual`) | Absolute Error (`abs(pred - actual)`) | Accuracy Rating | Bias Direction             |
| :------------------------------------------------- | :----------------- | :---------------- | :------------------------------------ | :-------------- | :------------------------- |
| **$P(\text{success})$**                            | `0.93`             | `1.00`            | `0.07`                                | Moderate        | Slight Underconfidence     |
| **Entropy ($\Delta S$)**                           | `7.70`             | `1.40`            | `6.30`                                | Moderate        | Overestimated Risk         |
| **Impact**                                         | `0.85`             | `0.85`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Cost**                                           | `0.25`             | `0.50`            | `0.25`                                | High (≤ 1.0)    | Highly Accurate            |
| **Learning Value**                                 | `0.35`             | `0.35`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Expected Value — Clean (without bugs)**          | `-1.59`            | `0.11`            | `1.70`                                | High            | Conservative Underestimate |
| **Expected Value — Observed (with bugs included)** | `-1.59`            | `0.11`            | `1.70`                                | High            | Conservative Underestimate |
| **Bug EV Drag**                                    | `0.00`             | `0.00`            | `0.00`                                | -               | Drag Penalty               |

---

## 2. Mathematical Derivations & Calibration Errors

- **Success Probability Error:** $|0.93 - 1.00| = 0.07$
- **Entropy Error:** $|7.70 - 1.40| = 6.30$
- **Impact Error:** $|0.85 - 0.85| = 0.00$
- **Cost Error:** $|0.25 - 0.50| = 0.25$
- **Learning Value Error:** $|0.35 - 0.35| = 0.00$
- **Expected Value Realization:**
  $$EV_{\text{pred}} = 0.93 \times 0.8 + 0.5 \times 0.3 - 0.3 \times 7.70 - 0.25 = -1.59$$
  $$EV_{\text{actual}} = EV_{\text{clean}} = 1.00 \times 0.8 + 0.5 \times 0.3 - 0.3 \times 1.40 - 0.50 = 0.11$$
  $$EV_{\text{with\_bugs}} = 1.00 \times 0.8 + 0.5 \times 0.3 - 0.3 \times 1.40 - 0.50 = 0.11$$
  $$\text{Bug EV Drag} = round(EV_{\text{clean}} - EV_{\text{with\_bugs}}, 2) = 0.00$$ $$\Delta EV = +1.70$$

---

## 3. Entropy Factor Breakdown

- **State Surface Area (SSA):** Predicted `0.6` vs Observed `4.5` (5 files modified).
- **Irreversibility (IRR):** Predicted `0.0` vs Observed `0.0` (Zero destructive or stateful changes).
- **Conflict Likelihood (CL):** Predicted `0.1` vs Observed `0.0` (Clean sequential branch merges).
- **Sandbox Escape Risk (SER):** Predicted `0.0` vs Observed `0.0` (Zero security exceptions).
- **Novelty (NOV):** Predicted `0.4` vs Observed `0.4` (Standard calibration reporting schema).

---

## 4. Calibration Assessment

Plan `P-1795781448-ANA-G4N` executed with minimal error ($p\_success\_error = 0.07$, $cost\_error = 0.25$). The
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
- **Approval carry-overs:** `2`
- **Pipeline runs:** `1`
- **Pipeline reruns:** `0`
- **Non-defect churn (target merge):** `2`
- **Non-defect churn (bookkeeping):** `0`
- **Non-defect churn (CI noise):** `0`

---

## 7. Self-Explaining Code Counts

Against the merge base with origin/main: added 0 docstring(s), added 0 comment(s), removed 0 docstring(s) and removed 0
comment(s) across 10 changed file(s).

- Changed files checked: 10
- Added docstrings: 0
- Added comments (not '# why:'): 0
- Removed docstrings: 0
- Removed comments (not '# why:'): 0
