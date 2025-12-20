"""Proposal management commands."""

import typer

from .. import proposals as proposals_module
from .. import services

app = typer.Typer()


@app.command()
def review(
    status: str = typer.Option(None, "--status", "-s"),
    action: str = typer.Option(
        None, "--action", "-a", help="Filter by action: delete, archive, flag"
    ),
):
    """Review proposals"""
    props = proposals_module.list_proposals(status=status)

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
    proposal_id, error, auto_approved = proposals_module.create_proposal(
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
    proposal_id: str = typer.Argument(None),
    human: str = typer.Option(None, "--human", help="Human reasoning for approval"),
    all_pending: bool = typer.Option(False, "--all", help="Approve all pending proposals"),
    action: str = typer.Option(None, "--action", "-a", help="Approve all with this action"),
):
    """Approve proposal(s)"""
    if all_pending or action:
        props = proposals_module.list_proposals(status="pending")
        if action:
            props = [p for p in props if p["proposed_action"] == action]

        if not props:
            typer.echo("No matching proposals")
            return

        count = 0
        for p in props:
            if proposals_module.approve_proposal(p["id"], user_reasoning=human):
                count += 1
        typer.echo(f"Approved {count} proposals")
        return

    if not proposal_id:
        typer.echo("Provide proposal_id or use --all/--action")
        raise typer.Exit(1)

    if proposals_module.approve_proposal(proposal_id, user_reasoning=human):
        typer.echo(f"Approved {proposal_id[:8]}")
    else:
        typer.echo("Failed to approve (not found or already processed)")
        raise typer.Exit(1)


@app.command()
def reject(
    proposal_id: str = typer.Argument(None),
    human: str = typer.Option(None, "--human", help="Human reasoning for rejection"),
    correct: str = typer.Option(
        None, "--correct", help="Corrected action (e.g., 'delete' instead of 'archive')"
    ),
    all_pending: bool = typer.Option(False, "--all", help="Reject all pending proposals"),
    action: str = typer.Option(None, "--action", "-a", help="Reject all with this action"),
):
    """Reject proposal(s) (optionally with correction)"""
    if all_pending or action:
        props = proposals_module.list_proposals(status="pending")
        if action:
            props = [p for p in props if p["proposed_action"] == action]

        if not props:
            typer.echo("No matching proposals")
            return

        count = 0
        for p in props:
            if proposals_module.reject_proposal(p["id"], user_reasoning=human, correction=correct):
                count += 1
        typer.echo(f"Rejected {count} proposals")
        return

    if not proposal_id:
        typer.echo("Provide proposal_id or use --all/--action")
        raise typer.Exit(1)

    if proposals_module.reject_proposal(proposal_id, user_reasoning=human, correction=correct):
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
    approved = proposals_module.get_approved_proposals()
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
