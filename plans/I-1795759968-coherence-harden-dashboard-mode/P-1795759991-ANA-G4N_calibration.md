# Plan Calibration Report: P-1795759991-ANA-G4N

- **Plan Reference:**
  [`plans/I-1795759968-coherence-harden-dashboard-mode/P-1795759991-ANA-G4N.md`](P-1795759991-ANA-G4N.md)
- **Execution ID:** `E-1795760168-ANA-G4N`
- **Execution Branch:** `I-1795759968-coherence-harden-dashboard-mode/P-1795759991-ANA-G4N/E-1795760168-ANA-G4N/_`
- **Intent Branch:** `I-1795759968-coherence-harden-dashboard-mode/_`
- **Evaluating Agent:** `antigravity-agent/gemini-4-neon`
- **Evaluation Timestamp:** `2026-11-27T06:34:29.000Z`
- **Evaluated Commit SHA:** `2219fd3534c935d742ea32a0c8f21ee43c3e38b2`
- **Base SHA:** `7526b787f206c0cb853b74b5adcfd7a27ad02d99`
- **Merge-Base SHA:** `7526b787f206c0cb853b74b5adcfd7a27ad02d99`
- **Merged Commits:** `0`
- **Patch Size Base:** `plan`

---

## 1. Executive Calibration Summary

| Metric                                             | Predicted (`pred`) | Actual (`actual`) | Absolute Error (`abs(pred - actual)`) | Accuracy Rating | Bias Direction             |
| :------------------------------------------------- | :----------------- | :---------------- | :------------------------------------ | :-------------- | :------------------------- |
| **$P(\text{success})$**                            | `0.92`             | `1.00`            | `0.08`                                | Moderate        | Slight Underconfidence     |
| **Entropy ($\Delta S$)**                           | `4.00`             | `1.08`            | `2.92`                                | Moderate        | Overestimated Risk         |
| **Impact**                                         | `0.90`             | `0.90`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Cost**                                           | `0.22`             | `0.50`            | `0.28`                                | High (≤ 1.0)    | Highly Accurate            |
| **Learning Value**                                 | `0.35`             | `0.35`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Expected Value — Clean (without bugs)**          | `-0.42`            | `0.25`            | `0.67`                                | High            | Conservative Underestimate |
| **Expected Value — Observed (with bugs included)** | `-0.42`            | `0.25`            | `0.67`                                | High            | Conservative Underestimate |
| **Bug EV Drag**                                    | `0.00`             | `0.00`            | `0.00`                                | -               | Drag Penalty               |

---

## 2. Mathematical Derivations & Calibration Errors

- **Success Probability Error:** $|0.92 - 1.00| = 0.08$
- **Entropy Error:** $|4.00 - 1.08| = 2.92$
- **Impact Error:** $|0.90 - 0.90| = 0.00$
- **Cost Error:** $|0.22 - 0.50| = 0.28$
- **Learning Value Error:** $|0.35 - 0.35| = 0.00$
- **Expected Value Realization:**
  $$EV_{\text{pred}} = 0.92 \times 0.9 + 0.5 \times 0.3 - 0.3 \times 4.00 - 0.22 = -0.42$$
  $$EV_{\text{actual}} = EV_{\text{clean}} = 1.00 \times 0.9 + 0.5 \times 0.3 - 0.3 \times 1.08 - 0.50 = 0.25$$
  $$EV_{\text{with\_bugs}} = 1.00 \times 0.9 + 0.5 \times 0.3 - 0.3 \times 1.08 - 0.50 = 0.25$$
  $$\text{Bug EV Drag} = round(EV_{\text{clean}} - EV_{\text{with\_bugs}}, 2) = 0.00$$ $$\Delta EV = +0.67$$

---

## 3. Entropy Factor Breakdown

- **State Surface Area (SSA):** Predicted `0.6` vs Observed `3.5` (4 files modified).
- **Irreversibility (IRR):** Predicted `0.0` vs Observed `0.0` (Zero destructive or stateful changes).
- **Conflict Likelihood (CL):** Predicted `0.1` vs Observed `0.0` (Clean sequential branch merges).
- **Sandbox Escape Risk (SER):** Predicted `0.0` vs Observed `0.0` (Zero security exceptions).
- **Novelty (NOV):** Predicted `0.4` vs Observed `0.4` (Standard calibration reporting schema).

---

## 4. Calibration Assessment

Plan `P-1795759991-ANA-G4N` executed with minimal error ($p\_success\_error = 0.08$, $cost\_error = 0.28$). The
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
- **Approval carry-overs:** `0`
- **Pipeline runs:** `2`
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
