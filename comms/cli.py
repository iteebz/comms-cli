import typer

from . import accounts as accts_module
from . import audit, db, drafts, policy, proposals
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

    if not email:
        accounts = accts_module.list_accounts("email")
        if len(accounts) == 1:
            email = accounts[0]["email"]
        else:
            typer.echo("Multiple accounts found. Specify --email")
            raise typer.Exit(1)

    account = None
    for acc in accts_module.list_accounts("email"):
        if acc["email"] == email:
            account = acc
            break

    if not account:
        typer.echo(f"Account not found: {email}")
        raise typer.Exit(1)

    draft_id = drafts.create_draft(
        to_addr=to,
        subject=subject or "(no subject)",
        body=body,
        cc_addr=cc,
        from_account_id=account["id"],
        from_addr=email,
    )

    typer.echo(f"Created draft {draft_id[:8]}")
    typer.echo(f"From: {email}")
    typer.echo(f"To: {to}")
    if cc:
        typer.echo(f"Cc: {cc}")
    typer.echo(f"Subject: {subject or '(no subject)'}")
    typer.echo(f"\nRun `comms approve {draft_id[:8]}` to approve for sending")


def _resolve_draft_id(draft_id_prefix: str) -> str | None:
    with db.get_db() as conn:
        rows = conn.execute(
            "SELECT id FROM drafts WHERE id LIKE ? ORDER BY created_at DESC",
            (f"{draft_id_prefix}%",),
        ).fetchall()

        if len(rows) == 0:
            return None
        if len(rows) == 1:
            return rows[0]["id"]
        return None


@app.command()
def approve_draft(draft_id: str):
    """Approve draft for sending"""
    full_id = _resolve_draft_id(draft_id) or draft_id
    d = drafts.get_draft(full_id)
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

    drafts.approve_draft(full_id)
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

    account = None
    for acc in accts_module.list_accounts("email"):
        if acc["email"] == email:
            account = acc
            break

    if not account:
        typer.echo(f"Account not found: {email}")
        raise typer.Exit(1)

    original_subject = messages[0]["subject"]
    reply_subject = (
        original_subject if original_subject.startswith("Re: ") else f"Re: {original_subject}"
    )

    original_from = messages[-1]["from"]

    draft_id = drafts.create_draft(
        to_addr=original_from,
        subject=reply_subject,
        body=body,
        thread_id=thread_id,
        from_account_id=account["id"],
        from_addr=email,
    )

    typer.echo(f"Created reply draft {draft_id[:8]}")
    typer.echo(f"To: {original_from}")
    typer.echo(f"Subject: {reply_subject}")
    typer.echo(f"\nRun `comms approve {draft_id[:8]}` to approve for sending")


@app.command()
def send(draft_id: str):
    """Send approved draft"""
    full_id = _resolve_draft_id(draft_id) or draft_id
    d = drafts.get_draft(full_id)
    if not d:
        typer.echo(f"Draft {draft_id} not found")
        raise typer.Exit(1)

    if not d.approved_at:
        typer.echo("Draft not approved. Run `comms approve` first.")
        raise typer.Exit(1)

    if d.sent_at:
        typer.echo("Draft already sent")
        return

    if not d.from_account_id or not d.from_addr:
        typer.echo("Draft missing source account info")
        raise typer.Exit(1)

    account = accts_module.get_account_by_id(d.from_account_id)
    if not account:
        typer.echo(f"Account not found: {d.from_account_id}")
        raise typer.Exit(1)

    email = d.from_addr

    if account["provider"] == "gmail":
        success = gmail.send_message(account["id"], email, d)
    else:
        typer.echo(f"Provider {account['provider']} not yet implemented")
        raise typer.Exit(1)

    if success:
        drafts.mark_sent(full_id)
        typer.echo(f"Sent: {d.to_addr}")
        typer.echo(f"Subject: {d.subject}")
    else:
        typer.echo("Failed to send")
        raise typer.Exit(1)


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


@app.command()
def review(status: str = typer.Option(None, "--status", "-s")):
    """Review proposals"""
    props = proposals.list_proposals(status=status)

    if not props:
        typer.echo("No proposals")
        return

    for p in props:
        status_icon = {"pending": "⧗", "approved": "✓", "rejected": "✗", "executed": "✓✓"}.get(
            p["status"], "?"
        )
        typer.echo(
            f"{status_icon} {p['id'][:8]} | {p['proposed_action']:10} {p['entity_type']:8} {p['entity_id'][:8]}"
        )
        if p["agent_reasoning"]:
            typer.echo(f"   agent: {p['agent_reasoning']}")
        if p["user_reasoning"]:
            typer.echo(f"   user:  {p['user_reasoning']}")


@app.command()
def propose(
    action: str,
    entity_type: str,
    entity_id: str,
    agent: str = typer.Option(None, "--agent", help="Agent reasoning"),
):
    """Create proposal"""
    proposal_id = proposals.create_proposal(
        entity_type=entity_type,
        entity_id=entity_id,
        proposed_action=action,
        agent_reasoning=agent,
    )
    typer.echo(f"Created proposal {proposal_id[:8]}")


@app.command()
def approve(
    proposal_id: str,
    human: str = typer.Option(None, "--human", help="Human reasoning for approval"),
):
    """Approve proposal"""
    if proposals.approve_proposal(proposal_id, user_reasoning=human):
        typer.echo(f"Approved {proposal_id[:8]}")
    else:
        typer.echo("Failed to approve (not found or already processed)")
        raise typer.Exit(1)


@app.command()
def reject(
    proposal_id: str,
    human: str = typer.Option(None, "--human", help="Human reasoning for rejection"),
):
    """Reject proposal"""
    if proposals.reject_proposal(proposal_id, user_reasoning=human):
        typer.echo(f"Rejected {proposal_id[:8]}")
    else:
        typer.echo("Failed to reject (not found or already processed)")
        raise typer.Exit(1)


@app.command()
def resolve():
    """Execute all approved proposals"""
    approved = proposals.get_approved_proposals()

    if not approved:
        typer.echo("No approved proposals to execute")
        return

    executed_count = 0
    failed_count = 0

    for p in approved:
        action = p["proposed_action"]
        entity_type = p["entity_type"]
        entity_id = p["entity_id"]

        typer.echo(f"Executing: {action} {entity_type} {entity_id[:8]}")

        try:
            if entity_type == "thread":
                account = accts_module.list_accounts("email")[0]
                email = account["email"]

                if action == "archive":
                    success = gmail.archive_thread(entity_id, email)
                elif action == "delete":
                    success = gmail.delete_thread(entity_id, email)
                elif action == "flag":
                    success = gmail.flag_thread(entity_id, email)
                elif action == "unflag":
                    success = gmail.unflag_thread(entity_id, email)
                elif action == "unarchive":
                    success = gmail.unarchive_thread(entity_id, email)
                elif action == "undelete":
                    success = gmail.undelete_thread(entity_id, email)
                else:
                    typer.echo(f"  Unknown action: {action}")
                    failed_count += 1
                    continue

                if success:
                    proposals.mark_executed(p["id"])
                    executed_count += 1
                    typer.echo(f"  ✓ {action} completed")
                else:
                    typer.echo(f"  ✗ {action} failed")
                    failed_count += 1
            else:
                typer.echo(f"  Unknown entity type: {entity_type}")
                failed_count += 1

        except Exception as e:
            typer.echo(f"  ✗ Error: {e}")
            failed_count += 1

    typer.echo(f"\nExecuted: {executed_count}, Failed: {failed_count}")


def main():
    db.init()
    app()


if __name__ == "__main__":
    main()
