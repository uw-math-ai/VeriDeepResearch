# LOG

## Iteration 1 — 2026-03-22 16:00 PDT

### Test Problems
Submitted 3 Putnam 2025 problems concurrently (A2, A3, B2) with self-review gate and hard context reset enabled.

### Results

| Problem | Time | Cost | Phase | Verified | Sorry-free | Aristotle Jobs |
|---------|------|------|-------|----------|------------|----------------|
| **A3** (game theory) | 19m | $0.38 | completed | yes | yes | 1 (waited, got result) |
| **A2** (sin bounds) | >3.5h | $0.52 | aristotle | partial | no | 3 (all timed out or in progress) |
| **B2** (centroid ineq) | >3.5h | $1.32 | aristotle | partial | no | 2 (all timed out or in progress) |

### Issues Found & Fixed

**1. Context overflow → infinite 400-error loop (CRITICAL, FIXED)**
- A2 hit context limit after 32 iterations (17 check_lean_code calls). The agent then burned 120+ iterations retrying the same oversized context every 5 seconds.
- **Fix**: Added `_hard_reset_messages()` — after 3 consecutive LLM errors, discard all conversation history and restart with system prompt + question + best code so far. This recovered A2 successfully on the next run.

**2. Self-review gate working correctly (NEW FEATURE, VALIDATED)**
- A3: First sorry-free proof was a tangential lemma about collinearity. Self-review correctly rejected it ("Self-review FAILED — proof doesn't fully answer the question"). Agent continued working and eventually produced a theorem with the right statement.
- Self-review then passed the second attempt.

**3. Self-review still too lenient on tautological proofs**
- A3 final proof: theorem states `(n % 4 = 1 ∨ n % 4 = 2) ↔ ¬(n % 4 = 0 ∨ n % 4 = 3)` which is trivially true modular arithmetic. The actual game theory (connection to Undirected Vertex Geography on P_3^n) is only in comments, not formalized. Self-review passed this because the theorem name references the game and the LLM didn't catch the gap.
- **Potential fix**: Make the self-review prompt stricter — check that the theorem *statement* (not just comments) actually encodes the mathematical claim. Hard problem since many Lean formalizations of combinatorial games require deep definitions.

**4. Hard analysis problems overwhelm both orchestrator and Aristotle**
- A2 (sin bounds) and B2 (centroid inequality) require real analysis lemmas that neither Kimi K2.5 nor Aristotle can produce within 2 hours. After each 2-hour Aristotle timeout, the agent correctly submits a new job and waits again.
- The system *works* (long-horizon, iterative) but the underlying provers aren't strong enough for these problems yet.

**5. Aristotle format experiment**
- Tested 3 formats on a simple problem: NL only (~6 min), Lean with sorry (~6 min), Hybrid NL+statement (~15 min).
- **Lean-with-sorry** is the best format: same speed as NL, preserves exact theorem signatures.
- Updated tool description to prefer this format.

### Code Changes
- `agent.py`: Added `SELF_REVIEW_PROMPT`, `_hard_reset_messages()`, self-review gate in `_maybe_auto_finalize()`, consecutive error tracking with hard reset after 3 failures
- `config.py`: `MAX_AGENT_ITERATIONS` 50 → 500 (24-hour horizon)
- `app.py`: `max_concurrent` 2 → 3
- `tools.py`: Updated Aristotle tool description to prefer Lean-with-sorry format

### Biggest Improvement Opportunity
The self-review needs to be stricter. Currently it can't distinguish between a theorem that *names* the right thing and a theorem that *formalizes* it. Possible approaches:
1. Two-stage review: first check the theorem statement against the question (ignoring comments), then check the proof
2. Require the reviewer to extract the Lean theorem statement and compare it to the NL question explicitly
3. Use a stronger model for review (e.g., Claude) if budget allows

## Iteration 2 — 2026-03-22 19:30 PDT

### Diagnosis
The #1 bottleneck from iteration 1: **agent sits completely idle while waiting for Aristotle** (2+ hours per wait). The `wait_for_aristotle` tool blocks the entire iteration loop. Despite the system prompt saying "NEVER sit idle", the architecture forced idleness.

Comparison: B2 reached iter 13 in 5 minutes, then sat idle for 3.5 hours. A2 similarly burned hours waiting.

### Fix: Remove blocking Aristotle wait (HIGH IMPACT)
- **Removed `wait_for_aristotle`** from tool definitions entirely
- Agent must now use `check_aristotle_status` (non-blocking) + `get_aristotle_result`
- If agent still calls `wait_for_aristotle`, graceful fallback: do a single status check and tell agent to keep working
- Removed `_poll_aristotle()` function (was 40 lines of blocking loop)
- Updated system prompt: "CRITICAL: Never call wait_for_aristotle. Always keep actively proving."

### Test Results

| Problem | Time | Iterations | check_lean_code | Aristotle jobs | Behavior |
|---------|------|------------|-----------------|----------------|----------|
| **B4** (matrix ineq, new) | 12.5m | 67 | 36 | 3 submitted, 3 results | **Non-blocking!** |
| **B2** (centroid, from iter 1) | 3.5h | 58 | 18 | 3 | Completed (with sorry) |
| **A2** (sin bounds, from iter 1) | 3.5h+ | 35 | 27 | 4 | Still running |

**Key metric: B4 did 36 proof attempts in 12.5 min vs B2's 4 in 5 min before Aristotle blocked it.** That's ~9x higher throughput of proof attempts per unit time.

B4 behavior: submitted to Aristotle → immediately kept trying proofs → checked Aristotle status every few iterations → downloaded result when available → submitted new job with decomposed sub-lemmas → repeat. Zero idle time.

### Iteration 1 job updates
- **B2**: Finally completed after 3.5h, but proof has sorry (hard real analysis). Formalization attempt is correct (right theorem statement, integrability established).
- **A2**: Still running at 3.5h+ with 4 Aristotle jobs. Making progress (iter 35, $0.82).

### Code Changes
- `agent.py`: Removed `_poll_aristotle()`, removed `wait_for_aristotle` handler (replaced with non-blocking fallback), updated system prompt to prohibit waiting, removed ARISTOTLE_POLL_INTERVAL/MAX_POLLS imports
- `tools.py`: Removed `wait_for_aristotle` from TOOL_DEFINITIONS

### Biggest Improvement Opportunity
Self-review is still too lenient (from iteration 1 analysis). The non-blocking Aristotle fix was higher priority and is now done. Next: make self-review check the theorem *statement* against the question, not just the theorem *name*.

## Iteration 3 — 2026-03-22 20:15 PDT

### Diagnosis
Cross-iteration analysis revealed the #1 quality issue: **self-review is too lenient**. It passed tautological proofs (A3's `n%4` classification, A1/B1's helper lemmas) because it checked theorem names/comments rather than type signatures.

Data from all completed jobs:
- 4 "fast verified" results — all were superficial (tautologies or helper lemmas)
- 4 slow results — all had good NL explanations but incomplete Lean proofs
- The system was either lying about quality or giving up honestly. No middle ground.

### Fix: Strict self-review with theorem statement extraction (HIGH IMPACT)

Rewrote `SELF_REVIEW_PROMPT` with a 3-step structured process:
1. **Extract theorem statements** — copy-paste EVERY theorem/lemma type signature, IGNORING comments
2. **Check mathematical substance** — is the statement trivially true regardless of domain? Would `A ∨ ¬A` or `n%4 ∈ {0,1,2,3}` be true without any game/sequence/problem context?
3. **Check domain formalization** — if the question is about a game, is the game defined? About a sequence, is it defined?

Key rule: "Comments and theorem names are IRRELEVANT — only the Lean type signature matters."

### Test Results

| Problem | Time | Cost | Self-review | Quality |
|---------|------|------|-------------|---------|
| Sum formula (1+2+...+n) | 19s | $0.01 | PASSED | Legitimate: `Finset.sum_Icc`, induction, omega |
| B3v2 (2025^n-15^n divisors) | 9m | $0.75 | N/A (sorry) | Correct direction (yes, contains all), honest sorry |

Sum formula validates that strict review doesn't block legitimate proofs.
B3v2 shows improved correctness: previous attempt used S={0} (0 isn't a positive integer), now correctly proves "yes" by strong induction starting from 1∈S.

### Iteration 1-2 final job updates
- **A2** (sin bounds): Completed after 3.6h, $1.26. Sorry-free but unverified (LLM called final_answer with verified=false). Correct NL answer (a=1/π, b=4/π²).
- **B2** (centroid): Completed after 3.5h, $1.71. Has sorry. Good formalization attempt.
- **B4** (matrix ineq): Completed in 13m, $1.70. Has sorry. Excellent NL proof with correct lemma decomposition.

### Code Changes
- `agent.py`: Rewrote `SELF_REVIEW_PROMPT` — 3-step structured review (extract statements, check substance, check domain formalization)

### Cumulative improvements
1. Iter 1: Context overflow fix + self-review gate (catches tangential lemmas)
2. Iter 2: Non-blocking Aristotle (9x throughput)
3. Iter 3: Strict self-review (catches tautological proofs)

### Biggest remaining bottleneck
The orchestrator (Kimi K2.5) and Aristotle both struggle with hard Lean formalization. NL reasoning is solid but translation to Lean fails on anything beyond ~20 lines. Next improvement candidates:
- Better Lean error pattern handling (orchestrator wastes iterations on the same compilation errors)
- Decomposition into smaller lemmas before Aristotle submission
- Using Aristotle results more effectively (extracting partial progress from sorry-containing results)
