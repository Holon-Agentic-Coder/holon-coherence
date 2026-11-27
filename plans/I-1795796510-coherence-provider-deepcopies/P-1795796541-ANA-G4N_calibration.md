# Plan Calibration Report: P-1795796541-ANA-G4N

- **Plan Reference:**
  [`plans/I-1795796510-coherence-provider-deepcopies/P-1795796541-ANA-G4N.md`](P-1795796541-ANA-G4N.md)
- **Execution ID:** `E-1795796781-ANA-G4N`
- **Execution Branch:** `I-1795796510-coherence-provider-deepcopies/P-1795796541-ANA-G4N/E-1795796781-ANA-G4N/_`
- **Intent Branch:** `I-1795796510-coherence-provider-deepcopies/_`
- **Evaluating Agent:** `antigravity-agent/gemini-4-neon`
- **Evaluation Timestamp:** `2026-11-27T16:39:47.000Z`
- **Evaluated Commit SHA:** `2267e687c16f9b764385a23fc542ff130e0b7339`
- **Base SHA:** `fa73d7a7a9c6a91abd1f47343302d8b40898ca02`
- **Merge-Base SHA:** `fa73d7a7a9c6a91abd1f47343302d8b40898ca02`
- **Merged Commits:** `0`
- **Patch Size Base:** `plan`

---

## 1. Executive Calibration Summary

| Metric                                             | Predicted (`pred`) | Actual (`actual`) | Absolute Error (`abs(pred - actual)`) | Accuracy Rating | Bias Direction             |
| :------------------------------------------------- | :----------------- | :---------------- | :------------------------------------ | :-------------- | :------------------------- |
| **$P(\text{success})$**                            | `0.89`             | `1.00`            | `0.11`                                | Moderate        | Slight Underconfidence     |
| **Entropy ($\Delta S$)**                           | `6.80`             | `0.92`            | `5.88`                                | Moderate        | Overestimated Risk         |
| **Impact**                                         | `8.30`             | `8.30`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Cost**                                           | `2.70`             | `2.29`            | `0.41`                                | High (≤ 1.0)    | Highly Accurate            |
| **Learning Value**                                 | `1.00`             | `1.00`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Expected Value — Clean (without bugs)**          | `3.15`             | `6.23`            | `3.08`                                | High            | Conservative Underestimate |
| **Expected Value — Observed (with bugs included)** | `3.15`             | `6.23`            | `3.08`                                | High            | Conservative Underestimate |
| **Bug EV Drag**                                    | `0.00`             | `0.00`            | `0.00`                                | -               | Drag Penalty               |

---

## 2. Mathematical Derivations & Calibration Errors

- **Success Probability Error:** $|0.89 - 1.00| = 0.11$
- **Entropy Error:** $|6.80 - 0.92| = 5.88$
- **Impact Error:** $|8.30 - 8.30| = 0.00$
- **Cost Error:** $|2.70 - 2.29| = 0.41$
- **Learning Value Error:** $|1.00 - 1.00| = 0.00$
- **Expected Value Realization:**
  $$EV_{\text{pred}} = 0.89 \times 8.3 + 0.5 \times 1.0 - 0.3 \times 6.80 - 2.70 = 3.15$$
  $$EV_{\text{actual}} = EV_{\text{clean}} = 1.00 \times 8.3 + 0.5 \times 1.0 - 0.3 \times 0.92 - 2.29 = 6.23$$
  $$EV_{\text{with\_bugs}} = 1.00 \times 8.3 + 0.5 \times 1.0 - 0.3 \times 0.92 - 2.29 = 6.23$$
  $$\text{Bug EV Drag} = round(EV_{\text{clean}} - EV_{\text{with\_bugs}}, 2) = 0.00$$ $$\Delta EV = +3.08$$

---

## 3. Entropy Factor Breakdown

- **State Surface Area (SSA):** Predicted `0.6` vs Observed `2.9` (6 files modified).
- **Irreversibility (IRR):** Predicted `0.0` vs Observed `0.0` (Zero destructive or stateful changes).
- **Conflict Likelihood (CL):** Predicted `0.1` vs Observed `0.0` (Clean sequential branch merges).
- **Sandbox Escape Risk (SER):** Predicted `0.0` vs Observed `0.0` (Zero security exceptions).
- **Novelty (NOV):** Predicted `0.4` vs Observed `0.4` (Standard calibration reporting schema).

---

## 4. Calibration Assessment

Plan `P-1795796541-ANA-G4N` executed with minimal error ($p\_success\_error = 0.11$, $cost\_error = 0.41$). The
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
comment(s) across 11 changed file(s).

- Changed files checked: 11
- Added docstrings: 0
- Added comments (not '# why:'): 0
- Removed docstrings: 0
- Removed comments (not '# why:'): 0
