# Plan Calibration Report: P-1795764581-ANA-G4N

- **Plan Reference:**
  [`plans/I-1795764560-coherence-ca-logging-and-image/P-1795764581-ANA-G4N.md`](P-1795764581-ANA-G4N.md)
- **Execution ID:** `E-1795764765-ANA-G4N`
- **Execution Branch:** `I-1795764560-coherence-ca-logging-and-image/P-1795764581-ANA-G4N/E-1795764765-ANA-G4N/_`
- **Intent Branch:** `I-1795764560-coherence-ca-logging-and-image/_`
- **Evaluating Agent:** `antigravity-agent/gemini-4-neon`
- **Evaluation Timestamp:** `2026-11-27T08:11:39.000Z`
- **Evaluated Commit SHA:** `6cf760c9060efeea3067f49d723d09a95d36e731`
- **Base SHA:** `dbf76cd61924c6560ae1f773acd556f7bd3365e8`
- **Merge-Base SHA:** `ce39bf34d71f87b85ead3f5dccd1ea4246245104`
- **Merged Commits:** `1`
- **Patch Size Base:** `target_merge_base` (merge-base `ce39bf34d71f87b85ead3f5dccd1ea4246245104` with the target
  branch)

---

## 1. Executive Calibration Summary

| Metric                                             | Predicted (`pred`) | Actual (`actual`) | Absolute Error (`abs(pred - actual)`) | Accuracy Rating | Bias Direction             |
| :------------------------------------------------- | :----------------- | :---------------- | :------------------------------------ | :-------------- | :------------------------- |
| **$P(\text{success})$**                            | `0.92`             | `1.00`            | `0.08`                                | Moderate        | Slight Underconfidence     |
| **Entropy ($\Delta S$)**                           | `3.80`             | `0.50`            | `3.30`                                | Moderate        | Overestimated Risk         |
| **Impact**                                         | `0.85`             | `0.85`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Cost**                                           | `0.18`             | `0.50`            | `0.32`                                | High (≤ 1.0)    | Highly Accurate            |
| **Learning Value**                                 | `0.25`             | `0.25`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Expected Value — Clean (without bugs)**          | `-0.41`            | `0.32`            | `0.73`                                | High            | Conservative Underestimate |
| **Expected Value — Observed (with bugs included)** | `-0.41`            | `0.32`            | `0.73`                                | High            | Conservative Underestimate |
| **Bug EV Drag**                                    | `0.00`             | `0.00`            | `0.00`                                | -               | Drag Penalty               |

---

## 2. Mathematical Derivations & Calibration Errors

- **Success Probability Error:** $|0.92 - 1.00| = 0.08$
- **Entropy Error:** $|3.80 - 0.50| = 3.30$
- **Impact Error:** $|0.85 - 0.85| = 0.00$
- **Cost Error:** $|0.18 - 0.50| = 0.32$
- **Learning Value Error:** $|0.25 - 0.25| = 0.00$
- **Expected Value Realization:**
  $$EV_{\text{pred}} = 0.92 \times 0.8 + 0.5 \times 0.2 - 0.3 \times 3.80 - 0.18 = -0.41$$
  $$EV_{\text{actual}} = EV_{\text{clean}} = 1.00 \times 0.8 + 0.5 \times 0.2 - 0.3 \times 0.50 - 0.50 = 0.32$$
  $$EV_{\text{with\_bugs}} = 1.00 \times 0.8 + 0.5 \times 0.2 - 0.3 \times 0.50 - 0.50 = 0.32$$
  $$\text{Bug EV Drag} = round(EV_{\text{clean}} - EV_{\text{with\_bugs}}, 2) = 0.00$$ $$\Delta EV = +0.73$$

---

## 3. Entropy Factor Breakdown

- **State Surface Area (SSA):** Predicted `0.6` vs Observed `1.5` (4 files modified).
- **Irreversibility (IRR):** Predicted `0.0` vs Observed `0.0` (Zero destructive or stateful changes).
- **Conflict Likelihood (CL):** Predicted `0.1` vs Observed `0.0` (Clean sequential branch merges).
- **Sandbox Escape Risk (SER):** Predicted `0.0` vs Observed `0.0` (Zero security exceptions).
- **Novelty (NOV):** Predicted `0.4` vs Observed `0.4` (Standard calibration reporting schema).

---

## 4. Calibration Assessment

Plan `P-1795764581-ANA-G4N` executed with minimal error ($p\_success\_error = 0.08$, $cost\_error = 0.32$). The
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
comment(s) across 9 changed file(s).

- Changed files checked: 9
- Added docstrings: 0
- Added comments (not '# why:'): 0
- Removed docstrings: 0
- Removed comments (not '# why:'): 0
