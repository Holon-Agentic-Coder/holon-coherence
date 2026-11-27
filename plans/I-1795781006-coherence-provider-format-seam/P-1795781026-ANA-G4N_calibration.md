# Plan Calibration Report: P-1795781026-ANA-G4N

- **Plan Reference:**
  [`plans/I-1795781006-coherence-provider-format-seam/P-1795781026-ANA-G4N.md`](P-1795781026-ANA-G4N.md)
- **Execution ID:** `E-1795781330-ANA-G4N`
- **Execution Branch:** `I-1795781006-coherence-provider-format-seam/P-1795781026-ANA-G4N/E-1795781330-ANA-G4N/_`
- **Intent Branch:** `I-1795781006-coherence-provider-format-seam/_`
- **Evaluating Agent:** `antigravity-agent/gemini-4-neon`
- **Evaluation Timestamp:** `2026-11-27T12:35:42.000Z`
- **Evaluated Commit SHA:** `793c1f81bcdab8f4bfa24b57fb3f9136e427c6f2`
- **Base SHA:** `63a6bf3f7977e19bf70a1c4f777b3817428fc919`
- **Merge-Base SHA:** `63a6bf3f7977e19bf70a1c4f777b3817428fc919`
- **Merged Commits:** `2`
- **Patch Size Base:** `target_merge_base` (merge-base `63a6bf3f7977e19bf70a1c4f777b3817428fc919` with the target
  branch)

---

## 1. Executive Calibration Summary

| Metric                                             | Predicted (`pred`) | Actual (`actual`) | Absolute Error (`abs(pred - actual)`) | Accuracy Rating | Bias Direction             |
| :------------------------------------------------- | :----------------- | :---------------- | :------------------------------------ | :-------------- | :------------------------- |
| **$P(\text{success})$**                            | `0.89`             | `1.00`            | `0.11`                                | Moderate        | Slight Underconfidence     |
| **Entropy ($\Delta S$)**                           | `7.80`             | `2.26`            | `5.54`                                | Moderate        | Overestimated Risk         |
| **Impact**                                         | `8.50`             | `8.50`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Cost**                                           | `3.20`             | `2.72`            | `0.48`                                | High (≤ 1.0)    | Highly Accurate            |
| **Learning Value**                                 | `1.20`             | `1.20`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Expected Value — Clean (without bugs)**          | `2.63`             | `5.70`            | `3.07`                                | High            | Conservative Underestimate |
| **Expected Value — Observed (with bugs included)** | `2.63`             | `5.70`            | `3.07`                                | High            | Conservative Underestimate |
| **Bug EV Drag**                                    | `0.00`             | `0.00`            | `0.00`                                | -               | Drag Penalty               |

---

## 2. Mathematical Derivations & Calibration Errors

- **Success Probability Error:** $|0.89 - 1.00| = 0.11$
- **Entropy Error:** $|7.80 - 2.26| = 5.54$
- **Impact Error:** $|8.50 - 8.50| = 0.00$
- **Cost Error:** $|3.20 - 2.72| = 0.48$
- **Learning Value Error:** $|1.20 - 1.20| = 0.00$
- **Expected Value Realization:**
  $$EV_{\text{pred}} = 0.89 \times 8.5 + 0.5 \times 1.2 - 0.3 \times 7.80 - 3.20 = 2.63$$
  $$EV_{\text{actual}} = EV_{\text{clean}} = 1.00 \times 8.5 + 0.5 \times 1.2 - 0.3 \times 2.26 - 2.72 = 5.70$$
  $$EV_{\text{with\_bugs}} = 1.00 \times 8.5 + 0.5 \times 1.2 - 0.3 \times 2.26 - 2.72 = 5.70$$
  $$\text{Bug EV Drag} = round(EV_{\text{clean}} - EV_{\text{with\_bugs}}, 2) = 0.00$$ $$\Delta EV = +3.07$$

---

## 3. Entropy Factor Breakdown

- **State Surface Area (SSA):** Predicted `0.6` vs Observed `7.4` (11 files modified).
- **Irreversibility (IRR):** Predicted `0.0` vs Observed `0.0` (Zero destructive or stateful changes).
- **Conflict Likelihood (CL):** Predicted `0.1` vs Observed `0.0` (Clean sequential branch merges).
- **Sandbox Escape Risk (SER):** Predicted `0.0` vs Observed `0.0` (Zero security exceptions).
- **Novelty (NOV):** Predicted `0.4` vs Observed `0.4` (Standard calibration reporting schema).

---

## 4. Calibration Assessment

Plan `P-1795781026-ANA-G4N` executed with minimal error ($p\_success\_error = 0.11$, $cost\_error = 0.48$). The
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
- **Scoped reviews:** `1`
- **Approval carry-overs:** `2`
- **Pipeline runs:** `2`
- **Pipeline reruns:** `0`
- **Non-defect churn (target merge):** `2`
- **Non-defect churn (bookkeeping):** `0`
- **Non-defect churn (CI noise):** `0`

---

## 7. Self-Explaining Code Counts

Against the merge base with origin/main: added 0 docstring(s), added 0 comment(s), removed 0 docstring(s) and removed 0
comment(s) across 16 changed file(s).

- Changed files checked: 16
- Added docstrings: 0
- Added comments (not '# why:'): 0
- Removed docstrings: 0
- Removed comments (not '# why:'): 0
