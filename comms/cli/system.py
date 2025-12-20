"""System commands: init, backup, status, inbox, triage."""

from datetime import datetime

import typer

from .. import accounts as accts_module
from .. import db, services
from ..adapters.email import gmail

app = typer.Typer()


def show_dashboard():
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
    from ..config import RULES_PATH

    if not RULES_PATH.exists():
        typer.echo(f"No rules file. Create one at: {RULES_PATH}")
        return

    typer.echo(RULES_PATH.read_text())


@app.command()
def status():
    """Show system status"""
    from ..config import get_policy

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
    from ..config import get_policy, set_policy

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
def stats():
    """Show learning stats from decisions"""
    from .. import learning

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
def audit_log(limit: int = 20):
    """Show recent audit log"""
    from .. import audit

    logs = audit.get_recent_logs(limit)
    for log_entry in logs:
        typer.echo(
            f"{log_entry['timestamp']} | {log_entry['action']} | "
            f"{log_entry['entity_type']}:{log_entry['entity_id'][:8]}"
        )


@app.command()
def triage(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of items to triage"),
    confidence: float = typer.Option(0.7, "--confidence", "-c", help="Minimum confidence"),
    dry_run: bool = typer.Option(False, "--dry-run", "-d", help="Show proposals without creating"),
    auto_execute: bool = typer.Option(False, "--execute", "-x", help="Auto-execute after approval"),
):
    """Triage inbox — Claude bulk-proposes actions"""
    from .. import triage as triage_module

    typer.echo("Scanning inbox...")
    triage_proposals = triage_module.triage_inbox(limit=limit)

    if not triage_proposals:
        typer.echo("No items to triage or triage failed")
        return

    typer.echo(f"\nFound {len(triage_proposals)} proposals:\n")

    for p in triage_proposals:
        conf = f"{p.confidence:.0%}"
        source = "📧" if p.item.source == "email" else "💬"
        skip = " (skip)" if p.confidence < confidence or p.action == "ignore" else ""
        typer.echo(f"{source} [{conf}] {p.action:10} {p.item.sender[:20]:20} {p.reasoning}{skip}")

    created = triage_module.create_proposals_from_triage(
        triage_proposals,
        min_confidence=confidence,
        dry_run=dry_run,
    )

    if dry_run:
        typer.echo(f"\nDry run: would create {len(created)} proposals")
        return

    typer.echo(f"\nCreated {len(created)} proposals")

    if auto_execute and created:
        typer.echo("\nExecuting approved proposals...")
        results = services.execute_approved_proposals()
        executed = sum(1 for r in results if r.success)
        typer.echo(f"Executed: {executed}/{len(results)}")
