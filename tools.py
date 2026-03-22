from __future__ import annotations

import json
import os
import tarfile
import tempfile
import httpx
from config import (
    THEOREM_SEARCH_BASE_URL,
    LEAN_EXPLORE_BASE_URL,
    AXLE_API_KEY,
    AXLE_BASE_URL,
    LEAN_ENVIRONMENT,
    ARISTOTLE_API_KEY,
)


# ---------------------------------------------------------------------------
# TheoremSearch
# ---------------------------------------------------------------------------

async def search_theorems(query: str, n_results: int = 5) -> str:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{THEOREM_SEARCH_BASE_URL}/search",
                json={"query": query, "n_results": n_results},
            )
            if response.status_code != 200:
                return json.dumps({"error": f"TheoremSearch unavailable (HTTP {response.status_code})"})
            data = response.json()
            results = []
            for thm in data.get("theorems", []):
                results.append({
                    "name": thm.get("name", ""),
                    "body": thm.get("body", "")[:500],
                    "slogan": thm.get("slogan", ""),
                    "paper_title": thm.get("paper", {}).get("title", ""),
                    "link": thm.get("link", ""),
                })
            return json.dumps(results, indent=2)
    except Exception as e:
        return json.dumps({"error": f"TheoremSearch error: {e}"})


# ---------------------------------------------------------------------------
# LeanExplore
# ---------------------------------------------------------------------------

async def search_lean_library(query: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{LEAN_EXPLORE_BASE_URL}/search",
                params={"q": query},
            )
            if response.status_code != 200:
                return json.dumps({"error": f"LeanExplore unavailable (HTTP {response.status_code})"})
            data = response.json()
            results = []
            for decl in data.get("results", [])[:10]:
                results.append({
                    "name": decl.get("name", ""),
                    "module": decl.get("module", ""),
                    "source_text": decl.get("source_text", "")[:400],
                    "informalization": decl.get("informalization", "")[:300],
                })
            return json.dumps(results, indent=2)
    except Exception as e:
        return json.dumps({"error": f"LeanExplore error: {e}"})


# ---------------------------------------------------------------------------
# Loogle (type-based Mathlib search)
# ---------------------------------------------------------------------------

async def search_loogle(query: str) -> str:
    """Search Mathlib by type signature pattern via Loogle."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                "https://loogle.lean-lang.org/json",
                params={"q": query},
            )
            if response.status_code != 200:
                return json.dumps({"error": f"Loogle unavailable (HTTP {response.status_code})"})
            data = response.json()
            if "error" in data:
                return json.dumps({"error": data["error"], "suggestions": data.get("suggestions", [])})
            hits = data.get("hits", [])[:10]
            results = []
            for h in hits:
                results.append({
                    "name": h.get("name", ""),
                    "type": h.get("type", ""),
                    "module": h.get("module", ""),
                    "doc": (h.get("doc") or "")[:200],
                })
            return json.dumps({"count": data.get("count", 0), "results": results}, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Loogle error: {e}"})


# ---------------------------------------------------------------------------
# Axle (Lean verification)
# ---------------------------------------------------------------------------

async def check_lean_code(code: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                f"{AXLE_BASE_URL}/check",
                headers={
                    "Authorization": f"Bearer {AXLE_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "content": code,
                    "environment": LEAN_ENVIRONMENT,
                    "timeout_seconds": 120,
                },
            )
            if response.status_code != 200:
                return json.dumps({"error": f"Axle HTTP {response.status_code}: {response.text[:500]}"})
            data = response.json()
            if "user_error" in data:
                return json.dumps({"error": data["user_error"]})
            return json.dumps({
                "okay": data.get("okay", False),
                "errors": data.get("lean_messages", {}).get("errors", []),
                "warnings": data.get("lean_messages", {}).get("warnings", []),
                "tool_errors": data.get("tool_messages", {}).get("errors", []),
                "tool_infos": data.get("tool_messages", {}).get("infos", []),
            }, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Axle error: {e}"})



# ---------------------------------------------------------------------------
# Aristotle (Lean formalization & proving)
# ---------------------------------------------------------------------------

async def submit_to_aristotle(prompt: str) -> str:
    """Submit a prompt to Aristotle. Returns project info JSON."""
    import aristotlelib
    from aristotlelib import Project

    aristotlelib.set_api_key(ARISTOTLE_API_KEY)
    try:
        project = await Project.create(prompt=prompt)
        return json.dumps({
            "project_id": project.project_id,
            "status": project.status.value,
        })
    except Exception as e:
        return json.dumps({"error": f"Aristotle submit error: {e}"})


async def check_aristotle_status(project_id: str) -> dict:
    """Check the status of an Aristotle project. Returns a dict (non-blocking)."""
    import aristotlelib
    from aristotlelib import Project

    aristotlelib.set_api_key(ARISTOTLE_API_KEY)
    try:
        project = await Project.from_id(project_id)
        return {
            "project_id": project.project_id,
            "status": project.status.value,
            "percent_complete": project.percent_complete,
        }
    except Exception as e:
        return {"error": str(e)}


async def get_aristotle_result(project_id: str) -> str:
    """Download and return the Lean code from a completed Aristotle project."""
    import aristotlelib
    from aristotlelib import Project

    aristotlelib.set_api_key(ARISTOTLE_API_KEY)
    try:
        project = await Project.from_id(project_id)
        with tempfile.TemporaryDirectory() as tmpdir:
            result_path = await project.get_solution(
                destination=os.path.join(tmpdir, "result")
            )
            result_path = str(result_path)

            if result_path.endswith(".tar.gz") or result_path.endswith(".tgz"):
                extract_dir = os.path.join(tmpdir, "extracted")
                os.makedirs(extract_dir, exist_ok=True)
                with tarfile.open(result_path) as tar:
                    tar.extractall(extract_dir)

                lean_contents = []
                for root, _dirs, files in os.walk(extract_dir):
                    for f in sorted(files):
                        if f.endswith(".lean"):
                            with open(os.path.join(root, f)) as fh:
                                lean_contents.append(fh.read())

                if not lean_contents:
                    return "No Lean files found in Aristotle result."
                return "\n\n".join(lean_contents)
            else:
                with open(result_path) as f:
                    return f.read()
    except Exception as e:
        return f"Error downloading Aristotle result: {e}"


# ---------------------------------------------------------------------------
# Tool definitions for OpenAI function calling
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "search_theorems",
            "description": (
                "Search for mathematical theorems on arXiv using TheoremSearch. "
                "Returns theorem statements, slogans, and paper references."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language search query about the mathematical topic",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_lean_library",
            "description": (
                "Search Mathlib (Lean 4 math library) for relevant declarations, "
                "theorems, and definitions. Use to find existing Lean names and API."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Search query - a Lean name like 'Nat.add_comm' "
                            "or natural language like 'sum of even numbers is even'"
                        ),
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_loogle",
            "description": (
                "Search Mathlib by TYPE SIGNATURE pattern using Loogle. "
                "Use this to find lemmas by their type shape. Examples:\n"
                "- 'List.map' (by name)\n"
                "- 'Nat -> Nat -> Nat' (by type)\n"
                "- '_ + _ = _ + _' (by pattern)\n"
                "- 'List.map (_ ∘ _) _ = _' (mixed)\n"
                "Returns declaration names, types, and modules."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Loogle query — a name, type pattern, or expression pattern",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_lean_code",
            "description": (
                "Quickly check if Lean 4 code compiles using the Axle verifier (seconds). "
                "Code MUST start with 'import Mathlib'. Use for fast verification."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Complete Lean 4 code. Must start with 'import Mathlib'.",
                    }
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_to_aristotle",
            "description": (
                "Submit a proof request to Aristotle (automated theorem prover). "
                "Aristotle proves graduate/research-level math in Lean 4. "
                "Returns a project_id immediately — use check_aristotle_status or "
                "wait_for_aristotle to get results later.\n\n"
                "PREFERRED FORMAT: Lean 4 code with sorry placeholders. This preserves "
                "the exact theorem signature and lets Aristotle focus on filling proofs:\n"
                "  'Fill in the sorries:\\n```lean\\nimport Mathlib\\n\\ntheorem my_thm ... := by\\n  sorry\\n```'\n\n"
                "ALTERNATIVE FORMATS (when you don't have a Lean statement yet):\n"
                "- Natural language description of the result to prove\n"
                "- Sub-lemmas that the result decomposes into\n\n"
                "SUBMIT MULTIPLE JOBS for different sub-lemmas or strategies.\n"
                "After submitting, continue researching — do NOT wait immediately."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": (
                            "PREFERRED: Lean 4 code with `sorry` in place of proofs. "
                            "ALTERNATIVE: Natural language description of the theorem to prove."
                        ),
                    }
                },
                "required": ["prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_aristotle_status",
            "description": (
                "Non-blocking check of an Aristotle project's status. "
                "Returns status and percent_complete. Use this to poll while "
                "doing other work."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "The project_id from submit_to_aristotle.",
                    }
                },
                "required": ["project_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wait_for_aristotle",
            "description": (
                "Wait for an Aristotle project to complete (polls every 30s, up to 20 min). "
                "Returns the Lean code produced. Only call this when you're ready to "
                "collect results — do other work first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "The project_id from submit_to_aristotle.",
                    }
                },
                "required": ["project_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_aristotle_result",
            "description": (
                "Download the Lean code from a COMPLETED Aristotle project. "
                "Only call after check_aristotle_status shows COMPLETE."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "The project_id of a completed Aristotle project.",
                    }
                },
                "required": ["project_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "final_answer",
            "description": (
                "Submit the final answer to the user. Call this when you have "
                "a complete natural language answer and Lean code."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "answer": {
                        "type": "string",
                        "description": "Clear natural language explanation. Use LaTeX ($...$ and $$...$$) for math.",
                    },
                    "lean_code": {
                        "type": "string",
                        "description": "Complete Lean 4 code (should start with 'import Mathlib').",
                    },
                    "verified": {
                        "type": "boolean",
                        "description": "Whether the Lean code was verified successfully by Axle.",
                    },
                },
                "required": ["answer", "lean_code", "verified"],
            },
        },
    },
]
