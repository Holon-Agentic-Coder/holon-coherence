# Plan Calibration Report: P-1795518095-ANA-G4N

- **Plan Reference:**
  [`plans/I-1795518078-coherence-addon-tests-self-doc/P-1795518095-ANA-G4N.md`](P-1795518095-ANA-G4N.md)
- **Execution ID:** `E-1795518227-ANA-G4N`
- **Execution Branch:** `I-1795518078-coherence-addon-tests-self-doc/P-1795518095-ANA-G4N/E-1795518227-ANA-G4N/_`
- **Intent Branch:** `I-1795518078-coherence-addon-tests-self-doc/_`
- **Evaluating Agent:** `antigravity-agent/gemini-4-neon`
- **Evaluation Timestamp:** `2026-11-24T11:15:00.000Z`
- **Evaluated Commit SHA:** `13d77de0b84ee917242b7f8e50bdbee9c32efeb9`
- **Base SHA:** `dd8e7318e9fdca7f34fc8914a684388fbe895921`
- **Merge-Base SHA:** `dd8e7318e9fdca7f34fc8914a684388fbe895921`
- **Merged Commits:** `1`
- **Patch Size Base:** `target_merge_base` (merge-base `dd8e7318e9fdca7f34fc8914a684388fbe895921` with the target
  branch)

---

## 1. Executive Calibration Summary

| Metric                                             | Predicted (`pred`) | Actual (`actual`) | Absolute Error (`abs(pred - actual)`) | Accuracy Rating | Bias Direction             |
| :------------------------------------------------- | :----------------- | :---------------- | :------------------------------------ | :-------------- | :------------------------- |
| **$P(\text{success})$**                            | `0.99`             | `1.00`            | `0.01`                                | High (≤ 0.05)   | Slight Underconfidence     |
| **Entropy ($\Delta S$)**                           | `1.70`             | `0.68`            | `1.02`                                | Moderate        | Overestimated Risk         |
| **Impact**                                         | `8.70`             | `8.70`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Cost**                                           | `0.55`             | `0.50`            | `0.05`                                | High (≤ 1.0)    | Highly Accurate            |
| **Learning Value**                                 | `1.60`             | `1.60`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Expected Value — Clean (without bugs)**          | `8.35`             | `8.80`            | `0.45`                                | High            | Conservative Underestimate |
| **Expected Value — Observed (with bugs included)** | `8.35`             | `8.80`            | `0.45`                                | High            | Conservative Underestimate |
| **Bug EV Drag**                                    | `0.00`             | `0.00`            | `0.00`                                | -               | Drag Penalty               |

---

## 2. Mathematical Derivations & Calibration Errors

- **Success Probability Error:** $|0.99 - 1.00| = 0.01$
- **Entropy Error:** $|1.70 - 0.68| = 1.02$
- **Impact Error:** $|8.70 - 8.70| = 0.00$
- **Cost Error:** $|0.55 - 0.50| = 0.05$
- **Learning Value Error:** $|1.60 - 1.60| = 0.00$
- **Expected Value Realization:**
  $$EV_{\text{pred}} = 0.99 \times 8.7 + 0.5 \times 1.6 - 0.3 \times 1.70 - 0.55 = 8.35$$
  $$EV_{\text{actual}} = EV_{\text{clean}} = 1.00 \times 8.7 + 0.5 \times 1.6 - 0.3 \times 0.68 - 0.50 = 8.80$$
  $$EV_{\text{with\_bugs}} = 1.00 \times 8.7 + 0.5 \times 1.6 - 0.3 \times 0.68 - 0.50 = 8.80$$
  $$\text{Bug EV Drag} = round(EV_{\text{clean}} - EV_{\text{with\_bugs}}, 2) = 0.00$$ $$\Delta EV = +0.45$$

---

## 3. Entropy Factor Breakdown

- **State Surface Area (SSA):** Predicted `0.6` vs Observed `2.1` (3 files modified).
- **Irreversibility (IRR):** Predicted `0.0` vs Observed `0.0` (Zero destructive or stateful changes).
- **Conflict Likelihood (CL):** Predicted `0.1` vs Observed `0.0` (Clean sequential branch merges).
- **Sandbox Escape Risk (SER):** Predicted `0.0` vs Observed `0.0` (Zero security exceptions).
- **Novelty (NOV):** Predicted `0.4` vs Observed `0.4` (Standard calibration reporting schema).

---

## 4. Calibration Assessment

Plan `P-1795518095-ANA-G4N` executed with minimal error ($p\_success\_error = 0.01$, $cost\_error = 0.05$). The
calibration step successfully completed the execution lifecycle and delivered verified post-execution analysis.

---

## 5. Touch Set Accuracy

- **Precision (declared entries the diff touched):** `100.0%`
- **Recall (changed files the touch set covered):** `100.0%`

Changed files outside the touch set:

- none

Declared entries the diff did not touch:

- none
