"""Headless Claude invocation for draft generation."""

import subprocess


def generate_reply(
    thread_context: str,
    instructions: str | None = None,
    model: str = "claude-sonnet-4-20250514",
) -> tuple[str, str]:
    """Generate reply draft using headless Claude.

    Returns (draft_body, reasoning).
    """
    prompt = f"""You are drafting an email reply. Be concise and professional.

THREAD CONTEXT:
{thread_context}

{f"INSTRUCTIONS: {instructions}" if instructions else ""}

OUTPUT FORMAT:
First line: Your reasoning (1 sentence)
Then a blank line
Then the reply body (no greeting, no signature - those are added automatically)

Example:
Acknowledging their update and confirming next steps.

Thanks for the update. I'll review the proposal by Friday and get back to you with feedback."""

    result = subprocess.run(
        [
            "claude",
            "--print",
            "--model",
            model,
            "-p",
            prompt,
            "--dangerously-skip-permissions",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode != 0:
        return "", f"Claude failed: {result.stderr}"

    output = result.stdout.strip()
    if not output:
        return "", "No output from Claude"

    parts = output.split("\n\n", 1)
    if len(parts) == 2:
        reasoning, body = parts
    else:
        reasoning = ""
        body = output

    return body.strip(), reasoning.strip()


def generate_signal_reply(
    conversation: list[dict],
    instructions: str | None = None,
    model: str = "claude-sonnet-4-20250514",
) -> tuple[str, str]:
    """Generate Signal reply using headless Claude.

    Returns (reply_text, reasoning).
    """
    context_lines = []
    for msg in conversation[-10:]:
        sender = msg.get("sender_name") or msg.get("sender_phone", "Unknown")
        body = msg.get("body", "")
        context_lines.append(f"{sender}: {body}")

    context = "\n".join(context_lines)

    prompt = f"""You are replying to a Signal message. Be casual and brief.

CONVERSATION:
{context}

{f"INSTRUCTIONS: {instructions}" if instructions else ""}

OUTPUT FORMAT:
First line: Your reasoning (1 sentence)
Then a blank line
Then your reply (1-3 sentences max, casual tone)

Example:
Confirming the time works.

Yeah 3pm works for me, see you then!"""

    result = subprocess.run(
        [
            "claude",
            "--print",
            "--model",
            model,
            "-p",
            prompt,
            "--dangerously-skip-permissions",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode != 0:
        return "", f"Claude failed: {result.stderr}"

    output = result.stdout.strip()
    if not output:
        return "", "No output from Claude"

    parts = output.split("\n\n", 1)
    if len(parts) == 2:
        reasoning, body = parts
    else:
        reasoning = ""
        body = output

    return body.strip(), reasoning.strip()
