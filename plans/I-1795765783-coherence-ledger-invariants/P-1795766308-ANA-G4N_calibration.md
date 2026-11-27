# Plan Calibration Report: P-1795766308-ANA-G4N

- **Plan Reference:**
  [`plans/I-1795765783-coherence-ledger-invariants/P-1795766308-ANA-G4N.md`](P-1795766308-ANA-G4N.md)
- **Execution ID:** `E-1795766477-ANA-G4N`
- **Execution Branch:** `I-1795765783-coherence-ledger-invariants/P-1795766308-ANA-G4N/E-1795766477-ANA-G4N/_`
- **Intent Branch:** `I-1795765783-coherence-ledger-invariants/_`
- **Evaluating Agent:** `antigravity-agent/gemini-4-neon`
- **Evaluation Timestamp:** `2026-11-27T08:32:48.000Z`
- **Evaluated Commit SHA:** `22f4aa753b9617b93c3e6f7b83e0e40fbac42310`
- **Base SHA:** `980da41a15659380a2ae1379d54462889a0ca6f5`
- **Merge-Base SHA:** `980da41a15659380a2ae1379d54462889a0ca6f5`
- **Merged Commits:** `2`
- **Patch Size Base:** `target_merge_base` (merge-base `980da41a15659380a2ae1379d54462889a0ca6f5` with the target
  branch)

---

## 1. Executive Calibration Summary

| Metric                                             | Predicted (`pred`) | Actual (`actual`) | Absolute Error (`abs(pred - actual)`) | Accuracy Rating | Bias Direction             |
| :------------------------------------------------- | :----------------- | :---------------- | :------------------------------------ | :-------------- | :------------------------- |
| **$P(\text{success})$**                            | `0.81`             | `1.00`            | `0.19`                                | Moderate        | Slight Underconfidence     |
| **Entropy ($\Delta S$)**                           | `6.00`             | `1.35`            | `4.65`                                | Moderate        | Overestimated Risk         |
| **Impact**                                         | `10.00`            | `10.00`           | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Cost**                                           | `2.70`             | `2.29`            | `0.41`                                | High (≤ 1.0)    | Highly Accurate            |
| **Learning Value**                                 | `1.70`             | `1.70`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Expected Value — Clean (without bugs)**          | `4.49`             | `8.15`            | `3.66`                                | High            | Conservative Underestimate |
| **Expected Value — Observed (with bugs included)** | `4.49`             | `8.15`            | `3.66`                                | High            | Conservative Underestimate |
| **Bug EV Drag**                                    | `0.00`             | `0.00`            | `0.00`                                | -               | Drag Penalty               |

---

## 2. Mathematical Derivations & Calibration Errors

- **Success Probability Error:** $|0.81 - 1.00| = 0.19$
- **Entropy Error:** $|6.00 - 1.35| = 4.65$
- **Impact Error:** $|10.00 - 10.00| = 0.00$
- **Cost Error:** $|2.70 - 2.29| = 0.41$
- **Learning Value Error:** $|1.70 - 1.70| = 0.00$
- **Expected Value Realization:**
  $$EV_{\text{pred}} = 0.81 \times 10.0 + 0.5 \times 1.7 - 0.3 \times 6.00 - 2.70 = 4.49$$
  $$EV_{\text{actual}} = EV_{\text{clean}} = 1.00 \times 10.0 + 0.5 \times 1.7 - 0.3 \times 1.35 - 2.29 = 8.15$$
  $$EV_{\text{with\_bugs}} = 1.00 \times 10.0 + 0.5 \times 1.7 - 0.3 \times 1.35 - 2.29 = 8.15$$
  $$\text{Bug EV Drag} = round(EV_{\text{clean}} - EV_{\text{with\_bugs}}, 2) = 0.00$$ $$\Delta EV = +3.66$$

---

## 3. Entropy Factor Breakdown

- **State Surface Area (SSA):** Predicted `0.6` vs Observed `4.4` (6 files modified).
- **Irreversibility (IRR):** Predicted `0.0` vs Observed `0.0` (Zero destructive or stateful changes).
- **Conflict Likelihood (CL):** Predicted `0.1` vs Observed `0.0` (Clean sequential branch merges).
- **Sandbox Escape Risk (SER):** Predicted `0.0` vs Observed `0.0` (Zero security exceptions).
- **Novelty (NOV):** Predicted `0.4` vs Observed `0.4` (Standard calibration reporting schema).

---

## 4. Calibration Assessment

Plan `P-1795766308-ANA-G4N` executed with minimal error ($p\_success\_error = 0.19$, $cost\_error = 0.41$). The
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
- **Scoped reviews:** `1`
- **Approval carry-overs:** `2`
- **Pipeline runs:** `3`
- **Pipeline reruns:** `0`
- **Non-defect churn (target merge):** `2`
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
