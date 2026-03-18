from __future__ import annotations

import asyncio
import json
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
    generate_lean_proof,
    submit_to_aristotle,
    check_aristotle_status,
    get_aristotle_result,
    TOOL_DEFINITIONS,
)

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
3. PROVE THE NEGATION in Lean 4. For example, if asked "Prove that all primes are odd", prove `∃ p, Nat.Prime p ∧ Even p` (namely p=2).
4. Verify the negation proof with check_lean_code.
5. Call final_answer with the negation proof as lean_code and verified=true (if the negation was verified).
Do NOT just refuse — always try to prove the negation. This is the most valuable thing you can do for a false statement.

## Workflow

### Phase 1: Research
1. Search for relevant theorems with **search_theorems** (arXiv, natural language).
2. Search Mathlib with **search_lean_library** (by name or natural language).
3. Search Mathlib by type pattern with **search_loogle** (e.g. "_ + _ = _ + _", "Nat → Nat → Prop").

### Phase 2: Fast attempt (try this first)
Try to prove the result using one or more of:
- Write Lean 4 code yourself and verify with **check_lean_code** (Axle — takes seconds).
- Use **generate_lean_proof** to have Qwen 3.5 write the proof, then verify with check_lean_code.
- **CRITICAL: If check_lean_code returns okay=true, IMMEDIATELY call final_answer. Do not wait for Aristotle or do any more work.**
- If errors: try to fix and re-check. Alternate between writing code yourself and using generate_lean_proof.
- If the statement seems false: try proving the NEGATION instead.

### Phase 3: Aristotle + active proving (if fast attempt fails)
If Axle verification fails after several attempts:
1. **Submit to Aristotle** — decompose into main result + sub-lemmas, submit ALL.
2. **DO NOT WAIT for Aristotle.** Instead, keep actively trying to close the proof yourself:
   - Use **generate_lean_proof** (Qwen 3.5) with different prompts and hints.
   - Search for more Mathlib declarations with search_lean_library and search_loogle.
   - Write Lean code yourself with different proof strategies.
   - Verify each attempt with check_lean_code.
   - **If ANY attempt verifies (okay=true), IMMEDIATELY call final_answer. Do not wait for Aristotle.**
3. **Periodically check Aristotle** with check_aristotle_status — but only between your own proof attempts, never as the primary activity.
4. If Aristotle completes, download with get_aristotle_result and verify with check_lean_code.
5. The goal is to RACE: you and Qwen try to prove it while Aristotle also works on it. Whoever finishes first wins.

### Phase 4: Final answer
Call **final_answer** with:
- Clear natural language explanation (with LaTeX math)
- Complete verified Lean 4 code (single file, starts with `import Mathlib`)
- Whether verification succeeded

## Key principles
- **NEVER sit idle.** Always be actively trying to prove the result.
- If check_lean_code says okay=true, IMMEDIATELY call final_answer. This is the highest priority.
- Use BOTH your own code AND generate_lean_proof (Qwen 3.5) — try different approaches.
- Submit to Aristotle early, but don't wait for it — keep proving.
- Race: you + Qwen vs Aristotle. First verified proof wins.
- For false statements, PROVE THE NEGATION — don't just refuse.
"""


class CostTracker:
    def __init__(self, max_cost: float = MAX_COST_PER_QUERY):
        self.total_cost = 0.0
        self.max_cost = max_cost
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def add(self, usage) -> float:
        input_t = usage.prompt_tokens or 0
        output_t = usage.completion_tokens or 0
        self.total_input_tokens += input_t
        self.total_output_tokens += output_t
        cost = input_t * INPUT_COST_PER_TOKEN + output_t * OUTPUT_COST_PER_TOKEN
        self.total_cost += cost
        return cost

    @property
    def over_budget(self) -> bool:
        return self.total_cost >= self.max_cost

    def summary(self) -> str:
        return f"${self.total_cost:.4f} ({self.total_input_tokens} in / {self.total_output_tokens} out)"


TERMINAL_STATUSES = {
    "COMPLETE", "COMPLETE_WITH_ERRORS", "FAILED",
    "CANCELED", "OUT_OF_BUDGET",
}


async def run_agent(question: str):
    """Run the VeriDeepResearch agent.

    Yields (display_text, final_result_or_none) tuples.
    """
    client = AsyncOpenAI(
        base_url=TOKEN_FACTORY_BASE_URL,
        api_key=TOKEN_FACTORY_API_KEY,
    )
    cost_tracker = CostTracker()
    status_log: list[str] = []

    def add_status(msg: str):
        status_log.append(msg)

    def render_status():
        return "\n".join(f"- {s}" for s in status_log)

    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]

    add_status("Analyzing your question...")
    yield render_status(), None

    for _iteration in range(MAX_AGENT_ITERATIONS):
        if cost_tracker.over_budget:
            add_status(f"Budget limit reached ({cost_tracker.summary()}).")
            yield render_status(), None
            break

        try:
            response = await client.chat.completions.create(
                model=KIMI_MODEL,
                messages=messages,
                tools=TOOL_DEFINITIONS,
                temperature=0.6,
                max_tokens=16384,
            )
        except Exception as e:
            add_status(f"LLM error: {e}")
            yield render_status(), None
            return

        if response.usage:
            cost_tracker.add(response.usage)

        choice = response.choices[0]
        assistant_msg = choice.message

        # Append assistant message to history
        msg_dict: dict = {"role": "assistant", "content": assistant_msg.content or ""}
        if assistant_msg.tool_calls:
            msg_dict["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in assistant_msg.tool_calls
            ]
        messages.append(msg_dict)

        if not assistant_msg.tool_calls:
            add_status("Thinking...")
            yield render_status(), None
            continue

        for tool_call in assistant_msg.tool_calls:
            fn_name = tool_call.function.name
            try:
                fn_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                fn_args = {}

            result = await _handle_tool_call(
                fn_name, fn_args, add_status, render_status,
                # Pass the yield-like callback for streaming status updates
            )

            # final_answer terminates the loop
            if fn_name == "final_answer":
                add_status("Research complete!")
                yield render_status(), fn_args
                return

            yield render_status(), None

            # For wait_for_aristotle, we need special handling with polling
            if fn_name == "wait_for_aristotle":
                project_id = fn_args.get("project_id", "")
                short_id = project_id[:8]
                max_wait_min = (ARISTOTLE_MAX_POLLS * ARISTOTLE_POLL_INTERVAL) // 60
                add_status(f"**Waiting for Aristotle** [{short_id}] (timeout: {max_wait_min} min, polling every {ARISTOTLE_POLL_INTERVAL}s)...")
                yield render_status(), None

                poll_result = None
                for poll_idx in range(ARISTOTLE_MAX_POLLS):
                    await asyncio.sleep(ARISTOTLE_POLL_INTERVAL)
                    info = await check_aristotle_status(project_id)

                    if "error" in info:
                        poll_result = json.dumps(info)
                        add_status(f"Aristotle [{short_id}] error: {info['error']}")
                        yield render_status(), None
                        break

                    status = info.get("status", "UNKNOWN")
                    pct = info.get("percent_complete")
                    elapsed = (poll_idx + 1) * ARISTOTLE_POLL_INTERVAL
                    elapsed_min = elapsed // 60
                    elapsed_sec = elapsed % 60
                    pct_str = f" ({pct}%)" if pct is not None else ""
                    time_str = f"{elapsed_min}m{elapsed_sec:02d}s" if elapsed_min else f"{elapsed}s"
                    add_status(f"Aristotle [{short_id}]: {status}{pct_str} — {time_str} elapsed")
                    yield render_status(), None

                    if status in TERMINAL_STATUSES:
                        if status in ("COMPLETE", "COMPLETE_WITH_ERRORS"):
                            add_status(f"Aristotle [{short_id}]: downloading result...")
                            yield render_status(), None
                            poll_result = await get_aristotle_result(project_id)
                        else:
                            poll_result = f"Aristotle project finished with status: {status}"
                        break

                if poll_result is None:
                    total_wait = ARISTOTLE_MAX_POLLS * ARISTOTLE_POLL_INTERVAL
                    poll_result = f"Aristotle [{short_id}] timed out after {total_wait // 60} minutes"
                    add_status(f"**Aristotle [{short_id}] timed out** after {total_wait // 60} minutes")
                    yield render_status(), None

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": poll_result,
                })
            else:
                # Regular tool — result was already computed
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })

    add_status(f"Reached max iterations. Cost: {cost_tracker.summary()}")
    yield render_status(), None


async def _handle_tool_call(fn_name: str, fn_args: dict,
                            add_status, render_status) -> str:
    """Execute a non-blocking tool call. Returns the result string.

    wait_for_aristotle is handled separately in the main loop (needs polling).
    """
    if fn_name == "final_answer":
        return json.dumps(fn_args)

    if fn_name == "search_theorems":
        query = fn_args.get("query", "")
        add_status(f'Searching for theorems: "{query}"...')
        return await search_theorems(query)

    if fn_name == "search_lean_library":
        query = fn_args.get("query", "")
        add_status(f'Searching Mathlib: "{query}"...')
        return await search_lean_library(query)

    if fn_name == "search_loogle":
        query = fn_args.get("query", "")
        add_status(f'Searching Loogle: "{query}"...')
        return await search_loogle(query)

    if fn_name == "generate_lean_proof":
        statement = fn_args.get("statement", "")
        short_stmt = statement[:80].replace("\n", " ")
        add_status(f'Generating proof with Qwen 3.5: "{short_stmt}"...')
        result = await generate_lean_proof(statement, fn_args.get("context", ""))
        add_status(f"Qwen 3.5 generated {len(result)} chars of Lean code")
        return result

    if fn_name == "check_lean_code":
        add_status("Verifying Lean code with Axle...")
        result = await check_lean_code(fn_args.get("code", ""))
        try:
            parsed = json.loads(result)
            if parsed.get("okay"):
                add_status("Lean code verified successfully!")
            else:
                n = len(parsed.get("errors", []))
                add_status(f"Lean code has {n} error(s)")
        except json.JSONDecodeError:
            pass
        return result

    if fn_name == "submit_to_aristotle":
        prompt = fn_args.get("prompt", "")
        # Show a clear summary of what was submitted
        prompt_preview = prompt[:120].replace("\n", " ").strip()
        if len(prompt) > 120:
            prompt_preview += "..."
        add_status(f'**Submitted to Aristotle:** "{prompt_preview}"')
        result = await submit_to_aristotle(prompt)
        try:
            parsed = json.loads(result)
            pid = parsed.get("project_id", "")
            if pid:
                add_status(f"Aristotle job **{pid[:8]}** queued (may take 1-30 min)")
            elif "error" in parsed:
                add_status(f"Aristotle error: {parsed['error']}")
        except json.JSONDecodeError:
            pass
        return result

    if fn_name == "check_aristotle_status":
        project_id = fn_args.get("project_id", "")
        info = await check_aristotle_status(project_id)
        status = info.get("status", "UNKNOWN")
        pct = info.get("percent_complete")
        pct_str = f" ({pct}%)" if pct is not None else ""
        add_status(f"Aristotle [{project_id[:8]}]: {status}{pct_str}")
        return json.dumps(info)

    if fn_name == "get_aristotle_result":
        project_id = fn_args.get("project_id", "")
        add_status(f"Downloading Aristotle result [{project_id[:8]}]...")
        return await get_aristotle_result(project_id)

    if fn_name == "wait_for_aristotle":
        # Handled specially in the main loop; return placeholder here
        return ""

    return json.dumps({"error": f"Unknown tool: {fn_name}"})


def format_final_response(status_text: str, result: dict | None) -> str:
    """Format the final response with natural language answer and expandable Lean code."""
    if result is None:
        return (
            status_text
            + "\n\nI was unable to complete the research. "
            "Please try rephrasing your question or asking something simpler."
        )

    answer = result.get("answer", "No answer provided.")
    lean_code = result.get("lean_code", "")
    verified = result.get("verified", False)

    parts = []

    # Status log (collapsed)
    parts.append(
        f"<details>\n<summary>Research log</summary>\n\n{status_text}\n\n</details>\n"
    )

    # Main answer
    parts.append(answer)

    # Lean code section
    if lean_code.strip():
        badge = "Verified" if verified else "Unverified"
        icon = "&#x2705;" if verified else "&#x26A0;&#xFE0F;"
        parts.append(
            f"\n\n<details open>\n<summary>{icon} Lean 4 Code ({badge})</summary>"
            f"\n\n```lean4\n{lean_code}\n```\n\n</details>"
        )

    return "\n\n".join(parts)
