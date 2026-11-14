# Plan Calibration Report: P-1793438393-antigravity-agent-gemini-3.8-flash-medium

- **Plan Reference:**
  [`plans/P-1793438393-antigravity-agent-gemini-3.8-flash-medium.md`](P-1793438393-antigravity-agent-gemini-3.8-flash-medium.md)
- **Execution ID:** `E-1794660196-e8e8027b-claude-agent-claude-opus-5-5`
- **Execution Branch:**
  `I-1793438378-coherence-proxy-lifecycle-class-for-start/P-1793438393-antigravity-agent-gemini-3.8-flash-medium/E-1794660196-e8e8027b-claude-agent-claude-opus-5-5/_`
- **Intent Branch:** `I-1793438378-coherence-proxy-lifecycle-class-for-start/_`
- **Evaluating Agent:** `claude-agent/claude-opus-5-5`
- **Evaluation Timestamp:** `2026-11-14T14:02:32.000Z`
- **Evaluated Commit SHA:** `1dbe76093831dba5ad92d4f1dad35e9f1266e39c`
- **Base SHA:** `14d42daf408dfe048042732a9136000ea96dcd40`
- **Merge-Base SHA:** `14d42daf408dfe048042732a9136000ea96dcd40`
- **Merged Commits:** `0`

---

## 1. Executive Calibration Summary

| Metric                                             | Predicted (`pred`) | Actual (`actual`) | Absolute Error (`abs(pred - actual)`) | Accuracy Rating | Bias Direction             |
| :------------------------------------------------- | :----------------- | :---------------- | :------------------------------------ | :-------------- | :------------------------- |
| **$P(\text{success})$**                            | `0.98`             | `1.00`            | `0.02`                                | High (≤ 0.05)   | Slight Underconfidence     |
| **Entropy ($\Delta S$)**                           | `3.40`             | `3.04`            | `0.36`                                | High (≤ 1.0)    | Overestimated Risk         |
| **Impact**                                         | `8.90`             | `8.90`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Cost**                                           | `0.75`             | `0.64`            | `0.11`                                | High (≤ 1.0)    | Highly Accurate            |
| **Learning Value**                                 | `2.20`             | `2.20`            | `0.00`                                | Exact           | Perfectly Calibrated       |
| **Expected Value — Clean (without bugs)**          | `8.05`             | `8.45`            | `0.40`                                | High            | Conservative Underestimate |
| **Expected Value — Observed (with bugs included)** | `8.05`             | `8.45`            | `0.40`                                | High            | Conservative Underestimate |
| **Bug EV Drag**                                    | `0.00`             | `0.00`            | `0.00`                                | -               | Drag Penalty               |

---

## 2. Mathematical Derivations & Calibration Errors

- **Success Probability Error:** $|0.98 - 1.00| = 0.02$
- **Entropy Error:** $|3.40 - 3.04| = 0.36$
- **Impact Error:** $|8.90 - 8.90| = 0.00$
- **Cost Error:** $|0.75 - 0.64| = 0.11$
- **Learning Value Error:** $|2.20 - 2.20| = 0.00$
- **Expected Value Realization:**
  $$EV_{\text{pred}} = 0.98 \times 8.9 + 0.5 \times 2.2 - 0.3 \times 3.40 - 0.75 = 8.05$$
  $$EV_{\text{actual}} = EV_{\text{clean}} = 1.00 \times 8.9 + 0.5 \times 2.2 - 0.3 \times 3.04 - 0.64 = 8.45$$
  $$EV_{\text{with\_bugs}} = 1.00 \times 8.9 + 0.5 \times 2.2 - 0.3 \times 3.04 - 0.64 = 8.45$$
  $$\text{Bug EV Drag} = round(EV_{\text{clean}} - EV_{\text{with\_bugs}}, 2) = 0.00$$ $$\Delta EV = +0.40$$

---

## 3. Entropy Factor Breakdown

- **State Surface Area (SSA):** Predicted `0.6` vs Observed `10.0` (17 files modified).
- **Irreversibility (IRR):** Predicted `0.0` vs Observed `0.0` (Zero destructive or stateful changes).
- **Conflict Likelihood (CL):** Predicted `0.1` vs Observed `0.0` (Clean sequential branch merges).
- **Sandbox Escape Risk (SER):** Predicted `0.0` vs Observed `0.0` (Zero security exceptions).
- **Novelty (NOV):** Predicted `0.4` vs Observed `0.4` (Standard calibration reporting schema).

---

## 4. Calibration Assessment

Plan `P-1793438393-antigravity-agent-gemini-3.8-flash-medium` executed with minimal error ($p\_success\_error = 0.02$,
$cost\_error = 0.11$). The calibration step successfully completed the execution lifecycle and delivered verified
post-execution analysis.
