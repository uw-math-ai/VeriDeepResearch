from __future__ import annotations

import asyncio
import json
import time
from openai import AsyncOpenAI
from config import (
    TOKEN_FACTORY_API_KEY,
    TOKEN_FACTORY_BASE_URL,
    KIMI_MODEL,
    INPUT_COST_PER_TOKEN,
    OUTPUT_COST_PER_TOKEN,
    MAX_COST_PER_QUERY,
    MAX_AGENT_ITERATIONS,
)
from tools import (
    search_theorems,
    search_lean_library,
    search_loogle,
    check_lean_code,
    repair_lean_proofs,
    extract_sorry_lemmas,
    submit_to_aristotle,
    check_aristotle_status,
    get_aristotle_result,
    TOOL_DEFINITIONS,
)
from job_models import JobState, JobPhase

SYSTEM_PROMPT = """\
You are VeriDeepResearch, a mathematical research assistant that produces VERIFIED answers using Lean 4 and Mathlib.

## Rules
- REFUSE non-mathematical questions. Call final_answer with a polite refusal, empty lean_code, and verified=false.
- ALWAYS start Lean code with `import Mathlib`.
- Use Lean 4.28.0 syntax with full Mathlib.
- Use LaTeX notation in your natural language answers: $...$ for inline math, $$...$$ for display math.

## Handling false statements
If a statement is FALSE or you suspect it is false:
1. Say UNAMBIGUOUSLY that the statement is false.
2. Provide a COUNTEREXAMPLE in natural language.
3. PROVE THE NEGATION in Lean 4.
4. Verify the negation proof with check_lean_code.
5. Call final_answer with the negation proof as lean_code and verified=true.

## Workflow

### Phase 1: Research
1. Search for relevant theorems with **search_theorems** (arXiv, natural language).
2. Search Mathlib with **search_lean_library** (by name or natural language).
3. Search Mathlib by type pattern with **search_loogle** (e.g. "_ + _ = _ + _").

### Phase 2: Write statement + parallel proving
1. **Write the formal Lean 4 theorem STATEMENT first** (with `sorry` as proof).
2. **Verify the statement compiles** with check_lean_code (just the statement + sorry).
3. Once the statement compiles with sorry:
   - **First try repair_lean_proofs** — it may fill simple sorries automatically in 1-2 seconds.
   - If sorry remains, **submit to Aristotle** with the sorry'd code.
   - **Simultaneously try proving it yourself** with check_lean_code.
4. If your proof attempt fails after 3-5 tries on a specific approach, try a DIFFERENT strategy:
   - Different tactics (simp, omega, ring, norm_num, linarith, nlinarith)
   - Different proof structure (induction, cases, contradiction, by_contra)
   - Decompose into smaller lemmas
5. **If the statement seems false**: try proving the NEGATION instead.
6. Note: the system automatically finalizes when Axle returns okay=true AND the code is sorry-free with theorem/lemma declarations AND self-review passes.

### Phase 3: Aristotle results + decomposition
1. **Periodically check Aristotle** with check_aristotle_status (every 5-10 iterations).
2. **When Aristotle is COMPLETE**: call get_aristotle_result, verify with check_lean_code.
3. **If Aristotle returns sorry-free**: verify with check_lean_code. Done!
4. **If Aristotle returns with sorry**:
   - Call **extract_sorry_lemmas** on the sorry-containing code. This automatically decomposes it into standalone lemma stubs.
   - Submit EACH extracted lemma to Aristotle as a separate job (use the lemma code as the prompt).
   - Try proving the sub-lemmas yourself too.
5. **You can also use extract_sorry_lemmas on YOUR OWN sorry-containing code** to decompose it before submitting to Aristotle.
6. Keep iterating until all sorries are filled or budget is exhausted.

**CRITICAL: Never call wait_for_aristotle. Submit to Aristotle EARLY (after writing the statement), not as a last resort.**

### Phase 4: Final answer
Call **final_answer** with:
- Clear natural language explanation (with LaTeX math)
- Complete verified Lean 4 code (single file, starts with `import Mathlib`)
- The code MUST declare at least one `theorem` or `lemma`
- Whether verification succeeded

## Key principles
- **Submit to Aristotle EARLY** — as soon as you have a compiling theorem statement with sorry. Don't waste 10+ iterations trying yourself first.
- **NEVER sit idle.** Keep proving while Aristotle works. NEVER call wait_for_aristotle.
- **Vary your approach.** If the same tactic fails 3 times, try something completely different.
- The code MUST contain `theorem` or `lemma` declarations.
- When Aristotle returns code with sorry, DECOMPOSE into sub-lemmas and resubmit each separately.
- For false statements, PROVE THE NEGATION.
"""

SELF_REVIEW_PROMPT = """\
You are a strict mathematical proof reviewer. You will receive:
1. An original mathematical question.
2. Lean 4 code that compiles without errors and without sorry.

Your task: determine whether the Lean 4 code **actually proves the main claim**.

## Step 1: Extract theorem statements
List EVERY `theorem` and `lemma` declaration from the code. Write out the FULL type signature (everything between the name and `:= by`). IGNORE all comments.

## Step 2: Check mathematical substance
For each theorem statement, ask:
- Does this statement encode the SPECIFIC mathematical claim from the question?
- Or is it a TRIVIALLY TRUE statement (e.g., `A ∨ ¬A`, `n % 4 ∈ {0,1,2,3}`, basic type equivalences)?
- Would this statement be true REGARDLESS of the mathematical context? If so, it's trivial.

## Step 3: Check domain formalization
- If the question involves a game, does the code define the game and prove a property of it?
- If the question involves sequences, does the code define the sequence?
- If the question involves specific mathematical objects, are they formalized?
- A theorem about `n % 4` does NOT prove anything about a game just because a comment says so.

## Rules
- Comments and theorem names are IRRELEVANT — only the Lean type signature matters.
- Helper lemmas without a main result = FAIL.
- Trivially true statements dressed up with domain-specific names = FAIL.
- The theorem must FORMALIZE the actual mathematical claim, not just name it.

Respond with:
1. Extracted theorem statements (copy-paste from code)
2. Brief analysis of each (1 sentence: what does this actually prove?)
3. **Verdict: PASS** or **Verdict: FAIL**
"""

def _is_vacuous_proof(code: str) -> bool:
    """Detect proofs whose theorem conclusion is trivially true (True, tauto, etc.)."""
    import re
    # Normalize: join continuation lines (indented lines) into previous line
    normalized = re.sub(r'\n\s+', ' ', code)

    for line in normalized.split("\n"):
        stripped = line.strip()
        if not re.match(r'(?:theorem|lemma)\s', stripped):
            continue
        # Check if the conclusion (text between last standalone `:` and `:=`) is True
        # Find `:= by` or `:= trivial` etc.
        assign_match = re.search(r':=\s*(?:by\b|trivial|tauto|True\.intro)', stripped)
        if not assign_match:
            continue
        before_assign = stripped[:assign_match.start()].rstrip()
        # The conclusion is after the LAST `:` that's not inside parens/brackets
        # Simple heuristic: split on ` : ` (with spaces) and take the last part
        parts = re.split(r'\)\s*:', before_assign)
        if len(parts) >= 2:
            conclusion = parts[-1].strip()
        else:
            # Try splitting on `: `
            parts2 = before_assign.rsplit(': ', 1)
            conclusion = parts2[-1].strip() if len(parts2) >= 2 else ""

        if conclusion in ("True", "⊤"):
            return True
        # Check for mod-tautologies: (n%k=0 ∨ n%k=1) ∨ (n%k=2 ∨ n%k=3)
        if re.fullmatch(r'[\s\(\)∨∧]*(?:\w+\s*%\s*\d+\s*=\s*\d+[\s\(\)∨∧]*)+', conclusion):
            return True

    return False


def _check_theorem_question_alignment(question: str, code: str) -> str | None:
    """Check if theorems in the code plausibly address the question. Returns a warning or None."""
    import re
    q_lower = question.lower()

    # Extract all theorem/lemma names from the code
    normalized = re.sub(r'\n\s+', ' ', code)
    theorem_lines = [l.strip() for l in normalized.split("\n")
                     if re.match(r'(?:theorem|lemma)\s', l.strip())]

    if not theorem_lines:
        return None

    # Check 1: Question asks "for all/every/each k" but no theorem has ∀ over that variable
    universal_patterns = re.findall(r'for (?:all|every|each)\s+(\w+)', q_lower)
    if universal_patterns:
        has_forall = any('∀' in t or 'forall' in t.lower() for t in theorem_lines)
        # Check if any theorem mentions specific values instead of universally quantified
        all_specific = all(
            not any(f'({var}' in t.lower() or f' {var} ' in t.lower() for t in theorem_lines)
            for var in universal_patterns
        )
        # Don't flag if theorems use implicit quantification (arguments before `:`)
        if not has_forall and all_specific and len(theorem_lines) == 1:
            # Only flag if there's just one lemma (likely a base case)
            name_match = re.match(r'(?:theorem|lemma)\s+(\S+)', theorem_lines[0])
            name = name_match.group(1) if name_match else ""
            if 'base' in name.lower() or 'case' in name.lower():
                return f"WARNING: Question asks 'for all {universal_patterns[0]}' but theorem '{name}' appears to be a base case only."

    # Check 2: Question asks about "number of" / "count" but no theorem involves Finset.card
    if any(w in q_lower for w in ['number of', 'how many', 'count']):
        has_counting = any('card' in t.lower() or 'count' in t.lower() or 'Finset' in t for t in theorem_lines)
        if not has_counting:
            return "WARNING: Question asks about counting but no theorem involves cardinality/counting."

    return None


def _summarize_lean_errors(errors: list) -> str:
    """Produce a short summary of Lean error types for status messages."""
    if not errors:
        return ""
    categories = {}
    for e in errors:
        msg = str(e.get("message", e) if isinstance(e, dict) else e)
        if "unknown identifier" in msg or "unknown constant" in msg:
            categories["unknown identifier"] = categories.get("unknown identifier", 0) + 1
        elif "type mismatch" in msg:
            categories["type mismatch"] = categories.get("type mismatch", 0) + 1
        elif "unsolved goals" in msg:
            categories["unsolved goals"] = categories.get("unsolved goals", 0) + 1
        elif "expected" in msg.lower() and "got" in msg.lower():
            categories["syntax"] = categories.get("syntax", 0) + 1
    if not categories:
        return ""
    parts = [f"{v} {k}" for k, v in categories.items()]
    return f" ({', '.join(parts)})"


TERMINAL_STATUSES = {
    "COMPLETE", "COMPLETE_WITH_ERRORS", "FAILED",
    "CANCELED", "OUT_OF_BUDGET",
}

MAX_TOOL_RESULT_CHARS = 3000
MAX_KEEP_RECENT = 30


def _hard_reset_messages(job: JobState):
    """Nuclear option: discard conversation history, keep only system + question + best code context."""
    fresh = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": job.question},
    ]
    if job.best_lean_code:
        status = "sorry-free" if job.best_code_sorry_free else "contains sorry"
        fresh.append({
            "role": "user",
            "content": (
                f"CONTEXT RESET: Previous conversation exceeded context limits.\n"
                f"Best Lean code so far ({status}):\n```lean4\n{job.best_lean_code[:4000]}\n```\n"
                f"Continue improving this proof. If it has sorry, fill them in. "
                f"If it doesn't fully prove the claim, fix the theorem statement."
            ),
        })
    else:
        fresh.append({
            "role": "user",
            "content": "CONTEXT RESET: Previous conversation exceeded context limits. Start fresh.",
        })
    job.messages = fresh


def _compress_messages(messages: list[dict]) -> list[dict]:
    if len(messages) <= MAX_KEEP_RECENT + 2:
        return messages
    head = messages[:2]
    recent = messages[-MAX_KEEP_RECENT:]
    middle = messages[2:-MAX_KEEP_RECENT]
    compressed = []
    for msg in middle:
        if msg.get("role") == "tool":
            content = msg.get("content", "")
            if len(content) > MAX_TOOL_RESULT_CHARS:
                msg = dict(msg)
                msg["content"] = content[:MAX_TOOL_RESULT_CHARS] + "\n... [truncated]"
            compressed.append(msg)
        elif msg.get("role") == "assistant" and not msg.get("tool_calls"):
            continue
        else:
            compressed.append(msg)
    return head + compressed + recent


async def run_agent_job(job: JobState) -> None:
    """Run the proof pipeline for a job. Mutates job in place, saves to disk after each step."""
    client = AsyncOpenAI(
        base_url=TOKEN_FACTORY_BASE_URL,
        api_key=TOKEN_FACTORY_API_KEY,
    )

    # Initialize messages if fresh job
    if not job.messages:
        job.messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": job.question},
        ]
        job.add_status("Analyzing your question...")
        job.set_phase(JobPhase.RESEARCHING)
        job.save()

    consecutive_errors = 0
    MAX_CONSECUTIVE_ERRORS = 3

    for iteration in range(job.iteration, MAX_AGENT_ITERATIONS):
        job.iteration = iteration

        if job.total_cost >= MAX_COST_PER_QUERY:
            job.add_status(f"Budget limit reached (${job.total_cost:.4f}).")
            break

        messages = _compress_messages(job.messages)

        try:
            response = await client.chat.completions.create(
                model=KIMI_MODEL,
                messages=messages,
                tools=TOOL_DEFINITIONS,
                temperature=0.6,
                max_tokens=16384,
            )
            consecutive_errors = 0  # reset on success
        except Exception as e:
            consecutive_errors += 1
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                # Context is likely too large — hard reset
                job.add_status("Context overflow detected — resetting conversation.")
                job.add_log("## Hard context reset after repeated LLM errors")
                _hard_reset_messages(job)
                consecutive_errors = 0
                job.save()
                continue
            job.add_status(f"LLM error: {e}")
            job.save()
            await asyncio.sleep(5)
            continue

        if response.usage:
            inp = response.usage.prompt_tokens or 0
            out = response.usage.completion_tokens or 0
            job.total_input_tokens += inp
            job.total_output_tokens += out
            job.total_cost += inp * INPUT_COST_PER_TOKEN + out * OUTPUT_COST_PER_TOKEN

        choice = response.choices[0]
        assistant_msg = choice.message

        msg_dict = {"role": "assistant", "content": assistant_msg.content or ""}
        if assistant_msg.tool_calls:
            msg_dict["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in assistant_msg.tool_calls
            ]
        job.messages.append(msg_dict)

        if not assistant_msg.tool_calls:
            if assistant_msg.content:
                job.add_log(f"## Agent thinking\n{assistant_msg.content}")
            job.save()
            continue

        for tool_call in assistant_msg.tool_calls:
            fn_name = tool_call.function.name
            try:
                fn_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                fn_args = {}

            job.tool_counts[fn_name] = job.tool_counts.get(fn_name, 0) + 1
            _update_phase(job, fn_name)
            job.add_log(f"## Tool: `{fn_name}`\n**Args:** ```\n{json.dumps(fn_args, indent=2)[:2000]}\n```")

            # Handle final_answer
            if fn_name == "final_answer":
                job.answer = fn_args.get("answer", "")
                job.best_lean_code = fn_args.get("lean_code", job.best_lean_code)
                job.best_code_verified = fn_args.get("verified", False)
                job.best_code_sorry_free = "sorry" not in job.best_lean_code
                job.set_phase(JobPhase.COMPLETED)
                job.finished_at = time.time()
                job.add_status("Research complete!")
                job.save()
                return

            # wait_for_aristotle removed — redirect to non-blocking check
            if fn_name == "wait_for_aristotle":
                project_id = fn_args.get("project_id", "")
                info = await check_aristotle_status(project_id)
                status = info.get("status", "UNKNOWN")
                if status in ("COMPLETE", "COMPLETE_WITH_ERRORS"):
                    result = await get_aristotle_result(project_id)
                else:
                    result = json.dumps(info) + "\n\nAristotle is still running. Do NOT wait — keep working on the proof yourself. Check back later with check_aristotle_status."
                job.messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })
                job.add_log(f"**Result:** ```\n{result[:5000]}\n```")
                job.save()
                continue

            # Execute regular tool
            result = await _handle_tool_call(fn_name, fn_args, job)
            job.add_log(f"**Result:** ```\n{result[:5000]}\n```")

            # Auto-finalize if check_lean_code returned okay + sorry-free + has theorem
            if fn_name == "check_lean_code":
                auto = await _maybe_auto_finalize(job, fn_args, result, client)
                if auto:
                    return
                _track_best_code(job, fn_args, result)
                # Stuck detection: if 5+ consecutive check_lean_code with errors, nudge
                if not hasattr(job, '_consecutive_lean_errors'):
                    job._consecutive_lean_errors = 0
                try:
                    parsed_result = json.loads(result)
                    if parsed_result.get("okay"):
                        job._consecutive_lean_errors = 0
                    else:
                        job._consecutive_lean_errors += 1
                        if job._consecutive_lean_errors >= 5:
                            job._consecutive_lean_errors = 0
                            job.messages.append({
                                "role": "user",
                                "content": "HINT: You've had 5+ consecutive Lean compilation errors. Try a COMPLETELY DIFFERENT approach: different proof strategy, different formalization, or decompose into smaller lemmas. If you haven't submitted to Aristotle yet, do so now with your best sorry'd code.",
                            })
                except (json.JSONDecodeError, KeyError):
                    pass

            job.messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })
            job.save()

    # Max iterations reached — but check if Aristotle jobs are still running
    pending_aristotle = [
        aj for aj in job.aristotle_jobs
        if aj.get("status") not in ("COMPLETE", "COMPLETE_WITH_ERRORS", "FAILED", "CANCELED", "OUT_OF_BUDGET", None)
        or aj.get("status") in ("SUBMITTED", "QUEUED", "IN_PROGRESS")
    ]
    if pending_aristotle and "sorry" in (job.best_lean_code or ""):
        job.add_status(f"Max iterations reached. Waiting for {len(pending_aristotle)} Aristotle job(s) to finish...")
        job.save()
        # Wait for Aristotle jobs (poll every 30s, up to 2 hours)
        for poll in range(240):
            await asyncio.sleep(30)
            all_done = True
            for aj in pending_aristotle:
                pid = aj.get("project_id", "")
                try:
                    info = await check_aristotle_status(pid)
                    status = info.get("status", "UNKNOWN")
                    pct = info.get("percent_complete")
                    aj["status"] = status
                    aj["percent_complete"] = pct
                    elapsed_min = (poll + 1) * 30 // 60
                    pct_str = f" ({pct}%)" if pct is not None else ""
                    if poll % 4 == 0:  # Log every 2 min
                        job.add_status(f"Aristotle [{pid[:8]}]: {status}{pct_str} — {elapsed_min}m")
                    if status not in TERMINAL_STATUSES:
                        all_done = False
                    elif status in ("COMPLETE", "COMPLETE_WITH_ERRORS"):
                        # Download and try to use the result
                        job.add_status(f"Aristotle [{pid[:8]}] completed! Downloading...")
                        ari_code = await get_aristotle_result(pid)
                        job.add_log(f"## Aristotle result [{pid[:8]}]\n```\n{ari_code[:5000]}\n```")
                        # Check if the result is sorry-free
                        if ari_code and "sorry" not in ari_code:
                            # Verify with Axle
                            check_result = await check_lean_code(ari_code)
                            try:
                                parsed = json.loads(check_result)
                                if parsed.get("okay"):
                                    has_theorem = any(
                                        line.strip().startswith(("theorem ", "lemma "))
                                        for line in ari_code.split("\n")
                                    )
                                    if has_theorem:
                                        job.best_lean_code = ari_code
                                        job.best_code_verified = True
                                        job.best_code_sorry_free = True
                                        job.add_status(f"Aristotle proof verified! Sorry-free!")
                                        # Generate explanation
                                        job.answer = _generate_fallback_explanation(job.question, ari_code)
                                        job.set_phase(JobPhase.COMPLETED)
                                        job.finished_at = time.time()
                                        job.add_status("Research complete (via Aristotle)!")
                                        job.save()
                                        return
                            except json.JSONDecodeError:
                                pass
                        # Aristotle returned sorry — give agent a "second wind"
                        if ari_code:
                            job.best_lean_code = ari_code
                            job.add_status(f"Aristotle returned code with sorry. Giving agent more iterations to decompose...")
                            job.add_log(f"## Second wind: Aristotle returned sorry-containing code")
                            # Feed Aristotle's output into the conversation
                            job.messages.append({
                                "role": "user",
                                "content": (
                                    f"Aristotle returned this Lean code (has sorry):\n```lean4\n{ari_code[:4000]}\n```\n\n"
                                    "Use extract_sorry_lemmas to decompose the remaining sorries, then submit each to Aristotle. "
                                    "Also try filling the sorries yourself with check_lean_code."
                                ),
                            })
                            # Grant 50 more iterations
                            job.save()
                            second_wind_iterations = min(50, MAX_AGENT_ITERATIONS - job.iteration)
                            if second_wind_iterations > 0:
                                job.add_status(f"Second wind: {second_wind_iterations} more iterations granted.")
                                # Re-enter the main loop (recursive call with iteration limit)
                                old_max = MAX_AGENT_ITERATIONS
                                for sw_iter in range(second_wind_iterations):
                                    job.iteration += 1
                                    if job.total_cost >= MAX_COST_PER_QUERY:
                                        break
                                    messages = _compress_messages(job.messages)
                                    try:
                                        response = await client.chat.completions.create(
                                            model=KIMI_MODEL, messages=messages,
                                            tools=TOOL_DEFINITIONS, temperature=0.6, max_tokens=16384,
                                        )
                                    except Exception:
                                        break
                                    if response.usage:
                                        inp = response.usage.prompt_tokens or 0
                                        out = response.usage.completion_tokens or 0
                                        job.total_input_tokens += inp
                                        job.total_output_tokens += out
                                        job.total_cost += inp * INPUT_COST_PER_TOKEN + out * OUTPUT_COST_PER_TOKEN
                                    choice = response.choices[0]
                                    assistant_msg = choice.message
                                    msg_dict = {"role": "assistant", "content": assistant_msg.content or ""}
                                    if assistant_msg.tool_calls:
                                        msg_dict["tool_calls"] = [
                                            {"id": tc.id, "type": "function",
                                             "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                                            for tc in assistant_msg.tool_calls
                                        ]
                                    job.messages.append(msg_dict)
                                    if not assistant_msg.tool_calls:
                                        job.save()
                                        continue
                                    for tool_call in assistant_msg.tool_calls:
                                        fn_name = tool_call.function.name
                                        try:
                                            fn_args = json.loads(tool_call.function.arguments)
                                        except json.JSONDecodeError:
                                            fn_args = {}
                                        job.tool_counts[fn_name] = job.tool_counts.get(fn_name, 0) + 1
                                        if fn_name == "final_answer":
                                            job.answer = fn_args.get("answer", "")
                                            job.best_lean_code = fn_args.get("lean_code", job.best_lean_code)
                                            job.best_code_verified = fn_args.get("verified", False)
                                            job.best_code_sorry_free = "sorry" not in job.best_lean_code
                                            job.set_phase(JobPhase.COMPLETED)
                                            job.finished_at = time.time()
                                            job.add_status("Research complete (second wind)!")
                                            job.save()
                                            return
                                        result = await _handle_tool_call(fn_name, fn_args, job)
                                        if fn_name == "check_lean_code":
                                            auto = await _maybe_auto_finalize(job, fn_args, result, client)
                                            if auto:
                                                return
                                            _track_best_code(job, fn_args, result)
                                        job.messages.append({
                                            "role": "tool", "tool_call_id": tool_call.id, "content": result,
                                        })
                                        job.save()
                except Exception as e:
                    job.add_log(f"## Aristotle poll error: {e}")
            job.save()
            if all_done:
                break

    # Finalize
    if not job.answer and job.best_lean_code:
        job.answer = _generate_fallback_explanation(job.question, job.best_lean_code)
    job.set_phase(JobPhase.COMPLETED if job.best_lean_code else JobPhase.FAILED)
    job.finished_at = time.time()
    job.add_status(f"Job complete. Cost: ${job.total_cost:.4f}")
    job.save()


def _update_phase(job: JobState, fn_name: str):
    phase = job.get_phase()
    if fn_name in ("search_theorems", "search_lean_library", "search_loogle"):
        if phase in (JobPhase.QUEUED,):
            job.set_phase(JobPhase.RESEARCHING)
    elif fn_name == "check_lean_code":
        if phase in (JobPhase.QUEUED, JobPhase.RESEARCHING):
            job.set_phase(JobPhase.PROVING_FAST)
    elif fn_name in ("submit_to_aristotle", "wait_for_aristotle", "check_aristotle_status"):
        job.set_phase(JobPhase.ARISTOTLE)


async def _handle_tool_call(fn_name: str, fn_args: dict, job: JobState) -> str:
    if fn_name == "search_theorems":
        query = fn_args.get("query", "")
        job.add_status(f'Searching for theorems: "{query}"...')
        return await search_theorems(query)

    if fn_name == "search_lean_library":
        query = fn_args.get("query", "")
        job.add_status(f'Searching Mathlib: "{query}"...')
        return await search_lean_library(query)

    if fn_name == "search_loogle":
        query = fn_args.get("query", "")
        job.add_status(f'Searching Loogle: "{query}"...')
        return await search_loogle(query)

    if fn_name == "check_lean_code":
        job.add_status("Verifying Lean code with Axle...")
        code = fn_args.get("code", "")
        result = await check_lean_code(code)
        try:
            parsed = json.loads(result)
            if parsed.get("okay"):
                has_sorry = "sorry" in code
                if has_sorry:
                    # Auto-repair: try to fill sorries with automation tactics
                    repair_result = await repair_lean_proofs(code)
                    try:
                        repair_parsed = json.loads(repair_result)
                        repairs = repair_parsed.get("repairs_applied", 0)
                        if repairs > 0 and not repair_parsed.get("still_has_sorry", True):
                            # All sorries filled! Replace the code in fn_args and result
                            repaired_code = repair_parsed.get("repaired_code", code)
                            fn_args["code"] = repaired_code
                            job.add_status(f"Auto-repair filled {repairs} sorry(s)! Verifying repaired code...")
                            job.add_log(f"## Auto-repair: {repairs} sorry(s) filled by automation")
                            # Re-verify the repaired code
                            result = await check_lean_code(repaired_code)
                            parsed = json.loads(result)
                            if parsed.get("okay") and "sorry" not in repaired_code:
                                job.add_status("Repaired code verified successfully!")
                            else:
                                job.add_status("Repaired code has issues — using original.")
                                fn_args["code"] = code  # revert
                        elif repairs > 0:
                            job.add_status(f"Auto-repair filled {repairs} sorry(s), {repair_parsed.get('still_has_sorry', True) and 'some remain' or 'done'}.")
                        else:
                            job.add_status("Lean code compiles but contains `sorry` — continuing...")
                    except (json.JSONDecodeError, Exception):
                        job.add_status("Lean code compiles but contains `sorry` — continuing...")
                else:
                    job.add_status("Lean code verified successfully!")
            else:
                errors = parsed.get("errors", [])
                n = len(errors)
                # Summarize error types for better status messages
                summary = _summarize_lean_errors(errors)
                job.add_status(f"Lean code has {n} error(s){summary}")
        except json.JSONDecodeError:
            pass
        return result

    if fn_name == "repair_lean_proofs":
        code = fn_args.get("code", "")
        job.add_status("Attempting automatic proof repair...")
        result = await repair_lean_proofs(code)
        try:
            parsed = json.loads(result)
            repairs = parsed.get("repairs_applied", 0)
            has_sorry = parsed.get("still_has_sorry", True)
            if repairs > 0 and not has_sorry:
                job.add_status(f"Proof repair succeeded! {repairs} sorry(s) filled automatically.")
            elif repairs > 0:
                job.add_status(f"Partial repair: {repairs} sorry(s) filled, some remain.")
            else:
                job.add_status("Proof repair: no sorries could be filled automatically.")
        except json.JSONDecodeError:
            pass
        return result

    if fn_name == "extract_sorry_lemmas":
        code = fn_args.get("code", "")
        job.add_status("Extracting sorry'd sub-lemmas...")
        result = await extract_sorry_lemmas(code)
        try:
            parsed = json.loads(result)
            n = parsed.get("num_lemmas", 0)
            names = parsed.get("lemma_names", [])
            job.add_status(f"Extracted {n} sub-lemma(s): {', '.join(names)}")
        except json.JSONDecodeError:
            pass
        return result

    if fn_name == "submit_to_aristotle":
        prompt = fn_args.get("prompt", "")
        preview = prompt[:120].replace("\n", " ").strip()
        if len(prompt) > 120:
            preview += "..."
        job.add_status(f'**Submitted to Aristotle:** "{preview}"')
        result = await submit_to_aristotle(prompt)
        try:
            parsed = json.loads(result)
            pid = parsed.get("project_id", "")
            if pid:
                job.add_status(f"Aristotle job **{pid[:8]}** queued")
                job.aristotle_jobs.append({
                    "project_id": pid,
                    "prompt_preview": preview,
                    "status": "SUBMITTED",
                })
            elif "error" in parsed:
                job.add_status(f"Aristotle error: {parsed['error']}")
        except json.JSONDecodeError:
            pass
        return result

    if fn_name == "check_aristotle_status":
        project_id = fn_args.get("project_id", "")
        # Rate-limit: skip if checked within last 60 seconds
        now = time.time()
        last_check_key = f"_ari_check_{project_id}"
        last_check = getattr(job, '_ari_check_times', {}).get(project_id, 0)
        if now - last_check < 60:
            # Return cached status without API call
            for aj in job.aristotle_jobs:
                if aj.get("project_id") == project_id:
                    cached = {"project_id": project_id, "status": aj.get("status", "UNKNOWN"), "percent_complete": aj.get("percent_complete")}
                    return json.dumps(cached) + "\n\n(Cached — check again later. Focus on proving the theorem yourself.)"
        # Actual API call
        if not hasattr(job, '_ari_check_times'):
            job._ari_check_times = {}
        job._ari_check_times[project_id] = now
        info = await check_aristotle_status(project_id)
        status = info.get("status", "UNKNOWN")
        pct = info.get("percent_complete")
        pct_str = f" ({pct}%)" if pct is not None else ""
        job.add_status(f"Aristotle [{project_id[:8]}]: {status}{pct_str}")
        # Update aristotle_jobs list
        for aj in job.aristotle_jobs:
            if aj.get("project_id") == project_id:
                aj["status"] = status
                aj["percent_complete"] = pct
        return json.dumps(info)

    if fn_name == "get_aristotle_result":
        project_id = fn_args.get("project_id", "")
        job.add_status(f"Downloading Aristotle result [{project_id[:8]}]...")
        return await get_aristotle_result(project_id)

    return json.dumps({"error": f"Unknown tool: {fn_name}"})


    # _poll_aristotle removed — blocking wait was the #1 bottleneck.
    # Agent now uses check_aristotle_status (non-blocking) + get_aristotle_result.


async def _maybe_auto_finalize(
    job: JobState, fn_args: dict, result: str, client: AsyncOpenAI
) -> bool:
    """If check_lean_code returned okay + sorry-free + has theorem, run self-review then finalize.

    The self-review asks the LLM (with clean context) whether the Lean code
    actually proves the claim in the original question, not just a tangential lemma.
    """
    try:
        parsed = json.loads(result)
        if not parsed.get("okay"):
            return False

        code = fn_args.get("code", "")
        tool_errors = parsed.get("tool_errors", [])
        has_sorry = "sorry" in code or any("sorry" in e for e in tool_errors)
        has_theorem = any(
            line.strip().startswith(("theorem ", "lemma "))
            for line in code.split("\n")
        )

        if has_sorry:
            return False
        if not has_theorem:
            job.add_status("Code compiles but has no theorem/lemma — continuing...")
            return False

        # --- Programmatic pre-check: catch obviously vacuous proofs ---
        if _is_vacuous_proof(code):
            job.add_status("Proof is vacuous (trivial conclusion) — continuing...")
            job.add_log("## Pre-check: vacuous proof detected (True, trivial, tauto)")
            job.messages.append({
                "role": "user",
                "content": "SELF-REVIEW RESULT: Your proof is VACUOUS — the theorem conclusion is trivially true (e.g., `True`, proved by `trivial`/`tauto`). This does NOT prove anything about the original question. You must state a theorem whose TYPE encodes the actual mathematical claim.",
            })
            return False

        # --- Programmatic pre-check: theorem-question alignment ---
        alignment_warning = _check_theorem_question_alignment(job.question, code)
        if alignment_warning:
            job.add_status(f"Alignment check: {alignment_warning}")
            job.add_log(f"## Alignment check warning\n{alignment_warning}")
            # Don't reject outright — pass to LLM self-review with the warning as context

        # --- Self-review: does this code actually answer the question? ---
        job.add_status("Lean code verified (sorry-free)! Running self-review...")
        job.add_log("## Self-review: checking if proof answers the original question")

        review_passed = True  # default to pass if review fails
        try:
            review_resp = await client.chat.completions.create(
                model=KIMI_MODEL,
                messages=[
                    {"role": "system", "content": SELF_REVIEW_PROMPT},
                    {"role": "user", "content": f"## Original question\n{job.question}\n\n## Lean 4 code (compiles, sorry-free)\n```lean4\n{code[:4000]}\n```{chr(10) + chr(10) + '## Alignment warning' + chr(10) + alignment_warning if alignment_warning else ''}"},
                ],
                temperature=0.2,
                max_tokens=1024,
            )
            if review_resp.usage:
                inp = review_resp.usage.prompt_tokens or 0
                out = review_resp.usage.completion_tokens or 0
                job.total_input_tokens += inp
                job.total_output_tokens += out
                job.total_cost += inp * INPUT_COST_PER_TOKEN + out * OUTPUT_COST_PER_TOKEN
            review_text = (review_resp.choices[0].message.content or "").strip()
            job.add_log(f"## Self-review result\n{review_text}")

            # Parse verdict: look for PASS or FAIL
            verdict_lower = review_text.lower()
            if "verdict: fail" in verdict_lower or "**fail**" in verdict_lower:
                review_passed = False
                job.add_status("Self-review FAILED — proof doesn't fully answer the question. Continuing...")
                job.add_log("## Self-review: FAIL — continuing to improve proof")
            elif "verdict: pass" in verdict_lower or "**pass**" in verdict_lower:
                review_passed = True
                job.add_status("Self-review PASSED — proof addresses the question.")
            else:
                # Ambiguous — check for negative signals
                if any(w in verdict_lower for w in ["does not prove", "doesn't prove", "tangential", "helper lemma only", "not the main claim"]):
                    review_passed = False
                    job.add_status("Self-review indicates incomplete proof. Continuing...")
                else:
                    review_passed = True
                    job.add_status("Self-review passed (no objections).")

        except Exception as e:
            job.add_log(f"## Self-review failed (error): {e}")
            job.add_status("Self-review error — finalizing anyway.")

        if not review_passed:
            # Don't finalize — inject review feedback as a user message
            # so the agent knows to keep working on the actual claim
            job.messages.append({
                "role": "user",
                "content": "SELF-REVIEW RESULT: Your Lean code compiles and is sorry-free, but it does NOT fully prove the main claim from the original question. It only proves helper lemmas or tangential results. You MUST formalize and prove the MAIN CLAIM. Keep working.",
            })
            return False

        # --- Review passed: finalize ---
        job.add_log("## Auto-finalize: okay=true, sorry-free, has theorem, self-review passed")

        # Generate explanation
        answer = _generate_fallback_explanation(job.question, code)
        try:
            resp = await client.chat.completions.create(
                model=KIMI_MODEL,
                messages=[
                    {"role": "system", "content": "Write a clear, concise natural language explanation of this verified Lean 4 proof. Use LaTeX ($...$, $$...$$). Focus on the mathematical content."},
                    {"role": "user", "content": f"Question: {job.question}\n\nVerified Lean 4 code:\n```lean4\n{code[:3000]}\n```"},
                ],
                temperature=0.4,
                max_tokens=2048,
            )
            if resp.usage:
                inp = resp.usage.prompt_tokens or 0
                out = resp.usage.completion_tokens or 0
                job.total_input_tokens += inp
                job.total_output_tokens += out
                job.total_cost += inp * INPUT_COST_PER_TOKEN + out * OUTPUT_COST_PER_TOKEN
            llm_answer = resp.choices[0].message.content
            if llm_answer and len(llm_answer) > 20:
                answer = llm_answer
        except Exception as e:
            job.add_log(f"## Explanation generation failed: {e}")

        job.answer = answer
        job.best_lean_code = code
        job.best_code_verified = True
        job.best_code_sorry_free = True
        job.set_phase(JobPhase.COMPLETED)
        job.finished_at = time.time()
        job.add_status("Research complete!")
        job.save()
        return True

    except (json.JSONDecodeError, KeyError):
        return False


def _track_best_code(job: JobState, fn_args: dict, result: str):
    try:
        parsed = json.loads(result)
        code = fn_args.get("code", "")
        if not parsed.get("okay"):
            return
        has_theorem = any(
            line.strip().startswith(("theorem ", "lemma "))
            for line in code.split("\n")
        )
        if not has_theorem:
            return
        has_sorry = "sorry" in code
        if not has_sorry:
            job.best_lean_code = code
            job.best_code_verified = True
            job.best_code_sorry_free = True
        elif not job.best_code_verified:
            job.best_lean_code = code
            job.best_code_verified = True
            job.best_code_sorry_free = False
    except (json.JSONDecodeError, KeyError):
        pass


def _generate_fallback_explanation(question: str, lean_code: str) -> str:
    lines = lean_code.strip().split("\n")
    theorems = [l.strip() for l in lines if l.strip().startswith(("theorem ", "lemma "))]
    tactics = []
    for l in lines:
        stripped = l.strip()
        if stripped and not stripped.startswith(("--", "/-", "import", "open", "variable", "section", "end", "namespace", "#")):
            for t in ["simp", "ring", "omega", "norm_num", "linarith", "nlinarith", "exact", "apply", "rw", "rcases", "obtain", "induction", "cases"]:
                if t in stripped:
                    tactics.append(t)
    tactics = list(dict.fromkeys(tactics))

    parts = [f"**Question:** {question}", ""]
    if theorems:
        parts.append("**Theorem statements:**")
        for t in theorems[:5]:
            parts.append(f"- `{t[:200]}`")
        parts.append("")
    if tactics:
        parts.append(f"**Key tactics used:** {', '.join(f'`{t}`' for t in tactics[:10])}")
        parts.append("")
    parts.append(f"The proof is {len(lines)} lines of Lean 4 code. See the attached `proof.lean` for the full formalization.")
    return "\n".join(parts)
