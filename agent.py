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
    ARISTOTLE_POLL_INTERVAL,
    ARISTOTLE_MAX_POLLS,
)
from tools import (
    search_theorems,
    search_lean_library,
    search_loogle,
    check_lean_code,
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

### Phase 2: Fast attempt
Write Lean 4 code yourself and verify with **check_lean_code** (Axle — takes seconds).
- The code MUST contain at least one `theorem` or `lemma` declaration.
- If errors: analyze the error, fix, and re-check.
- If the statement seems false: try proving the NEGATION instead.
- Note: the system automatically finalizes when Axle returns okay=true AND the code is sorry-free with theorem/lemma declarations.

### Phase 3: Aristotle + active proving
If Axle verification fails after several attempts:
1. **Submit to Aristotle** — submit the main result as a natural language prompt.
2. **Keep actively trying** — search more declarations, try different proof strategies, verify with check_lean_code.
3. **Periodically check Aristotle** with check_aristotle_status.
4. **If Aristotle returns with sorry**: take the output, identify sorry'd sub-lemmas, submit EACH to Aristotle as a new job. Try to prove them yourself too.
5. **If Aristotle returns sorry-free**: verify with check_lean_code.
6. Keep iterating until all sorries are filled or budget is exhausted.

### Phase 4: Final answer
Call **final_answer** with:
- Clear natural language explanation (with LaTeX math)
- Complete verified Lean 4 code (single file, starts with `import Mathlib`)
- The code MUST declare at least one `theorem` or `lemma`
- Whether verification succeeded

## Key principles
- **NEVER sit idle.** Always be actively trying to prove the result.
- Write ALL Lean code yourself — you are the prover. Aristotle is your backup.
- The code MUST contain `theorem` or `lemma` declarations.
- When Aristotle returns code with sorry, DECOMPOSE and resubmit. Don't give up.
- For false statements, PROVE THE NEGATION.
"""

TERMINAL_STATUSES = {
    "COMPLETE", "COMPLETE_WITH_ERRORS", "FAILED",
    "CANCELED", "OUT_OF_BUDGET",
}

MAX_TOOL_RESULT_CHARS = 3000
MAX_KEEP_RECENT = 30


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
        except Exception as e:
            job.add_status(f"LLM error: {e}")
            job.save()
            await asyncio.sleep(5)  # brief pause before retry
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

            # Handle wait_for_aristotle with polling
            if fn_name == "wait_for_aristotle":
                result = await _poll_aristotle(job, fn_args)
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

            job.messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })
            job.save()

    # Max iterations reached
    if not job.answer and job.best_lean_code:
        job.answer = _generate_fallback_explanation(job.question, job.best_lean_code)
    job.set_phase(JobPhase.COMPLETED if job.best_lean_code else JobPhase.FAILED)
    job.finished_at = time.time()
    job.add_status(f"Max iterations reached. Cost: ${job.total_cost:.4f}")
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
        result = await check_lean_code(fn_args.get("code", ""))
        try:
            parsed = json.loads(result)
            if parsed.get("okay"):
                code = fn_args.get("code", "")
                has_sorry = "sorry" in code
                if has_sorry:
                    job.add_status("Lean code compiles but contains `sorry` — continuing...")
                else:
                    job.add_status("Lean code verified successfully!")
            else:
                n = len(parsed.get("errors", []))
                job.add_status(f"Lean code has {n} error(s)")
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


async def _poll_aristotle(job: JobState, fn_args: dict) -> str:
    project_id = fn_args.get("project_id", "")
    short_id = project_id[:8]
    max_wait_min = (ARISTOTLE_MAX_POLLS * ARISTOTLE_POLL_INTERVAL) // 60
    job.add_status(f"**Waiting for Aristotle** [{short_id}] (timeout: {max_wait_min} min)...")
    job.save()

    for poll_idx in range(ARISTOTLE_MAX_POLLS):
        await asyncio.sleep(ARISTOTLE_POLL_INTERVAL)
        info = await check_aristotle_status(project_id)

        if "error" in info:
            job.add_status(f"Aristotle [{short_id}] error: {info['error']}")
            job.save()
            return json.dumps(info)

        status = info.get("status", "UNKNOWN")
        pct = info.get("percent_complete")
        elapsed = (poll_idx + 1) * ARISTOTLE_POLL_INTERVAL
        elapsed_min = elapsed // 60
        elapsed_sec = elapsed % 60
        pct_str = f" ({pct}%)" if pct is not None else ""
        time_str = f"{elapsed_min}m{elapsed_sec:02d}s" if elapsed_min else f"{elapsed}s"
        job.add_status(f"Aristotle [{short_id}]: {status}{pct_str} — {time_str}")

        # Update aristotle_jobs
        for aj in job.aristotle_jobs:
            if aj.get("project_id") == project_id:
                aj["status"] = status
                aj["percent_complete"] = pct

        job.save()

        if status in TERMINAL_STATUSES:
            if status in ("COMPLETE", "COMPLETE_WITH_ERRORS"):
                job.add_status(f"Aristotle [{short_id}]: downloading result...")
                job.save()
                return await get_aristotle_result(project_id)
            return f"Aristotle project finished with status: {status}"

    job.add_status(f"**Aristotle [{short_id}] timed out** after {max_wait_min} minutes")
    job.save()
    return f"Aristotle [{short_id}] timed out"


async def _maybe_auto_finalize(
    job: JobState, fn_args: dict, result: str, client: AsyncOpenAI
) -> bool:
    """If check_lean_code returned okay + sorry-free + has theorem, auto-finalize. Returns True if finalized."""
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

        job.add_status("Lean code verified (sorry-free)! Finalizing...")
        job.add_log("## Auto-finalize: okay=true, sorry-free, has theorem")

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
