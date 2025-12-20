"""Draft commands: compose, reply, approve, send."""

import typer

from .. import drafts as drafts_module
from .. import policy, services
from .helpers import run_service

app = typer.Typer()


@app.command()
def drafts_list():
    """List pending drafts"""
    pending = drafts_module.list_pending_drafts()
    if not pending:
        typer.echo("No pending drafts")
        return

    for d in pending:
        status = "✓ approved" if d.approved_at else "⧗ pending"
        typer.echo(f"{d.id[:8]} | {d.to_addr} | {d.subject or '(no subject)'} | {status}")


@app.command()
def draft_show(draft_id: str):
    """Show draft details"""
    d = drafts_module.get_draft(draft_id)
    if not d:
        typer.echo(f"Draft {draft_id} not found")
        raise typer.Exit(1)

    typer.echo(f"To: {d.to_addr}")
    if d.cc_addr:
        typer.echo(f"Cc: {d.cc_addr}")
    typer.echo(f"Subject: {d.subject or '(no subject)'}")
    typer.echo(f"\n{d.body}\n")

    if d.claude_reasoning:
        typer.echo(f"--- Claude reasoning ---\n{d.claude_reasoning}")

    typer.echo(f"\nCreated: {d.created_at}")
    if d.approved_at:
        typer.echo(f"Approved: {d.approved_at}")
    if d.sent_at:
        typer.echo(f"Sent: {d.sent_at}")


@app.command()
def compose(
    to: str,
    subject: str = typer.Option(None, "--subject", "-s"),
    body: str = typer.Option(None, "--body", "-b"),
    cc: str = typer.Option(None, "--cc"),
    email: str = typer.Option(None, "--email", "-e"),
):
    """Compose new email draft"""
    if not body:
        typer.echo("Error: --body required")
        raise typer.Exit(1)

    draft_id, from_addr = run_service(
        services.compose_email_draft,
        to_addr=to,
        subject=subject,
        body=body,
        cc_addr=cc,
        email=email,
    )

    typer.echo(f"Created draft {draft_id[:8]}")
    typer.echo(f"From: {from_addr}")
    typer.echo(f"To: {to}")
    if cc:
        typer.echo(f"Cc: {cc}")
    typer.echo(f"Subject: {subject or '(no subject)'}")
    typer.echo(f"\nRun `comms approve {draft_id[:8]}` to approve for sending")


@app.command()
def approve_draft(draft_id: str):
    """Approve draft for sending"""
    full_id = drafts_module.resolve_draft_id(draft_id) or draft_id
    d = drafts_module.get_draft(full_id)
    if not d:
        typer.echo(f"Draft {draft_id} not found")
        raise typer.Exit(1)

    if d.approved_at:
        typer.echo("Draft already approved")
        return

    allowed, msg = policy.check_recipient_allowed(d.to_addr)
    if not allowed:
        typer.echo(f"Cannot approve draft: {msg}")
        raise typer.Exit(1)

    drafts_module.approve_draft(full_id)
    typer.echo(f"Approved draft {full_id[:8]}")
    typer.echo(f"\nRun `comms send {full_id[:8]}` to send")


@app.command()
def reply(
    thread_id: str,
    body: str = typer.Option(None, "--body", "-b"),
    email: str = typer.Option(None, "--email", "-e"),
):
    """Reply to thread"""
    if not body:
        typer.echo("Error: --body required")
        raise typer.Exit(1)

    draft_id, original_from, reply_subject = run_service(
        services.reply_to_thread, thread_id=thread_id, body=body, email=email
    )

    typer.echo(f"Created reply draft {draft_id[:8]}")
    typer.echo(f"To: {original_from}")
    typer.echo(f"Subject: {reply_subject}")
    typer.echo(f"\nRun `comms approve {draft_id[:8]}` to approve for sending")


@app.command()
def draft_reply(
    thread_id: str,
    instructions: str = typer.Option(None, "--instructions", "-i", help="Instructions for Claude"),
    email: str = typer.Option(None, "--email", "-e"),
):
    """Generate reply draft using Claude"""
    from .. import claude

    full_id = run_service(services.resolve_thread_id, thread_id, email) or thread_id
    messages = run_service(services.fetch_thread, full_id, email)

    context_lines = []
    for msg in messages[-5:]:
        context_lines.append(f"From: {msg['from']}")
        context_lines.append(f"Date: {msg['date']}")
        context_lines.append(f"Body: {msg['body'][:500]}")
        context_lines.append("---")

    context = "\n".join(context_lines)

    typer.echo("Generating draft...")
    body, reasoning = claude.generate_reply(context, instructions)

    if not body:
        typer.echo(f"Failed: {reasoning}")
        raise typer.Exit(1)

    draft_id, original_from, reply_subject = run_service(
        services.reply_to_thread, thread_id=full_id, body=body, email=email
    )

    typer.echo(f"\nReasoning: {reasoning}")
    typer.echo(f"\nDraft {draft_id[:8]}:")
    typer.echo(f"To: {original_from}")
    typer.echo(f"Subject: {reply_subject}")
    typer.echo(f"\n{body}\n")
    typer.echo(f"Run `comms approve {draft_id[:8]}` to approve")


@app.command()
def send(draft_id: str):
    """Send approved draft"""
    full_id = drafts_module.resolve_draft_id(draft_id) or draft_id
    d = drafts_module.get_draft(full_id)
    if not d:
        typer.echo(f"Draft {draft_id} not found")
        raise typer.Exit(1)

    run_service(services.send_draft, full_id)
    typer.echo(f"Sent: {d.to_addr}")
    typer.echo(f"Subject: {d.subject}")
