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
| 7 | "Prove Cantor's theorem: for any set S, there is no surjection from S to its power set P(S)." | 16s | Yes | Both a Mathlib one-liner (`Function.cantor_surjective`) and an explicit diagonal argument. |
| 8 | "Prove that every finite integral domain is a field." | 16s | Yes | Used `Finite.isDomain_to_isField` from Mathlib. |
| 9 | "Prove that for every positive integer n, n^3 - n is divisible by 6." | 39s | Yes | 50+ line proof: factored n(n-1)(n+1), proved divisibility by 2 and 3 via case analysis, combined via coprimality. |
| 10 | "Prove x^2 + y^2 + z^2 >= x*y + y*z + x*z for all reals." | 19s | Yes | Used `nlinarith` with `sq_nonneg` hints. Explained the sum-of-squares-of-differences identity. |

## Research level / Ambiguous questions

| # | Question | Time | Verified | Notes |
|---|----------|------|----------|-------|
| 11 | "Prove that a continuous bijection from a compact space to a Hausdorff space is a homeomorphism." | 66s | Yes | Used `isHomeomorph_iff_continuous_bijective`. Detailed proof sketch. |
| 12 | "What are the weakest assumptions on G that guarantee G is abelian?" | 54s | Yes | Researched 10+ Mathlib declarations. Gave 3 answers: cyclic G/Z(G), exponent 2, trivial commutator. All 3 proved in a single verified file. |
| 13 | "Prove Cauchy's functional equation: if f is continuous and f(x+y)=f(x)+f(y), then f(x)=cx." | 38s | Yes | Constructed AddMonoidHom, used `map_real_smul` for ℝ-linearity, deduced f(x)=f(1)*x. |
| 14 | "Under what conditions is the pointwise limit of continuous functions continuous?" | 26s | Yes | Correctly identified uniform convergence + `TendstoUniformly.continuous`. Noted counterexample f_n(x)=x^n. |
| 15 | "Prove Rolle's theorem for continuous f on [0,1] with f(0)=f(1)." | 100s | Yes | Caught the subtlety: statement is true in Mathlib because `deriv f x = 0` when f is not differentiable. 8 iterations. |
| 16 | "Weakest condition for every open cover to have a countable subcover?" | 192s | Yes | Identified second-countability, proved hierarchy SecondCountable ⟹ HereditarilyLindelöf ⟹ Lindelöf. 8 Axle verification attempts needed. |

## Aristotle escalation (hard problems)

| # | Question | Time | Result | Notes |
|---|----------|------|--------|-------|
| 17 | "Prove: finite group of order pq with p∤(q-1) is cyclic." | >15min | Timeout | Fast path failed. Submitted to Aristotle but queue was backed up. Correct escalation behavior. |
| 18 | "Prove Schur's inequality for t=1." | >15min | Timeout | Fast path failed. Submitted 2 Aristotle jobs. Queue backed up. Correct escalation behavior. |

## Non-math rejection

| # | Question | Time | Result |
|---|----------|------|--------|
| 19 | "What is the best Italian restaurant in New York?" | 2s | Rejected |
| 20 | "What is the weather today?" | 2s | Rejected |

## Summary

- **14/16 mathematical questions verified** in Lean 4 (all correct)
- **2/16 timed out** waiting for Aristotle (correctly escalated hard problems)
- **2/2 non-math questions rejected**
- **1/1 false statements correctly identified** ("prove 1=2")
- **Median response time: 19 seconds** for verified proofs
- All Lean code verified by Axle (Lean 4.28.0 + Mathlib)
- Classic LLM failures handled correctly (9.9 vs 9.11, Rolle's theorem subtlety)
- Ambiguous "what conditions" questions produced multi-part research answers with all parts verified
- Fast path (Kimi K2.5 + Axle) handles most problems; Aristotle correctly invoked for genuinely hard ones
