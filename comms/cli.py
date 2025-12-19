import typer

from . import accounts as accts_module
from . import audit, db, drafts, policy
from .adapters.email import gmail, outlook, proton

app = typer.Typer(
    name="comms",
    help="AI-managed comms for ADHD brains",
    no_args_is_help=False,
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def _dashboard(ctx: typer.Context):
    """Show dashboard"""
    if ctx.invoked_subcommand is None:
        accounts = accts_module.list_accounts("email")
        total_inbox = 0

        for account in accounts:
            if account["provider"] == "gmail":
                count = gmail.count_inbox_threads(account["email"])
                total_inbox += count

        with db.get_db() as conn:
            pending_drafts = conn.execute(
                "SELECT COUNT(*) FROM drafts WHERE approved_at IS NULL AND sent_at IS NULL"
            ).fetchone()[0]
            approved_unsent = conn.execute(
                "SELECT COUNT(*) FROM drafts WHERE approved_at IS NOT NULL AND sent_at IS NULL"
            ).fetchone()[0]

        typer.echo("Comms Dashboard\n")
        typer.echo(f"Inbox threads: {total_inbox}")
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


@app.command()
def link(
    provider: str = typer.Argument(..., help="Provider: proton, gmail, outlook"),
    email: str = typer.Argument(
        None, help="Email (required for proton/outlook, auto-detected for gmail)"
    ),
    password: str = typer.Option(
        None, "--password", "-p", help="Password (Proton Bridge password)"
    ),
    client_id: str = typer.Option(None, "--client-id", help="OAuth Client ID (Outlook)"),
    client_secret: str = typer.Option(
        None, "--client-secret", help="OAuth Client Secret (Outlook)"
    ),
):
    """Link email account"""
    if provider not in ["proton", "gmail", "outlook"]:
        typer.echo(f"Unknown provider: {provider}")
        raise typer.Exit(1)

    if provider == "gmail":
        try:
            email = gmail.init_oauth()
            typer.echo(f"OAuth completed: {email}")
        except Exception as e:
            typer.echo(f"OAuth failed: {e}")
            raise typer.Exit(1) from None

        account_id = accts_module.add_email_account(provider, email)
        success, msg = gmail.test_connection(account_id, email)
        if not success:
            typer.echo(f"Failed to connect: {msg}")
            raise typer.Exit(1)

    elif provider == "proton":
        if not email:
            typer.echo("Proton requires email address")
            raise typer.Exit(1)

        if not password:
            password = typer.prompt("Proton Bridge Password", hide_input=True)

        account_id = accts_module.add_email_account(provider, email)
        proton.store_credentials(email, password)
        success, msg = proton.test_connection(account_id, email)
        if not success:
            typer.echo(f"Failed to connect: {msg}")
            raise typer.Exit(1)

    elif provider == "outlook":
        if not email:
            typer.echo("Outlook requires email address")
            raise typer.Exit(1)

        if not client_id or not client_secret:
            typer.echo("Outlook requires --client-id and --client-secret")
            typer.echo(
                "Get them from: https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps"
            )
            raise typer.Exit(1)

        account_id = accts_module.add_email_account(provider, email)
        outlook.store_credentials(email, client_id, client_secret)
        success, msg = outlook.test_connection(account_id, email, client_id, client_secret)
        if not success:
            typer.echo(f"Failed to connect: {msg}")
            raise typer.Exit(1)

    typer.echo(f"Linked {provider}: {email}")
    typer.echo(f"Account ID: {account_id}")


@app.command()
def accounts():
    """List all accounts"""
    accts = accts_module.list_accounts()
    if not accts:
        typer.echo("No accounts configured")
        return

    for acct in accts:
        status = "✓" if acct["enabled"] else "✗"
        typer.echo(f"{status} {acct['provider']:10} {acct['email']:30} {acct['id'][:8]}")


@app.command()
def unlink(account_id: str):
    """Unlink account by ID or email"""
    accts = accts_module.list_accounts()
    matching = [a for a in accts if a["id"].startswith(account_id) or a["email"] == account_id]

    if not matching:
        typer.echo(f"No account found matching: {account_id}")
        raise typer.Exit(1)

    if len(matching) > 1:
        typer.echo(f"Multiple accounts match '{account_id}':")
        for acct in matching:
            typer.echo(f"  {acct['id'][:8]} {acct['provider']} {acct['email']}")
        raise typer.Exit(1)

    acct = matching[0]
    if accts_module.remove_account(acct["id"]):
        typer.echo(f"Unlinked {acct['provider']}: {acct['email']}")
    else:
        typer.echo("Failed to unlink account")
        raise typer.Exit(1)


@app.command()
def threads():
    """List inbox threads from all accounts"""
    accounts = accts_module.list_accounts("email")

    for account in accounts:
        if account["provider"] == "gmail":
            typer.echo(f"\n{account['email']}:")
            threads = gmail.list_inbox_threads(account["email"])

            if not threads:
                typer.echo("  No threads")
                continue

            for t in threads:
                typer.echo(f"  {t['id'][:8]} | {t['snippet'][:60]}")


@app.command()
def thread(thread_id: str, email: str = typer.Option(None, "--email", "-e")):
    """Fetch and display full thread"""
    if not email:
        accounts = accts_module.list_accounts("email")
        if len(accounts) == 1:
            email = accounts[0]["email"]
        else:
            typer.echo("Multiple accounts found. Specify --email")
            raise typer.Exit(1)

    messages = gmail.fetch_thread_messages(thread_id, email)

    if not messages:
        typer.echo(f"Thread not found: {thread_id}")
        raise typer.Exit(1)

    typer.echo(f"\nThread: {messages[0]['subject']}")
    typer.echo("=" * 80)

    for msg in messages:
        typer.echo(f"\nFrom: {msg['from']}")
        typer.echo(f"Date: {msg['date']}")
        typer.echo(f"\n{msg['body']}\n")
        typer.echo("-" * 80)


@app.command()
def archive(thread_id: str, email: str = typer.Option(None, "--email", "-e")):
    """Archive thread (remove from inbox)"""
    if not email:
        accounts = accts_module.list_accounts("email")
        if len(accounts) == 1:
            email = accounts[0]["email"]
        else:
            typer.echo("Multiple accounts found. Specify --email")
            raise typer.Exit(1)

    success = gmail.archive_thread(thread_id, email)

    if success:
        typer.echo(f"Archived thread: {thread_id}")
        audit.log("archive", "thread", thread_id, {"reason": "manual"})
    else:
        typer.echo("Failed to archive thread")
        raise typer.Exit(1)


@app.command()
def delete(thread_id: str, email: str = typer.Option(None, "--email", "-e")):
    """Delete thread (move to trash)"""
    if not email:
        accounts = accts_module.list_accounts("email")
        if len(accounts) == 1:
            email = accounts[0]["email"]
        else:
            typer.echo("Multiple accounts found. Specify --email")
            raise typer.Exit(1)

    success = gmail.delete_thread(thread_id, email)

    if success:
        typer.echo(f"Deleted thread: {thread_id}")
        audit.log("delete", "thread", thread_id, {"reason": "manual"})
    else:
        typer.echo("Failed to delete thread")
        raise typer.Exit(1)


@app.command()
def flag(thread_id: str, email: str = typer.Option(None, "--email", "-e")):
    """Flag thread (star it)"""
    _thread_action(thread_id, "flag", gmail.flag_thread, email)


@app.command()
def unflag(thread_id: str, email: str = typer.Option(None, "--email", "-e")):
    """Unflag thread (unstar it)"""
    _thread_action(thread_id, "unflag", gmail.unflag_thread, email)


@app.command()
def unarchive(thread_id: str, email: str = typer.Option(None, "--email", "-e")):
    """Unarchive thread (restore to inbox)"""
    _thread_action(thread_id, "unarchive", gmail.unarchive_thread, email)


@app.command()
def undelete(thread_id: str, email: str = typer.Option(None, "--email", "-e")):
    """Undelete thread (restore from trash)"""
    _thread_action(thread_id, "undelete", gmail.undelete_thread, email)


def _thread_action(thread_id: str, action_name: str, action_fn, email: str = None):
    """Helper to execute thread actions with audit logging"""
    if not email:
        accounts = accts_module.list_accounts("email")
        if len(accounts) == 1:
            email = accounts[0]["email"]
        else:
            typer.echo("Multiple accounts found. Specify --email")
            raise typer.Exit(1)

    success = action_fn(thread_id, email)

    if success:
        past_tense = f"{action_name}ged" if action_name.endswith("flag") else f"{action_name}d"
        typer.echo(f"{past_tense.capitalize()} thread: {thread_id}")
        audit.log(action_name, "thread", thread_id, {"reason": "manual"})
    else:
        typer.echo(f"Failed to {action_name} thread")
        raise typer.Exit(1)


def main():
    db.init()
    app()


if __name__ == "__main__":
    main()
