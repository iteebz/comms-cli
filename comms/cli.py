from datetime import datetime

import typer

from . import accounts as accts_module
from . import audit, db, drafts, policy, proposals, services
from .adapters.email import gmail, outlook, proton
from .adapters.messaging import signal

app = typer.Typer(
    name="comms",
    help="AI-managed comms for ADHD brains",
    no_args_is_help=False,
    add_completion=False,
)


def _run_service(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(1) from None


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
def inbox(limit: int = typer.Option(20, "--limit", "-n")):
    """Unified inbox (email + signal, sorted by time)"""
    items = services.get_unified_inbox(limit=limit)
    if not items:
        typer.echo("Inbox empty")
        return

    for item in items:
        ts = datetime.fromtimestamp(item.timestamp / 1000).strftime("%m-%d %H:%M")
        unread = "●" if item.unread else " "
        source = "📧" if item.source == "email" else "💬"
        typer.echo(f"{unread} {source} [{ts}] {item.sender[:20]:20} {item.preview}")


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

    auto = pol.get("auto_approve", {})
    typer.echo("\nAuto-approve:")
    typer.echo(f"  Enabled: {auto.get('enabled', False)}")
    typer.echo(f"  Threshold: {auto.get('threshold', 0.95):.0%}")
    typer.echo(f"  Min samples: {auto.get('min_samples', 10)}")
    typer.echo(f"  Actions: {auto.get('actions', []) or 'all'}")


@app.command()
def auto_approve(
    enable: bool = typer.Option(None, "--enable/--disable", help="Enable or disable"),
    threshold: float = typer.Option(None, "--threshold", "-t", help="Accuracy threshold"),
    min_samples: int = typer.Option(None, "--min-samples", "-n", help="Minimum samples"),
    action: list[str] | None = None,
):
    """Configure auto-approve settings"""
    from .config import get_policy, set_policy

    pol = get_policy()
    auto = pol.get("auto_approve", {})

    if enable is not None:
        auto["enabled"] = enable
    if threshold is not None:
        auto["threshold"] = threshold
    if min_samples is not None:
        auto["min_samples"] = min_samples
    if action:
        auto["actions"] = list(action)

    pol["auto_approve"] = auto
    set_policy(pol)

    typer.echo(f"Auto-approve: {'enabled' if auto.get('enabled') else 'disabled'}")
    typer.echo(f"  Threshold: {auto.get('threshold', 0.95):.0%}")
    typer.echo(f"  Min samples: {auto.get('min_samples', 10)}")
    typer.echo(f"  Actions: {auto.get('actions', []) or 'all'}")


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

    draft_id, from_addr = _run_service(
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

    draft_id, original_from, reply_subject = _run_service(
        services.reply_to_thread, thread_id=thread_id, body=body, email=email
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

    _run_service(services.send_draft, full_id)
    typer.echo(f"Sent: {d.to_addr}")
    typer.echo(f"Subject: {d.subject}")


@app.command()
def audit_log(limit: int = 20):
    """Show recent audit log"""
    logs = audit.get_recent_logs(limit)
    for log_entry in logs:
        typer.echo(
            f"{log_entry['timestamp']} | {log_entry['action']} | {log_entry['entity_type']}:{log_entry['entity_id'][:8]}"
        )


@app.command()
def stats():
    """Show learning stats from decisions"""
    from . import learning

    action_stats = learning.get_decision_stats()
    if not action_stats:
        typer.echo("No decision data yet")
        return

    typer.echo("Action Stats:")
    for action, s in sorted(action_stats.items(), key=lambda x: -x[1].total):
        typer.echo(
            f"  {action:12} | {s.total:3} total | {s.accuracy:.0%} accuracy | "
            f"{s.approved} approved, {s.rejected} rejected, {s.corrected} corrected"
        )

    patterns = learning.get_correction_patterns()
    if patterns:
        typer.echo("\nCorrection Patterns:")
        for p in patterns[:5]:
            typer.echo(f"  {p['original']} → {p['corrected']} ({p['count']}x)")

    suggestions = learning.suggest_auto_approve()
    if suggestions:
        typer.echo(f"\nAuto-approve candidates (≥95% accuracy, ≥10 samples): {suggestions}")


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
        msg_id = msg["id"][:8] if msg.get("id") else ""
        typer.echo(f"{msg_id} [{ts}] {sender}: {msg['body']}")


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
def signal_reply(
    message_id: str = typer.Argument(..., help="Message ID to reply to"),
    message: str = typer.Option(..., "--message", "-m", help="Reply message"),
    phone: str = typer.Option(None, "--phone", "-p"),
):
    """Reply to a Signal message"""
    phone = _get_signal_phone(phone)

    success, result, original = signal.reply(phone, message_id, message)

    if success:
        sender = original["sender_name"] or original["sender_phone"]
        typer.echo(f"Replied to {sender}")
        typer.echo(f"  Original: {original['body'][:50]}...")
    else:
        typer.echo(f"Failed: {result}")
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
    for entry in services.list_threads(label):
        account = entry["account"]
        threads = entry["threads"]
        typer.echo(f"\n{account['email']} ({label}):")

        if not threads:
            typer.echo("  No threads")
            continue

        for t in threads:
            date_str = t.get("date", "")[:16]  # "Mon, 7 Jul 2025"
            typer.echo(f"  {t['id'][:8]} | {date_str:16} | {t['snippet'][:50]}")


@app.command()
def thread(thread_id: str, email: str = typer.Option(None, "--email", "-e")):
    """Fetch and display full thread"""
    full_id = _run_service(services.resolve_thread_id, thread_id, email) or thread_id
    messages = _run_service(services.fetch_thread, full_id, email)

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
    _run_service(services.thread_action, "archive", thread_id, email)
    typer.echo(f"Archived thread: {thread_id}")
    audit.log("archive", "thread", thread_id, {"reason": "manual"})


@app.command()
def delete(thread_id: str, email: str = typer.Option(None, "--email", "-e")):
    """Delete thread (move to trash)"""
    _run_service(services.thread_action, "delete", thread_id, email)
    typer.echo(f"Deleted thread: {thread_id}")
    audit.log("delete", "thread", thread_id, {"reason": "manual"})


@app.command()
def flag(thread_id: str, email: str = typer.Option(None, "--email", "-e")):
    """Flag thread (star it)"""
    _thread_action(thread_id, "flag", email)


@app.command()
def unflag(thread_id: str, email: str = typer.Option(None, "--email", "-e")):
    """Unflag thread (unstar it)"""
    _thread_action(thread_id, "unflag", email)


@app.command()
def unarchive(thread_id: str, email: str = typer.Option(None, "--email", "-e")):
    """Unarchive thread (restore to inbox)"""
    _thread_action(thread_id, "unarchive", email)


@app.command()
def undelete(thread_id: str, email: str = typer.Option(None, "--email", "-e")):
    """Undelete thread (restore from trash)"""
    _thread_action(thread_id, "undelete", email)


def _thread_action(thread_id: str, action_name: str, email: str | None = None):
    """Helper to execute thread actions with audit logging"""
    _run_service(services.thread_action, action_name, thread_id, email)

    past_tense = f"{action_name}ged" if action_name.endswith("flag") else f"{action_name}d"
    typer.echo(f"{past_tense.capitalize()} thread: {thread_id}")
    audit.log(action_name, "thread", thread_id, {"reason": "manual"})


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
    proposal_id, error, auto_approved = proposals.create_proposal(
        entity_type=entity_type,
        entity_id=entity_id,
        proposed_action=action,
        agent_reasoning=agent,
    )

    if proposal_id:
        if auto_approved:
            typer.echo(f"Auto-approved proposal {proposal_id[:8]} (high confidence)")
        else:
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

    results = services.execute_approved_proposals()

    executed_count = 0
    failed_count = 0
    for result in results:
        typer.echo(f"Executing: {result.action} {result.entity_type} {result.entity_id[:8]}")
        if result.success:
            executed_count += 1
            typer.echo(f"  ✓ {result.action} completed")
        else:
            failed_count += 1
            typer.echo(f"  ✗ {result.error}")

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


@app.command()
def daemon_start(
    interval: int = typer.Option(5, "--interval", "-i", help="Polling interval in seconds"),
    foreground: bool = typer.Option(False, "--foreground", "-f", help="Run in foreground"),
):
    """Start Signal daemon (background polling)"""
    from . import daemon

    success, msg = daemon.start(interval=interval, foreground=foreground)
    typer.echo(msg)
    if not success:
        raise typer.Exit(1)


@app.command()
def daemon_stop():
    """Stop Signal daemon"""
    from . import daemon

    success, msg = daemon.stop()
    typer.echo(msg)
    if not success:
        raise typer.Exit(1)


@app.command()
def daemon_status():
    """Show daemon status"""
    from . import daemon, launchd

    s = daemon.status()
    ld = launchd.status()

    if ld["installed"]:
        typer.echo(f"Launchd: {'running' if ld['running'] else 'installed but not running'}")
    elif s["running"]:
        typer.echo(f"Running (PID {s['pid']})")
        typer.echo(f"Accounts: {', '.join(s['accounts'])}")
    else:
        typer.echo("Not running")

    if s.get("last_log"):
        typer.echo("\nRecent log:")
        for line in s["last_log"]:
            typer.echo(f"  {line}")


@app.command()
def daemon_install(
    interval: int = typer.Option(5, "--interval", "-i", help="Polling interval"),
):
    """Install daemon as launchd service (auto-start on boot)"""
    from . import launchd

    success, msg = launchd.install(interval=interval)
    typer.echo(msg)
    if not success:
        raise typer.Exit(1)


@app.command()
def daemon_uninstall():
    """Uninstall daemon launchd service"""
    from . import launchd

    success, msg = launchd.uninstall()
    typer.echo(msg)
    if not success:
        raise typer.Exit(1)


def main():
    db.init()
    app()


if __name__ == "__main__":
    main()
