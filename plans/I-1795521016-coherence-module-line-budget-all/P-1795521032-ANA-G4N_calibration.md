# Plan Calibration Report: P-1795521032-ANA-G4N

- **Plan Reference:**
  [`plans/I-1795521016-coherence-module-line-budget-all/P-1795521032-ANA-G4N.md`](P-1795521032-ANA-G4N.md)
- **Execution ID:** `E-1795521216-ANA-G4N`
- **Execution Branch:** `I-1795521016-coherence-module-line-budget-all/P-1795521032-ANA-G4N/E-1795521216-ANA-G4N/_`
- **Intent Branch:** `I-1795521016-coherence-module-line-budget-all/_`
- **Evaluating Agent:** `antigravity-agent/gemini-4-neon`
- **Evaluation Timestamp:** `2026-11-24T12:17:13.000Z`
- **Evaluated Commit SHA:** `aed3e1bc7f6136132152164d15bb12fb180631c9`
- **Base SHA:** `ef30cf91eeab8302e9f1d7915cab2e9baff5c3ad`
- **Merge-Base SHA:** `ef30cf91eeab8302e9f1d7915cab2e9baff5c3ad`
- **Merged Commits:** `0`
- **Patch Size Base:** `plan`

---

## 1. Executive Calibration Summary

| Metric                                             | Predicted (`pred`) | Actual (`actual`) | Absolute Error (`abs(pred - actual)`) | Accuracy Rating | Bias Direction             |
| :------------------------------------------------- | :----------------- | :---------------- | :------------------------------------ | :-------------- | :------------------------- |
| **$P(\text{success})$**                            | `0.95`             | `1.00`            | `0.05`                                | High (≤ 0.05)   | Slight Underconfidence     |
| **Entropy ($\Delta S$)**                           | `4.60`             | `1.70`            | `2.90`                                | Moderate        | Overestimated Risk         |
| **Impact**                                         | `8.80`             | `8.80`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Cost**                                           | `2.05`             | `1.74`            | `0.31`                                | High (≤ 1.0)    | Highly Accurate            |
| **Learning Value**                                 | `2.20`             | `2.20`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Expected Value — Clean (without bugs)**          | `6.03`             | `7.65`            | `1.62`                                | High            | Conservative Underestimate |
| **Expected Value — Observed (with bugs included)** | `6.03`             | `7.65`            | `1.62`                                | High            | Conservative Underestimate |
| **Bug EV Drag**                                    | `0.00`             | `0.00`            | `0.00`                                | -               | Drag Penalty               |

---

## 2. Mathematical Derivations & Calibration Errors

- **Success Probability Error:** $|0.95 - 1.00| = 0.05$
- **Entropy Error:** $|4.60 - 1.70| = 2.90$
- **Impact Error:** $|8.80 - 8.80| = 0.00$
- **Cost Error:** $|2.05 - 1.74| = 0.31$
- **Learning Value Error:** $|2.20 - 2.20| = 0.00$
- **Expected Value Realization:**
  $$EV_{\text{pred}} = 0.95 \times 8.8 + 0.5 \times 2.2 - 0.3 \times 4.60 - 2.05 = 6.03$$
  $$EV_{\text{actual}} = EV_{\text{clean}} = 1.00 \times 8.8 + 0.5 \times 2.2 - 0.3 \times 1.70 - 1.74 = 7.65$$
  $$EV_{\text{with\_bugs}} = 1.00 \times 8.8 + 0.5 \times 2.2 - 0.3 \times 1.70 - 1.74 = 7.65$$
  $$\text{Bug EV Drag} = round(EV_{\text{clean}} - EV_{\text{with\_bugs}}, 2) = 0.00$$ $$\Delta EV = +1.62$$

---

## 3. Entropy Factor Breakdown

- **State Surface Area (SSA):** Predicted `0.6` vs Observed `5.5` (9 files modified).
- **Irreversibility (IRR):** Predicted `0.0` vs Observed `0.0` (Zero destructive or stateful changes).
- **Conflict Likelihood (CL):** Predicted `0.1` vs Observed `0.0` (Clean sequential branch merges).
- **Sandbox Escape Risk (SER):** Predicted `0.0` vs Observed `0.0` (Zero security exceptions).
- **Novelty (NOV):** Predicted `0.4` vs Observed `0.4` (Standard calibration reporting schema).

---

## 4. Calibration Assessment

Plan `P-1795521032-ANA-G4N` executed with minimal error ($p\_success\_error = 0.05$, $cost\_error = 0.31$). The
calibration step successfully completed the execution lifecycle and delivered verified post-execution analysis.

---

## 5. Touch Set Accuracy

- **Precision (declared entries the diff touched):** `100.0%`
- **Recall (changed files the touch set covered):** `77.8%`

Changed files outside the touch set:

- `scripts/module_budget_base.py`
- `tests/test_pre_commit_check.py`

Declared entries the diff did not touch:

- none
