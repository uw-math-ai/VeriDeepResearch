# Test Log

All tests run on https://vilin97-verideepresearch.hf.space (local testing via Python 3.10).

## Simple / LLM-tricky questions

| # | Question | Time | Verified | Notes |
|---|----------|------|----------|-------|
| 1 | "Show that for all natural numbers n, n + 0 = n." | 16s | Yes | Proved by `rfl`. |
| 2 | "Prove that the sum of two even numbers is even." | 19s | Yes | Used `Even.add` + explicit proof. |
| 3 | "Which is larger, 9.9 or 9.11? Prove it." | 4s | Yes | 9.9 > 9.11 via `norm_num`. Classic LLM failure — verified correct. |
| 4 | "Prove that 1/3 + 1/3 + 1/3 = 1." | 16s | Yes | Over ℚ with `norm_num`. |

## False statements (negation proved)

| # | Question | Time | Verified | Notes |
|---|----------|------|----------|-------|
| 5 | "Prove that 1 = 2." | 2s | N/A | Correctly refused. |
| 6 | "Prove every continuous function on [0,1] is differentiable." | 32s | Yes | Proved negation: |x| continuous but not differentiable at 0. |
| 7 | "Prove every monotone sequence of reals converges." | 61s | Yes | Proved negation: a_n = n is monotone but divergent. |
| 8 | "Prove every group of order 6 is abelian." | 73s | Yes | Proved negation: DihedralGroup 3 is non-abelian. |

## Graduate / Prelim level

| # | Question | Time | Verified | Notes |
|---|----------|------|----------|-------|
| 9 | "Composition of injective functions is injective." | ~20s | Yes | |
| 10 | "Cantor's theorem: no surjection from S to P(S)." | 16s | Yes | Mathlib one-liner + explicit diagonal argument. |
| 11 | "Every finite integral domain is a field." | 16s | Yes | |
| 12 | "n³ - n divisible by 6." | 39s | Yes | 50+ line proof, case analysis. |
| 13 | "x² + y² + z² ≥ xy + yz + xz." | 19s | Yes | `nlinarith` with `sq_nonneg` hints. |
| 14 | "Continuous bijection compact → Hausdorff is homeomorphism." | 52s | Yes | |
| 15 | "Weakest assumptions for abelian group." | 54s | Yes | 3 answers, all verified. |
| 16 | "Cauchy functional equation." | 38s | Yes | |
| 17 | "Weakest condition for limit of continuous functions." | 26s | Yes | Uniform convergence. |
| 18 | "Rolle's theorem without differentiability." | 100s | Yes | Caught Mathlib's `deriv` convention. |
| 19 | "Weakest condition for countable subcovers." | 192s | Yes | Second-countability → Lindelöf. |
| 20 | "Group of order pq is cyclic." | **203s** | **Yes** | Previously >15min timeout. Auto-finalize fix. |
| 21 | "Schur's inequality t=1." | **67s** | **Yes** | Previously >15min timeout. Qwen 3.5 proved it. |

## UW Analysis Prelim (Sept 2020)

| # | Question | Time | Verified | Notes |
|---|----------|------|----------|-------|
| 22 | #9a: "Weakly convergent ⟹ norm bounded." | 53s | Yes | Banach-Steinhaus. |
| 23 | "Well-ordering principle." | 18s | Yes | `Nat.find` + Loogle. |

## Putnam 2025

| # | Problem | Time | Cost | Verified | Notes |
|---|---------|------|------|----------|-------|
| 24 | **A1**: Coprimality of (2m_k+1, 2n_k+1). | 74s | $0.04 | **Yes** | Qwen + 2 Loogle + 2 Axle. |
| 25 | **A2**: Bounds a·x(π-x) ≤ sinx ≤ b·x(π-x). | 370s | $0.03 | **Yes** | a=0, b=4/π². |
| 26 | **A5**: Maximal f(s) permutation counting. | 189s | $0.05 | **Yes** | |
| 27 | **A6**: b_{2k+1} - 2b_{2k} divisibility. | 45s | $0.03 | **Yes** | Fastest Putnam solve. |
| 28 | **B2**: Centroid comparison x₁ < x₂. | 335s | $0.21 | **Yes** | Submitted to Aristotle, but agent proved it first. |
| 29 | **B3**: Set S with divisor property of 2025ⁿ-15ⁿ. | 624s | $0.21 | **Yes** | Hardest — 10+ min, multiple Qwen attempts. |
| 30 | **B4**: Matrix sum bound S ≤ (n+2)N/3. | 183s | $0.05 | **Yes** | 3 Qwen attempts, 5 Axle checks. |
| 31 | **B5**: Modular inverse ordering > p/4-1. | 84s | $0.02 | **Yes** | Cheapest Putnam solve. |
| 32 | **B6**: Largest r for g(n+1)-g(n) ≥ (g(g(n)))^r. | 511s | $0.25 | **Yes** | Aristotle started (1%), agent proved independently. |
| 33 | **A3**: Digit string game (Alice vs Bob). | 163s | $0.12 | **Yes** | Combinatorial game theory formalized. |
| 34 | **A4**: Minimal k for commuting matrices. | 64s | $0.02 | **Yes** | Fastest Putnam B-side solve. |
| 35 | **B1**: Plane coloring → monochromatic. | 225s | $0.10 | **Yes** | Geometric argument formalized. |

## Non-math rejection

| # | Question | Time | Result |
|---|----------|------|--------|
| 33 | "Best Italian restaurant in New York?" | 2s | Rejected |
| 34 | "What is the weather today?" | 2s | Rejected |

## Summary

- **12/12 Putnam 2025 problems verified** (A1-A6 and B1-B6). Total cost: $1.13.
- **33/33 mathematical questions verified** in Lean 4 across all categories
- **3/3 false statements caught** with verified negation proofs
- **2/2 non-math questions rejected**
- **Median response time: ~70 seconds** for verified proofs
- All Lean code verified by Axle (Lean 4.28.0 + Mathlib)
- Tools: TheoremSearch, LeanExplore, Loogle, Axle, Qwen 3.5, Aristotle, Kimi K2.5
- Email notification with proof.lean and research_log.md attachments
