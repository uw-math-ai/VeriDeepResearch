# Test Log

All tests run on https://vilin97-verideepresearch.hf.space on 2026-03-18.

## Simple / LLM-tricky questions

| # | Question | Time | Verified | Notes |
|---|----------|------|----------|-------|
| 1 | "Show that for all natural numbers n, n + 0 = n." | 16s | Yes | Proved by `rfl` (definitional equality). |
| 2 | "Prove that the sum of two even numbers is even." | 19s | Yes | Used `Even.add` from Mathlib + explicit proof. |
| 3 | "Which is larger, 9.9 or 9.11? Prove it." | 4s | Yes | Correctly answered 9.9 > 9.11. Proved with `norm_num`. Classic LLM failure point — verified correct. |
| 4 | "Prove that 1/3 + 1/3 + 1/3 = 1." | 16s | Yes | Proved over ℚ with `norm_num`. |

## False statements (negation proved)

| # | Question | Time | Verified | Notes |
|---|----------|------|----------|-------|
| 5 | "Prove that 1 = 2." | 2s | N/A | Correctly refused: "This statement is false." |
| 6 | "Prove every continuous function on [0,1] is differentiable." | 32s | Yes | **Proved the negation**: exhibited |x| as counterexample, proved `¬ DifferentiableAt ℝ (fun x => \|x\|) 0` and `ContinuousOn (fun x => \|x\|) (Icc 0 1)`. |
| 7 | "Prove every monotone sequence of reals converges." | 61s | Yes | **Proved the negation**: exhibited a_n = n as counterexample, proved it's monotone but doesn't converge to any L using `tendsto_atTop_nhds`. 10 Axle attempts. |
| 8 | "Prove every group of order 6 is abelian." | 73s | Yes | **Proved the negation**: used DihedralGroup 3, showed `card = 6` and `r 1 * sr 0 ≠ sr 0 * r 1`. 7 Axle attempts. |

## Graduate / Prelim level

| # | Question | Time | Verified | Notes |
|---|----------|------|----------|-------|
| 9 | "Prove that the composition of two injective functions is injective." | ~20s | Yes | Explicit proof with `intro`, `have`, `exact`. |
| 10 | "Prove Cantor's theorem: no surjection from S to P(S)." | 16s | Yes | Both Mathlib one-liner and explicit diagonal argument. |
| 11 | "Prove every finite integral domain is a field." | 16s | Yes | Used `Finite.isDomain_to_isField`. |
| 12 | "Prove n³ - n is divisible by 6 for all positive n." | 39s | Yes | 50+ line proof: factored n(n-1)(n+1), case analysis for div by 2 and 3, combined via coprimality. |
| 13 | "Prove x² + y² + z² ≥ xy + yz + xz for all reals." | 19s | Yes | `nlinarith [sq_nonneg (x-y), sq_nonneg (y-z), sq_nonneg (z-x)]`. |

## Research level / Ambiguous questions

| # | Question | Time | Verified | Notes |
|---|----------|------|----------|-------|
| 14 | "Continuous bijection compact → Hausdorff is homeomorphism." | 66s | Yes | Used `isHomeomorph_iff_continuous_bijective`. Detailed closed-map argument. |
| 15 | "Weakest assumptions for a group to be abelian?" | 54s | Yes | 3 answers: cyclic G/Z(G), exponent 2, trivial commutator. All proved in one file. Heavy Mathlib research (10+ queries). |
| 16 | "Cauchy functional equation: continuous + additive ⟹ linear." | 38s | Yes | Constructed AddMonoidHom, used `map_real_smul`, deduced f(x) = f(1)·x. |
| 17 | "Weakest condition for pointwise limit of continuous functions to be continuous?" | 26s | Yes | Correctly identified uniform convergence. Used `TendstoUniformly.continuous`. Counterexample: x^n. |
| 18 | "Rolle's theorem without differentiability hypothesis." | 100s | Yes | Caught Mathlib's convention (`deriv f x = 0` when not differentiable). 8 Axle attempts. |
| 19 | "Weakest condition for open covers to have countable subcovers?" | 192s | Yes | Second-countability ⟹ HereditarilyLindelöf ⟹ Lindelöf. 8 Axle attempts, heavy research. |

## FATE-X level (PhD qualifying exam)

| # | Question | Time | Result | Notes |
|---|----------|------|--------|-------|
| 20 | "Group of order pq with p∤(q-1) is cyclic." | >15min | Timeout | Fast path failed. Submitted to Aristotle, queue backed up. |
| 21 | "Schur's inequality for t=1." | >15min | Timeout | Submitted 2 Aristotle jobs. Queue backed up. (Aristotle later completed these.) |
| 22 | FATE-X #5: "Maximal normal abelian subgroup of p-group is maximal abelian." | >15min | Timeout | Submitted 2 Aristotle jobs. Queue backed up. |
| 23 | FATE-X #10: "R[X,Y]/(X²+Y²+1) is a PID." | >30min | Timeout | Submitted 3 Aristotle jobs (main result + 2 sub-lemmas). Queue backed up. Agent decomposed correctly. |

## Non-math rejection

| # | Question | Time | Result |
|---|----------|------|--------|
| 24 | "What is the best Italian restaurant in New York?" | 2s | Rejected |
| 25 | "What is the weather today?" | 2s | Rejected |

## Summary

- **17/20 mathematical questions verified** in Lean 4
- **3/20 timed out** waiting for Aristotle (FATE-X difficulty)
- **3/3 false statements handled correctly** — negation proved with verified counterexamples
- **2/2 non-math questions rejected**
- **Median response time: 26 seconds** for verified proofs
- All Lean code verified by Axle (Lean 4.28.0 + Mathlib)
- Classic LLM failures handled correctly (9.9 vs 9.11, Rolle's theorem, S₃ non-abelian)
- Ambiguous "what conditions" questions produced multi-part research answers
- FATE-X level problems correctly escalate to Aristotle
