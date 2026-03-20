# Issues found in Putnam 2025 email output

Reviewed all 12 Putnam 2025 emails on 2026-03-20.

## Critical

### 1. `sorry` in "verified" proofs
**Affected**: B1 (and likely others)
**Description**: B1's email says "VERIFIED" and `proof.lean` contains `sorry`. Axle returns `okay=true` for code that compiles with `sorry` because sorry is a **warning**, not an error. The auto-finalize treats `okay=true` as fully verified.
**Impact**: Users see "VERIFIED" for incomplete proofs. This is the worst possible outcome — false confidence in an unfinished proof.
**Fix**: After Axle returns `okay=true`, check `tool_errors` for sorry mentions. Only mark as verified if the code is sorry-free.

### 2. Explanation generation fails silently (7/12 emails)
**Affected**: A1, A5, B2, B3, B4, B5, B6
**Description**: These emails show "(Proof verified — generating explanation...)" as the answer body. The auto-finalize LLM explanation call fails (likely context overflow or timeout) and the `except Exception: pass` swallows the error, leaving the placeholder.
**Impact**: 7 out of 12 emails have no mathematical explanation — just a placeholder string. The Lean code and research log are attached, but the email body is useless.
**Fix**: (a) Log the exception instead of silently passing. (b) Use a shorter prompt for the explanation call. (c) Add a deterministic fallback that extracts a basic explanation from the lean code (theorem name, types, key tactics).

### 3. Problem transcription error (A6)
**Affected**: A6
**Description**: The original Putnam A6 says `b_{2^{k+1}} - 2b_{2^k}` (powers of 2 as subscripts), but the prompt submitted was `b_{2k+1} - 2*b_{2k}` (linear subscripts). The agent correctly identified the mis-transcribed statement as false and proved the negation.
**Impact**: The system behaved correctly (proved the negation of a false statement), but the result doesn't match the actual Putnam problem.
**Root cause**: Human error in transcription from PDF to text. Not a system bug.

## Moderate

### 4. Stats not shown in email body for auto-finalized results
**Affected**: All auto-finalized emails
**Description**: The stats HTML section (time, cost, tokens, tool counts) is present in the email but may be computed before the explanation call, so the final cost/token count doesn't include the explanation call.
**Fix**: Recompute stats after the explanation call.

### 5. No way to distinguish "verified with sorry" from "verified without sorry"
**Affected**: Any proof that uses sorry
**Description**: The email badge says "VERIFIED" or "UNVERIFIED" but there's no intermediate state for "compiles but contains sorry". This is a meaningful distinction.
**Fix**: Add a third status: "PARTIAL (contains sorry)". Check for sorry in the Lean code text itself as a secondary check.

## Minor

### 6. Plain text fallback is minimal
**Affected**: All emails
**Description**: Email clients that don't render HTML get a very sparse plain text version without stats or formatting.
**Fix**: Include stats in the plain text fallback too.

### 7. Attachment filenames are generic
**Affected**: All emails
**Description**: Every email attaches `proof.lean` and `research_log.md`. When downloading multiple, they overwrite each other.
**Fix**: Include the problem name in filenames, e.g. `putnam_A6_proof.lean`.
