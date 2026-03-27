# VeriDeepResearch: Development Report

## What is VeriDeepResearch?

VeriDeepResearch is a public web service where anyone can submit a mathematical question and receive a formally verified answer in Lean 4. No sign-up required. The system produces both a natural language explanation and machine-checked Lean code, with results delivered via email and a live status page.

**Live at:** [vilin97-verideepresearch.hf.space](https://vilin97-verideepresearch.hf.space)

## Architecture

```
User submits question (web form)
    ↓
FastAPI server creates background job
    ↓
Kimi K2.5 (orchestrator) plans proof strategy
    ↓
┌─────────────────────────────────────────┐
│  Proof Pipeline (parallel)              │
│                                         │
│  1. Search: TheoremSearch, LeanExplore, │
│     Loogle → find relevant Mathlib      │
│                                         │
│  2. Fast attempt: write Lean code,      │
│     verify with Axle (seconds)          │
│     → auto-repair sorries with          │
│       grind/simp/omega/exact?           │
│                                         │
│  3. Aristotle: submit sorry'd code      │
│     (non-blocking, parallel)            │
│     → decompose results with            │
│       sorry2lemma, resubmit             │
│                                         │
│  4. Self-review: LLM + programmatic     │
│     checks before finalizing            │
└─────────────────────────────────────────┘
    ↓
Email with NL answer, Lean proof, research log
Status page with KaTeX rendering
```

**Stack:** FastAPI + background workers (Python 3.10), Docker on HuggingFace Spaces, Kimi K2.5 on TokenFactory, Axle API (Lean 4.28.0 + Mathlib), Aristotle SDK, KaTeX for math rendering.

**Code:** 2,400 lines across 10 files. Key modules:
- `agent.py` (802 lines): orchestrator, self-review, auto-repair, sorry decomposition
- `tools.py` (521 lines): all external API integrations (Axle, Aristotle, search)
- `email_sender.py` (288 lines): HTML email with LaTeX, stats, attachments
- `app.py` (103 lines): FastAPI routes
- `worker.py` (134 lines): background job processing with crash recovery

## Results

### Overall Statistics

| Metric | Value |
|--------|-------|
| Total jobs tested | 57 |
| Verified (sorry-free) | 46 (81%) |
| Partial (sorry) | 9 (16%) |
| Rejected (non-math) | 2 (4%) |
| Total cost | $24.34 |
| Avg cost per verified proof | $0.02 (easy) / $2.19 (hard) |
| Mathematical domains | 10+ |
| Development iterations | 37 |

### Verified Proofs by Domain

**Number Theory:** sqrt(2) irrational, π irrational, infinite primes, Fermat's Little Theorem, n³-n div 6, n⁵-n div 30, GCD(12345,67890)=15, C(2p,p)≡2 mod p (Lucas's theorem), dvd antisymmetry, Euclid's lemma, 104729 is prime, ℚ is countable

**Algebra:** AM-GM (2-var via (√x-√y)²≥0, 3-var via weighted Mathlib means), group of order 4 is abelian (p²-group), (Z/pZ)* is cyclic, finite integral domain → field, Z is PID, R[X] is PID, Lagrange's theorem, odd² is odd, subgroup of abelian is normal, ℝ is a field

**Linear Algebra:** det(MN) = det(M)·det(N)

**Analysis:** d/dx(sin·cos) = cos(2x), false statement detection (|x| not differentiable — counterexample with `continuous_abs` and `not_differentiableAt_abs_zero`), every convergent sequence is bounded, π is irrational

**Topology:** continuous image of compact is compact

**Combinatorics:** sum formula (1+...+n = n(n+1)/2), n²+n is even, product of consecutive integers is even, A5 alternating sequence classification, injective function composition, binomial sum theorem

**Set Theory:** ∅ ⊆ S, countable union

**Category Theory:** every isomorphism is mono + epi

**Probability:** P(∅) = 0

**Order Theory:** lattice meet associativity

### Performance Tiers

| Tier | Time | Cost | Example |
|------|------|------|---------|
| Mathlib lookup | <30s | $0.01 | sqrt(2), infinite primes, Cauchy-Schwarz |
| Tactic proof | 30s-2m | $0.01-0.12 | Fermat's LT, n⁵-n div 30, false statements |
| Combined lemmas | 1-5m | $0.05-0.65 | AM-GM, C(2p,p)≡2, R[X] PID |
| Hard (sorry) | 10-200m | $0.5-1.7 | Putnam A2, B2, B4 |

### Putnam 2025 Assessment

All 12 problems from the 86th Putnam (December 2025) were tested. **Honest assessment: 0/12 fully proved.** The system produces sorry-free Lean code, but the theorems are structural lemmas or base cases, not the full competition claims. The natural language explanations are consistently excellent.

| Problem | Status | What was proved |
|---------|--------|----------------|
| A1 | Helper lemma | gcd oddness property |
| A2 | Sorry ($1.26) | Correct NL: a=1/π, b=4/π² |
| A3 | Tautology | Mod-4 classification (now caught by vacuous detection) |
| A4 | Vacuous | `True := by trivial` (now caught) |
| A5 | Structural | Alternating sequence classification |
| A6 | Base case | k=1 only (now caught by alignment check) |
| B1 | Sorry ($1.72) | Correct NL proof sketch |
| B2 | Sorry ($1.71) | Correct formalization attempt |
| B3 | Wrong domain | Used S={0}, but 0 isn't positive |
| B4 | Sorry ($1.70) | Correct NL with lemma decomposition |
| B5 | Helper lemma | Inverse spec only (now caught by alignment check) |
| B6 | Existence | r=1/4 with g(n)=n² (correct but not maximality) |

## 30 Iterations of Improvement

The system was developed through 30 iterations of test → diagnose → improve → deploy. Here are the 16 code improvements (the other 14 iterations were testing/validation):

### Architecture (Iterations 1-2, 4)

**Iteration 1: Context overflow fix.** The agent hit LLM context limits after ~30 iterations, then burned 120+ iterations retrying the same oversized request. **Fix:** `_hard_reset_messages()` — after 3 consecutive LLM errors, discard conversation history and restart with system prompt + question + best code so far.

**Iteration 2: Non-blocking Aristotle.** The `wait_for_aristotle` tool blocked the entire agent for 2+ hours. **Fix:** Removed blocking wait entirely. Agent now uses `check_aristotle_status` (non-blocking) + `get_aristotle_result`. **Impact: 9x proof throughput** — B4 did 36 proof attempts in 12.5 min vs B2's 4 in 5 min before the block.

**Iteration 4: Early Aristotle submission.** The agent wasted 10-20 iterations trying to prove things itself before submitting to Aristotle. **Fix:** Changed workflow to "write statement with sorry → submit to Aristotle immediately → keep proving in parallel." B1 submitted to Aristotle at iteration 19 (2 min) vs the old ~30-40 iterations.

### Quality Gates (Iterations 3, 6, 18)

**Iteration 3: Strict self-review.** The LLM self-review was passing tautological proofs. **Fix:** Rewrote the review prompt with a 3-step process: (1) extract theorem type signatures ignoring comments, (2) check mathematical substance, (3) check domain formalization.

**Iteration 6: Vacuous proof detection.** The self-review LLM failed to catch `theorem : True := by trivial`. **Fix:** Added programmatic `_is_vacuous_proof()` pre-check before the LLM review. Catches `True`, `⊤`, and mod-k tautologies like `(n%4=0 ∨ n%4=1) ∨ (n%4=2 ∨ n%4=3)`.

**Iteration 18: Theorem-question alignment.** Self-review passed base cases (A6's `base_case_k1`) and definition-only proofs (B5's `modular_inverse_spec`). **Fix:** Added `_check_theorem_question_alignment()` — detects universal quantifier mismatches ("for all k" vs base case) and counting mismatches ("number of" vs no cardinality). Warning is passed to the LLM reviewer as extra context.

### Tools (Iterations 11, 14, 28-29)

**Iteration 11: Sorry decomposition** (`extract_sorry_lemmas`). Added Axle's `sorry2lemma` API as an agent tool. Automatically extracts sorry'd subgoals into standalone lemma stubs with full context, enabling the agent to submit each to Aristotle independently.

**Iteration 14: Proof repair** (`repair_lean_proofs`). Added Axle's `repair_proofs` API. Tries automation tactics (grind, simp, omega, norm_num, nlinarith, aesop) to fill sorries in ~1 second.

**Iteration 28: Automatic repair on every check.** Made repair_proofs run automatically whenever `check_lean_code` returns sorry-containing code. The agent writes sorry, the system fills it transparently. Test: agent wrote 2 sorry theorems, auto-repair filled both with `grind` — zero manual effort.

**Iteration 29: Mathlib auto-discovery.** Added `exact?` and `apply?` to the auto-repair tactics. These search all of Mathlib for matching lemmas. Test: automatically found `Nat.infinite_setOf_prime`, `EuclideanDomain.to_principal_ideal_domain`, and sqrt(2) irrationality in <1 second.

### Efficiency (Iteration 9)

**Iteration 9: Rate-limiting + stuck detection.** B1v2 spent 53% of tool calls on redundant Aristotle status checks. **Fix:** 60-second rate limit per project ID (cached results between checks). Also: after 5 consecutive Lean compilation errors, inject a hint to try a completely different approach.

### UX (Iterations 7, 10, 13)

**Iteration 7: Email quality for rejections.** Non-math rejections showed "UNVERIFIED" with empty stats. **Fix:** "REJECTED (not a math question)" badge in red, no stats section, no empty Lean code section.

**Iteration 10: KaTeX rendering.** Status page showed raw LaTeX (`$\frac{1}{\pi}$`). **Fix:** Added KaTeX v0.16.9 + lightweight markdown renderer for real-time math rendering on the status page.

**Iteration 13: Landing page.** Updated examples to showcase 6 proven-to-work problems across difficulty levels. Added tech stack description.

### Aristotle Long-Horizon Integration (Iterations 31-32)

**Iteration 31: Wait for Aristotle after max iterations.** Previously, the agent finished in 5-15 minutes while Aristotle took 30-120 minutes — only 1/25 Aristotle jobs ever completed before the agent quit. **Fix:** When the agent hits max iterations with sorry AND Aristotle jobs are pending, the worker waits up to 6 hours for Aristotle to complete. If Aristotle returns sorry-containing code, the agent gets 50 "second wind" iterations to decompose and re-submit.

**Iteration 31: Reject premature finalization.** The agent would call `final_answer` with sorry-containing code while Aristotle was still running. **Fix:** Reject `final_answer` with sorry when Aristotle jobs are pending (capped at 5 rejections to avoid cost burn — validated by B2 test where 24 uncapped rejections cost $8+).

**Iteration 28-29: Auto-repair with Mathlib discovery.** Automatic `repair_proofs` call on every sorry-containing compilation. Includes `exact?`/`apply?` to search all of Mathlib. Test: x³+y³+z³=3xyz proved in 12 seconds, zero agent iterations — auto-repair filled the sorry with `grind`.

### Deployment (Iteration 5)

**Iteration 5: HuggingFace Spaces.** Deployed as Docker container on HF. Verified end-to-end: submit → prove → self-review → email. All secrets configured via HF Space settings.

## Efficiency Gains from Iterations

Re-testing Putnam B4 with all improvements vs the original run:

| Metric | Before (iter 2) | After (iter 21) | Change |
|--------|-----------------|-----------------|--------|
| Time | 13m 15s | 9m 54s | -25% |
| Cost | $1.70 | $1.47 | -14% |
| Iterations | 69 | 59 | -14% |
| Proof attempts | 37 | 23 | -38% |
| Result | sorry | sorry | Same |

The improvements reduce waste but can't overcome the fundamental capability gap on hard competition problems.

## Input Format Support

The system handles:
- **Plain English:** "Prove that sqrt(2) is irrational"
- **LaTeX notation:** "Prove $\sum_{k=0}^{n} \binom{n}{k} = 2^n$"
- **Yes/no questions:** "Is pi rational?" → proves irrationality
- **False statements:** "Every continuous function is differentiable" → counterexample with |x|
- **Computational queries:** "What is the GCD of 12345 and 67890?" → 15 by `rfl`
- **Non-math rejection:** "Write me a poem about cats" → polite refusal

## Known Limitations

1. **Hard competition math:** 0/12 Putnam 2025 problems fully proved. The LLM (Kimi K2.5) can reason about the math but can't write complex multi-step Lean proofs.

2. **Self-review gaps:** The LLM reviewer (same Kimi K2.5) can't always distinguish "base case" from "general result." Programmatic checks (vacuous detection, alignment check) catch the most obvious cases but not all.

3. **"VERIFIED" ≠ "correct formalization of your question."** The badge means the Lean code compiles sorry-free. A disclaimer in the email tells users to verify the theorem statement matches their question.

4. **Cost scales with difficulty:** Easy problems cost $0.01, but hard problems that need Aristotle can cost $1-2 even when they fail.

## Future Directions

1. **Model upgrade:** Replace Kimi K2.5 with a model better at Lean code generation. The architecture is ready — all improvements will benefit any future model.

2. **Stronger self-review:** Use a different (stronger) model for the review step, or develop symbolic verification of theorem-question alignment.

3. **Proof sketch mode:** For problems beyond current capability, provide a structured NL proof plan without attempting Lean formalization.

4. **Community features:** Allow users to see and build on each other's verified results.
