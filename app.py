import traceback
import gradio as gr
from agent import run_agent, format_final_response
from email_sender import send_result_email


EXAMPLES = [
    ["Prove that the sum of two even numbers is even."],
    ["Is the square root of 2 irrational?"],
    ["Prove that there are infinitely many prime numbers."],
    ["Show that for all natural numbers n, n + 0 = n."],
    ["Prove that the composition of two injective functions is injective."],
]

LATEX_DELIMITERS = [
    {"left": "$$", "right": "$$", "display": True},
    {"left": "$", "right": "$", "display": False},
]


async def respond(message, history, email):
    """Handle a user message. Streams progress, then delivers final answer."""
    if not message or not message.strip():
        yield "Please enter a mathematical question."
        return

    try:
        status_text = ""
        final_result = None

        async for status, result in run_agent(message):
            status_text = status
            if result is not None:
                final_result = result
            yield status_text

        formatted = format_final_response(status_text, final_result)
        yield formatted

        # Send email if provided
        if email and email.strip() and "@" in email:
            answer = final_result.get("answer", "") if final_result else ""
            lean_code = final_result.get("lean_code", "") if final_result else ""
            verified = final_result.get("verified", False) if final_result else False
            sent = send_result_email(
                to_email=email.strip(),
                question=message,
                status_log=status_text,
                answer=answer,
                lean_code=lean_code,
                verified=verified,
            )
            if sent:
                yield formatted + "\n\n---\n*Results sent to " + email.strip() + "*"

    except Exception as e:
        tb = traceback.format_exc()
        yield f"An error occurred:\n```\n{tb}\n```"


demo = gr.ChatInterface(
    fn=respond,
    title="VeriDeepResearch",
    description=(
        "Ask a mathematical question and get a verified answer. "
        "The answer is formalized in Lean 4 and checked by a proof verifier. "
        "Optionally enter your email to be notified when long-running proofs complete."
    ),
    examples=EXAMPLES,
    additional_inputs=[
        gr.Textbox(
            label="Email (optional)",
            placeholder="your@email.com — get notified when done",
            type="email",
        ),
    ],
    chatbot=gr.Chatbot(
        height=600,
        latex_delimiters=LATEX_DELIMITERS,
    ),
)


if __name__ == "__main__":
    demo.launch()
