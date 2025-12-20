from datetime import datetime

import typer

from . import accounts as accts_module
from . import audit, db, drafts, policy, proposals
from .adapters.email import gmail, outlook, proton
from .adapters.messaging import signal

app = typer.Typer(
    name="comms",
    help="AI-managed comms for ADHD brains",
    no_args_is_help=False,
    add_completion=False,
)


THREAD_ACTIONS = {
    "archive": gmail.archive_thread,
    "delete": gmail.delete_thread,
    "flag": gmail.flag_thread,
    "unflag": gmail.unflag_thread,
    "unarchive": gmail.unarchive_thread,
    "undelete": gmail.undelete_thread,
}


def _resolve_email_account(email: str | None) -> dict:
    account, error = accts_module.select_email_account(email)
    if account:
        return account
    typer.echo(error or "No email account found")
    raise typer.Exit(1)


def _require_gmail_account(email: str | None) -> dict:
    account = _resolve_email_account(email)
    if account["provider"] != "gmail":
        typer.echo(f"Provider {account['provider']} not supported for this command")
        raise typer.Exit(1)
    return account


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
def backup():
    """Backup database to ~/.comms_backups/{timestamp}/"""
    backup_path = db.backup_db()
    if backup_path:
        typer.echo(f"Backup created: {backup_path}")
    else:
        typer.echo("No database to backup")


@app.command()
def rules():
    """Show triage rules (edit at ~/.comms/rules.md)"""
    from .config import RULES_PATH

    if not RULES_PATH.exists():
        typer.echo(f"No rules file. Create one at: {RULES_PATH}")
        return

    typer.echo(RULES_PATH.read_text())


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

    account = _resolve_email_account(email)
    email = account["email"]

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


@app.command()
def approve_draft(draft_id: str):
    """Approve draft for sending"""
    full_id = drafts.resolve_draft_id(draft_id) or draft_id
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

    account = _require_gmail_account(email)
    email = account["email"]

    messages = gmail.fetch_thread_messages(thread_id, email)

    if not messages:
        typer.echo(f"Thread not found: {thread_id}")
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
    full_id = drafts.resolve_draft_id(draft_id) or draft_id
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
    provider: str = typer.Argument(..., help="Provider: gmail, outlook, proton, signal"),
    identifier: str = typer.Argument(
        None, help="Email or phone number (e.g., +1234567890 for Signal)"
    ),
    password: str = typer.Option(
        None, "--password", "-p", help="Password (Proton Bridge password)"
    ),
    client_id: str = typer.Option(None, "--client-id", help="OAuth Client ID (Outlook)"),
    client_secret: str = typer.Option(
        None, "--client-secret", help="OAuth Client Secret (Outlook)"
    ),
):
    """Link email or messaging account"""
    if provider not in ["proton", "gmail", "outlook", "signal"]:
        typer.echo(f"Unknown provider: {provider}")
        raise typer.Exit(1)

    if provider == "signal":
        existing = signal.list_accounts()
        if existing:
            typer.echo(f"Signal accounts already linked: {existing}")
            for phone in existing:
                if not any(a["email"] == phone for a in accts_module.list_accounts("messaging")):
                    account_id = accts_module.add_messaging_account("signal", phone)
                    typer.echo(f"Added existing account: {phone} ({account_id[:8]})")
            return

        typer.echo("Linking Signal as secondary device...")
        typer.echo("Open Signal on your phone -> Settings -> Linked Devices -> Link New Device")
        typer.echo("Then scan the QR code that will appear.")
        success, msg = signal.link("comms-cli")
        if not success:
            typer.echo(f"Link failed: {msg}")
            raise typer.Exit(1)

        accounts = signal.list_accounts()
        if not accounts:
            typer.echo("No accounts found after linking")
            raise typer.Exit(1)

        phone = accounts[0]
        account_id = accts_module.add_messaging_account("signal", phone)
        typer.echo(f"Linked Signal: {phone}")
        typer.echo(f"Account ID: {account_id}")
        return

    email = identifier
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


def _get_signal_phone(phone: str | None) -> str:
    if phone:
        return phone
    accounts = accts_module.list_accounts("messaging")
    signal_accounts = [a for a in accounts if a["provider"] == "signal"]
    if not signal_accounts:
        typer.echo("No Signal accounts linked. Run: comms link signal")
        raise typer.Exit(1)
    return signal_accounts[0]["email"]


@app.command()
def messages(
    phone: str = typer.Option(None, "--phone", "-p", help="Signal phone number"),
    timeout: int = typer.Option(5, "--timeout", "-t", help="Receive timeout in seconds"),
):
    """Receive new Signal messages and store them"""
    phone = _get_signal_phone(phone)

    typer.echo(f"Receiving messages for {phone}...")
    msgs = signal.receive(phone, timeout=timeout)

    if msgs:
        typer.echo(f"Received {len(msgs)} new message(s)")
        for msg in msgs:
            sender = msg.get("from_name") or msg.get("from", "Unknown")
            body = msg.get("body", "")
            typer.echo(f"  {sender}: {body}")
    else:
        typer.echo("No new messages")


@app.command()
def signal_inbox(
    phone: str = typer.Option(None, "--phone", "-p"),
):
    """Show Signal conversations"""
    phone = _get_signal_phone(phone)

    convos = signal.get_conversations(phone)
    if not convos:
        typer.echo("No conversations yet. Run: comms messages")
        return

    for c in convos:
        name = c["sender_name"] or c["sender_phone"]
        unread = c["unread_count"]
        count = c["message_count"]
        unread_str = f" ({unread} unread)" if unread else ""
        typer.echo(f"{c['sender_phone']:16} | {name:20} | {count} msgs{unread_str}")


@app.command()
def signal_history(
    contact: str = typer.Argument(..., help="Phone number to view history with"),
    phone: str = typer.Option(None, "--phone", "-p"),
    limit: int = typer.Option(20, "--limit", "-n"),
):
    """Show message history with a contact"""
    phone = _get_signal_phone(phone)

    msgs = signal.get_messages(phone=phone, sender=contact, limit=limit)
    if not msgs:
        typer.echo(f"No messages from {contact}")
        return

    msgs.reverse()
    for msg in msgs:
        sender = msg["sender_name"] or msg["sender_phone"]
        ts = datetime.fromtimestamp(msg["timestamp"] / 1000).strftime("%m-%d %H:%M")
        typer.echo(f"[{ts}] {sender}: {msg['body']}")


@app.command()
def signal_send(
    recipient: str = typer.Argument(..., help="Phone number or group ID"),
    message: str = typer.Option(..., "--message", "-m", help="Message to send"),
    phone: str = typer.Option(None, "--phone", "-p"),
    group: bool = typer.Option(False, "--group", "-g", help="Send to group"),
):
    """Send Signal message"""
    phone = _get_signal_phone(phone)

    if group:
        success, msg = signal.send_group(phone, recipient, message)
    else:
        success, msg = signal.send(phone, recipient, message)

    if success:
        typer.echo(f"Sent to {recipient}")
    else:
        typer.echo(f"Failed: {msg}")
        raise typer.Exit(1)


@app.command()
def signal_contacts(phone: str = typer.Option(None, "--phone", "-p")):
    """List Signal contacts"""
    phone = _get_signal_phone(phone)
    contacts = signal.list_contacts(phone)
    if not contacts:
        typer.echo("No contacts")
        return

    for c in contacts:
        name = c.get("name", "")
        number = c.get("number", "")
        typer.echo(f"{number:20} {name}")


@app.command()
def signal_groups(phone: str = typer.Option(None, "--phone", "-p")):
    """List Signal groups"""
    phone = _get_signal_phone(phone)
    groups = signal.list_groups(phone)
    if not groups:
        typer.echo("No groups")
        return

    for g in groups:
        typer.echo(f"{g.get('id', '')[:16]} | {g.get('name', '')}")


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
def threads(
    label: str = typer.Option(
        "inbox", "--label", "-l", help="Label filter: inbox, unread, archive, trash, starred, sent"
    ),
):
    """List threads from all accounts"""
    accounts = accts_module.list_accounts("email")

    for account in accounts:
        if account["provider"] == "gmail":
            typer.echo(f"\n{account['email']} ({label}):")
            threads = gmail.list_threads(account["email"], label=label)

            if not threads:
                typer.echo("  No threads")
                continue

            for t in threads:
                date_str = t.get("date", "")[:16]  # "Mon, 7 Jul 2025"
                typer.echo(f"  {t['id'][:8]} | {date_str:16} | {t['snippet'][:50]}")


def _resolve_thread_id(prefix: str, email: str) -> str | None:
    if len(prefix) >= 16:
        return prefix
    threads = gmail.list_threads(email, label="inbox", max_results=100)
    threads += gmail.list_threads(email, label="unread", max_results=100)
    for t in threads:
        if t["id"].startswith(prefix):
            return t["id"]
    return None


@app.command()
def thread(thread_id: str, email: str = typer.Option(None, "--email", "-e")):
    """Fetch and display full thread"""
    account = _require_gmail_account(email)
    email = account["email"]

    full_id = _resolve_thread_id(thread_id, email) or thread_id
    messages = gmail.fetch_thread_messages(full_id, email)

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
    account = _require_gmail_account(email)
    email = account["email"]

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
    account = _require_gmail_account(email)
    email = account["email"]

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
    account = _require_gmail_account(email)
    email = account["email"]

    success = action_fn(thread_id, email)

    if success:
        past_tense = f"{action_name}ged" if action_name.endswith("flag") else f"{action_name}d"
        typer.echo(f"{past_tense.capitalize()} thread: {thread_id}")
        audit.log(action_name, "thread", thread_id, {"reason": "manual"})
    else:
        typer.echo(f"Failed to {action_name} thread")
        raise typer.Exit(1)


@app.command()
def review(
    status: str = typer.Option(None, "--status", "-s"),
    action: str = typer.Option(
        None, "--action", "-a", help="Filter by action: delete, archive, flag"
    ),
):
    """Review proposals"""
    props = proposals.list_proposals(status=status)

    if action:
        props = [p for p in props if p["proposed_action"] == action]

    if not props:
        typer.echo("No proposals")
        return

    by_action = {}
    for p in props:
        a = p["proposed_action"]
        if a not in by_action:
            by_action[a] = []
        by_action[a].append(p)

    for act in ["flag", "archive", "delete"]:
        if act not in by_action:
            continue
        typer.echo(f"\n=== {act.upper()} ({len(by_action[act])}) ===")
        for p in by_action[act]:
            typer.echo(f"  {p['id'][:8]} | {p['agent_reasoning'] or p['entity_id'][:8]}")


@app.command()
def propose(
    action: str,
    entity_type: str,
    entity_id: str,
    agent: str = typer.Option(None, "--agent", help="Agent reasoning"),
):
    """Create proposal"""
    proposal_id, error = proposals.create_proposal(
        entity_type=entity_type,
        entity_id=entity_id,
        proposed_action=action,
        agent_reasoning=agent,
    )

    if proposal_id:
        typer.echo(f"Created proposal {proposal_id[:8]}")
    else:
        typer.echo(f"Failed to create proposal: {error}")
        raise typer.Exit(1)


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
    correct: str = typer.Option(
        None, "--correct", help="Corrected action (e.g., 'delete' instead of 'archive')"
    ),
):
    """Reject proposal (optionally with correction)"""
    if proposals.reject_proposal(proposal_id, user_reasoning=human, correction=correct):
        if correct:
            typer.echo(f"Rejected {proposal_id[:8]} with correction: {correct}")
        else:
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
        email = p.get("email")

        typer.echo(f"Executing: {action} {entity_type} {entity_id[:8]}")

        try:
            if entity_type == "thread":
                if not email:
                    account = _resolve_email_account(None)
                    email = account["email"]

                action_fn = THREAD_ACTIONS.get(action)
                if not action_fn:
                    typer.echo(f"  Unknown action: {action}")
                    failed_count += 1
                    continue

                success = action_fn(entity_id, email)

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


@app.command()
def signal_status():
    """Check Signal connection status"""
    accounts = signal.list_accounts()
    if not accounts:
        typer.echo("No Signal accounts registered with signal-cli")
        typer.echo("Run: comms link signal")
        return

    for phone in accounts:
        success, msg = signal.test_connection(phone)
        status = "OK" if success else f"FAIL: {msg}"
        typer.echo(f"{phone}: {status}")


def main():
    db.init()
    app()


if __name__ == "__main__":
    main()
