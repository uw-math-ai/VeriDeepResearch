# Test Log

All tests run on https://vilin97-verideepresearch.hf.space on 2026-03-18.

## Simple / LLM-tricky questions

| # | Question | Time | Verified | Notes |
|---|----------|------|----------|-------|
| 1 | "Show that for all natural numbers n, n + 0 = n." | 16s | Yes | Proved by `rfl` (definitional equality). |
| 2 | "Prove that the sum of two even numbers is even." | 19s | Yes | Used `Even.add` from Mathlib + explicit proof. |
| 3 | "Which is larger, 9.9 or 9.11? Prove it." | 4s | Yes | Correctly answered 9.9 > 9.11. Proved with `norm_num`. Classic LLM failure point — verified correct. |
| 4 | "Prove that 1/3 + 1/3 + 1/3 = 1." | 16s | Yes | Proved over ℚ with `norm_num`. |
| 5 | "Prove that 1 = 2." | 2s | N/A | Correctly refused: "This statement is false in standard mathematics." No Lean code generated. |

## Graduate / Prelim level

| # | Question | Time | Verified | Notes |
|---|----------|------|----------|-------|
| 6 | "Prove that the composition of two injective functions is injective." | ~20s | Yes | Explicit proof with `intro`, `have`, `exact`. |
| 7 | "Prove Cantor's theorem: for any set S, there is no surjection from S to its power set P(S)." | 16s | Yes | Both a Mathlib one-liner (`Function.cantor_surjective`) and an explicit diagonal argument proof. |
| 8 | "Prove that every finite integral domain is a field." | 16s | Yes | Used `Finite.isDomain_to_isField` from Mathlib. |

## Research level

| # | Question | Time | Verified | Notes |
|---|----------|------|----------|-------|
| 9 | "Prove that a continuous bijection from a compact space to a Hausdorff space is a homeomorphism." | 66s | Yes | Used `isHomeomorph_iff_continuous_bijective` from Mathlib. Included detailed proof sketch explaining closed map argument. |

## Non-math rejection

| # | Question | Time | Result |
|---|----------|------|--------|
| 10 | "What is the best Italian restaurant in New York?" | 2s | Rejected: "I can only answer questions related to mathematics." |
| 11 | "What is the weather today?" | 2s | Rejected: "I'm a mathematical research assistant specialized in formalizing and verifying mathematical proofs." |

## Summary

- **9/9 mathematical questions answered correctly** (8 verified, 1 correctly identified as false)
- **2/2 non-math questions rejected**
- **Median response time: 16 seconds** for verified proofs
- **All Lean code verified** by the Axle proof checker (Lean 4.28.0 + Mathlib)
- The system correctly handles the classic "9.9 vs 9.11" trick that trips up many LLMs
- Fast path (Kimi K2.5 + Axle) suffices for most questions; Aristotle available as fallback for harder problems
