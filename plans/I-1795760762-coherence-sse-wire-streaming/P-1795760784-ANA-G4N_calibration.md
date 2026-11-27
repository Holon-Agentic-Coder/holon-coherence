# Plan Calibration Report: P-1795760784-ANA-G4N

- **Plan Reference:**
  [`plans/I-1795760762-coherence-sse-wire-streaming/P-1795760784-ANA-G4N.md`](P-1795760784-ANA-G4N.md)
- **Execution ID:** `E-1795760989-ANA-G4N`
- **Execution Branch:** `I-1795760762-coherence-sse-wire-streaming/P-1795760784-ANA-G4N/E-1795760989-ANA-G4N/_`
- **Intent Branch:** `I-1795760762-coherence-sse-wire-streaming/_`
- **Evaluating Agent:** `antigravity-agent/gemini-4-neon`
- **Evaluation Timestamp:** `2026-11-27T06:49:54.000Z`
- **Evaluated Commit SHA:** `88d4dd8dac18583791bd82e73b59c579f27baa88`
- **Base SHA:** `57a319bc5af95ca4308e5b4018494283b06c210c`
- **Merge-Base SHA:** `57a319bc5af95ca4308e5b4018494283b06c210c`
- **Merged Commits:** `0`
- **Patch Size Base:** `plan`

---

## 1. Executive Calibration Summary

| Metric                                             | Predicted (`pred`) | Actual (`actual`) | Absolute Error (`abs(pred - actual)`) | Accuracy Rating | Bias Direction             |
| :------------------------------------------------- | :----------------- | :---------------- | :------------------------------------ | :-------------- | :------------------------- |
| **$P(\text{success})$**                            | `0.88`             | `1.00`            | `0.12`                                | Moderate        | Slight Underconfidence     |
| **Entropy ($\Delta S$)**                           | `7.00`             | `2.43`            | `4.57`                                | Moderate        | Overestimated Risk         |
| **Impact**                                         | `0.85`             | `0.85`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Cost**                                           | `0.22`             | `0.50`            | `0.28`                                | High (≤ 1.0)    | Highly Accurate            |
| **Learning Value**                                 | `0.40`             | `0.40`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Expected Value — Clean (without bugs)**          | `-1.37`            | `-0.18`           | `1.19`                                | High            | Conservative Underestimate |
| **Expected Value — Observed (with bugs included)** | `-1.37`            | `-0.18`           | `1.19`                                | High            | Conservative Underestimate |
| **Bug EV Drag**                                    | `0.00`             | `0.00`            | `0.00`                                | -               | Drag Penalty               |

---

## 2. Mathematical Derivations & Calibration Errors

- **Success Probability Error:** $|0.88 - 1.00| = 0.12$
- **Entropy Error:** $|7.00 - 2.43| = 4.57$
- **Impact Error:** $|0.85 - 0.85| = 0.00$
- **Cost Error:** $|0.22 - 0.50| = 0.28$
- **Learning Value Error:** $|0.40 - 0.40| = 0.00$
- **Expected Value Realization:**
  $$EV_{\text{pred}} = 0.88 \times 0.8 + 0.5 \times 0.4 - 0.3 \times 7.00 - 0.22 = -1.37$$
  $$EV_{\text{actual}} = EV_{\text{clean}} = 1.00 \times 0.8 + 0.5 \times 0.4 - 0.3 \times 2.43 - 0.50 = -0.18$$
  $$EV_{\text{with\_bugs}} = 1.00 \times 0.8 + 0.5 \times 0.4 - 0.3 \times 2.43 - 0.50 = -0.18$$
  $$\text{Bug EV Drag} = round(EV_{\text{clean}} - EV_{\text{with\_bugs}}, 2) = 0.00$$ $$\Delta EV = +1.19$$

---

## 3. Entropy Factor Breakdown

- **State Surface Area (SSA):** Predicted `0.6` vs Observed `8.0` (4 files modified).
- **Irreversibility (IRR):** Predicted `0.0` vs Observed `0.0` (Zero destructive or stateful changes).
- **Conflict Likelihood (CL):** Predicted `0.1` vs Observed `0.0` (Clean sequential branch merges).
- **Sandbox Escape Risk (SER):** Predicted `0.0` vs Observed `0.0` (Zero security exceptions).
- **Novelty (NOV):** Predicted `0.4` vs Observed `0.4` (Standard calibration reporting schema).

---

## 4. Calibration Assessment

Plan `P-1795760784-ANA-G4N` executed with minimal error ($p\_success\_error = 0.12$, $cost\_error = 0.28$). The
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

- **Full reviews:** `2`
- **Scoped reviews:** `0`
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
