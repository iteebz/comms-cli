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
    proposal_id: str,
    human: str = typer.Option(None, "--human", help="Human reasoning for approval"),
):
    """Approve proposal"""
    if proposals_module.approve_proposal(proposal_id, user_reasoning=human):
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
