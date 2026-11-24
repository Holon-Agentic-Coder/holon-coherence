# Plan Calibration Report: P-1795548994-ANA-G4N

- **Plan Reference:** [`plans/I-1795548977-coherence-final-self-doc/P-1795548994-ANA-G4N.md`](P-1795548994-ANA-G4N.md)
- **Execution ID:** `E-1795549182-ANA-G4N`
- **Execution Branch:** `I-1795548977-coherence-final-self-doc/P-1795548994-ANA-G4N/E-1795549182-ANA-G4N/_`
- **Intent Branch:** `I-1795548977-coherence-final-self-doc/_`
- **Evaluating Agent:** `antigravity-agent/gemini-4-neon`
- **Evaluation Timestamp:** `2026-11-24T19:59:47.000Z`
- **Evaluated Commit SHA:** `2ecebadf140de5d56732110817f70f0524913e00`
- **Base SHA:** `a1a337e531edad03e515021c8d9ee663d3f18e9f`
- **Merge-Base SHA:** `a1a337e531edad03e515021c8d9ee663d3f18e9f`
- **Merged Commits:** `0`
- **Patch Size Base:** `plan`

---

## 1. Executive Calibration Summary

| Metric                                             | Predicted (`pred`) | Actual (`actual`) | Absolute Error (`abs(pred - actual)`) | Accuracy Rating | Bias Direction             |
| :------------------------------------------------- | :----------------- | :---------------- | :------------------------------------ | :-------------- | :------------------------- |
| **$P(\text{success})$**                            | `0.98`             | `1.00`            | `0.02`                                | High (≤ 0.05)   | Slight Underconfidence     |
| **Entropy ($\Delta S$)**                           | `2.10`             | `1.25`            | `0.85`                                | High (≤ 1.0)    | Overestimated Risk         |
| **Impact**                                         | `9.00`             | `9.00`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Cost**                                           | `0.80`             | `0.68`            | `0.12`                                | High (≤ 1.0)    | Highly Accurate            |
| **Learning Value**                                 | `1.80`             | `1.80`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Expected Value — Clean (without bugs)**          | `8.29`             | `8.84`            | `0.55`                                | High            | Conservative Underestimate |
| **Expected Value — Observed (with bugs included)** | `8.29`             | `8.84`            | `0.55`                                | High            | Conservative Underestimate |
| **Bug EV Drag**                                    | `0.00`             | `0.00`            | `0.00`                                | -               | Drag Penalty               |

---

## 2. Mathematical Derivations & Calibration Errors

- **Success Probability Error:** $|0.98 - 1.00| = 0.02$
- **Entropy Error:** $|2.10 - 1.25| = 0.85$
- **Impact Error:** $|9.00 - 9.00| = 0.00$
- **Cost Error:** $|0.80 - 0.68| = 0.12$
- **Learning Value Error:** $|1.80 - 1.80| = 0.00$
- **Expected Value Realization:**
  $$EV_{\text{pred}} = 0.98 \times 9.0 + 0.5 \times 1.8 - 0.3 \times 2.10 - 0.80 = 8.29$$
  $$EV_{\text{actual}} = EV_{\text{clean}} = 1.00 \times 9.0 + 0.5 \times 1.8 - 0.3 \times 1.25 - 0.68 = 8.84$$
  $$EV_{\text{with\_bugs}} = 1.00 \times 9.0 + 0.5 \times 1.8 - 0.3 \times 1.25 - 0.68 = 8.84$$
  $$\text{Bug EV Drag} = round(EV_{\text{clean}} - EV_{\text{with\_bugs}}, 2) = 0.00$$ $$\Delta EV = +0.55$$

---

## 3. Entropy Factor Breakdown

- **State Surface Area (SSA):** Predicted `0.6` vs Observed `4.0` (9 files modified).
- **Irreversibility (IRR):** Predicted `0.0` vs Observed `0.0` (Zero destructive or stateful changes).
- **Conflict Likelihood (CL):** Predicted `0.1` vs Observed `0.0` (Clean sequential branch merges).
- **Sandbox Escape Risk (SER):** Predicted `0.0` vs Observed `0.0` (Zero security exceptions).
- **Novelty (NOV):** Predicted `0.4` vs Observed `0.4` (Standard calibration reporting schema).

---

## 4. Calibration Assessment

Plan `P-1795548994-ANA-G4N` executed with minimal error ($p\_success\_error = 0.02$, $cost\_error = 0.12$). The
calibration step successfully completed the execution lifecycle and delivered verified post-execution analysis.

---

## 5. Touch Set Accuracy

- **Precision (declared entries the diff touched):** `100.0%`
- **Recall (changed files the touch set covered):** `100.0%`

Changed files outside the touch set:

- none

Declared entries the diff did not touch:

- none
