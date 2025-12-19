import typer

from . import audit, db, drafts, policy

app = typer.Typer(
    name="comms",
    help="AI-managed comms for ADHD brains",
    no_args_is_help=False,
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def _dashboard(ctx: typer.Context):
    """Show dashboard: unread threads, pending drafts, the damage"""
    if ctx.invoked_subcommand is None:
        with db.get_db() as conn:
            unread_count = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE status = 'unread'"
            ).fetchone()[0]
            pending_drafts = conn.execute(
                "SELECT COUNT(*) FROM drafts WHERE approved_at IS NULL AND sent_at IS NULL"
            ).fetchone()[0]
            approved_unsent = conn.execute(
                "SELECT COUNT(*) FROM drafts WHERE approved_at IS NOT NULL AND sent_at IS NULL"
            ).fetchone()[0]

        typer.echo("Comms Dashboard\n")
        typer.echo(f"Unread messages: {unread_count}")
        typer.echo(f"Pending drafts: {pending_drafts}")
        typer.echo(f"Approved (unsent): {approved_unsent}")


@app.command()
def init():
    """Initialize comms database and config"""
    db.init()
    typer.echo("Initialized comms database")


@app.command()
def status():
    """Show system status"""
    from .config import get_policy

    pol = get_policy()
    typer.echo("Policy:")
    typer.echo(f"  Require approval: {pol.get('require_approval', True)}")
    typer.echo(f"  Max daily sends: {pol.get('max_daily_sends', 50)}")
    typer.echo(f"  Allowed recipients: {len(pol.get('allowed_recipients', []))}")
    typer.echo(f"  Allowed domains: {len(pol.get('allowed_domains', []))}")


@app.command()
def drafts_list():
    """List pending drafts"""
    pending = drafts.list_pending_drafts()
    if not pending:
        typer.echo("No pending drafts")
        return

    for d in pending:
        status = "✓ approved" if d.approved_at else "⧗ pending"
        typer.echo(f"{d.id[:8]} | {d.to_addr} | {d.subject or '(no subject)'} | {status}")


@app.command()
def draft_show(draft_id: str):
    """Show draft details"""
    d = drafts.get_draft(draft_id)
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
def approve(draft_id: str):
    """Approve draft for sending"""
    d = drafts.get_draft(draft_id)
    if not d:
        typer.echo(f"Draft {draft_id} not found")
        raise typer.Exit(1)

    if d.approved_at:
        typer.echo("Draft already approved")
        return

    allowed, errors = policy.validate_send(draft_id, d.to_addr)
    if not allowed:
        typer.echo("Cannot approve draft:")
        for err in errors:
            typer.echo(f"  - {err}")
        raise typer.Exit(1)

    drafts.approve_draft(draft_id)
    typer.echo(f"Approved draft {draft_id[:8]}")


@app.command()
def audit_log(limit: int = 20):
    """Show recent audit log"""
    logs = audit.get_recent_logs(limit)
    for log_entry in logs:
        typer.echo(
            f"{log_entry['timestamp']} | {log_entry['action']} | {log_entry['entity_type']}:{log_entry['entity_id'][:8]}"
        )


def main():
    db.init()
    app()


if __name__ == "__main__":
    main()
