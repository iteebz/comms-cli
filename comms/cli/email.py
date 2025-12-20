"""Email thread commands."""

import typer

from .. import audit, services
from .helpers import run_service

app = typer.Typer()


@app.command()
def threads(
    label: str = typer.Option(
        "inbox", "--label", "-l", help="Label filter: inbox, unread, archive, trash, starred, sent"
    ),
):
    """List threads from all accounts"""
    for entry in services.list_threads(label):
        account = entry["account"]
        thread_list = entry["threads"]
        typer.echo(f"\n{account['email']} ({label}):")

        if not thread_list:
            typer.echo("  No threads")
            continue

        for t in thread_list:
            date_str = t.get("date", "")[:16]
            typer.echo(f"  {t['id'][:8]} | {date_str:16} | {t['snippet'][:50]}")


@app.command()
def thread(thread_id: str, email: str = typer.Option(None, "--email", "-e")):
    """Fetch and display full thread"""
    full_id = run_service(services.resolve_thread_id, thread_id, email) or thread_id
    messages = run_service(services.fetch_thread, full_id, email)

    typer.echo(f"\nThread: {messages[0]['subject']}")
    typer.echo("=" * 80)

    for msg in messages:
        typer.echo(f"\nFrom: {msg['from']}")
        typer.echo(f"Date: {msg['date']}")
        typer.echo(f"\n{msg['body']}\n")
        typer.echo("-" * 80)


@app.command()
def summarize(thread_id: str, email: str = typer.Option(None, "--email", "-e")):
    """Summarize thread using Claude"""
    from .. import claude

    full_id = run_service(services.resolve_thread_id, thread_id, email) or thread_id
    messages = run_service(services.fetch_thread, full_id, email)

    typer.echo(f"Summarizing {len(messages)} messages...")
    summary = claude.summarize_thread(messages)
    typer.echo(f"\n{summary}")


@app.command()
def archive(thread_id: str, email: str = typer.Option(None, "--email", "-e")):
    """Archive thread (remove from inbox)"""
    run_service(services.thread_action, "archive", thread_id, email)
    typer.echo(f"Archived thread: {thread_id}")
    audit.log("archive", "thread", thread_id, {"reason": "manual"})


@app.command()
def delete(thread_id: str, email: str = typer.Option(None, "--email", "-e")):
    """Delete thread (move to trash)"""
    run_service(services.thread_action, "delete", thread_id, email)
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
    run_service(services.thread_action, action_name, thread_id, email)
    past_tense = f"{action_name}ged" if action_name.endswith("flag") else f"{action_name}d"
    typer.echo(f"{past_tense.capitalize()} thread: {thread_id}")
    audit.log(action_name, "thread", thread_id, {"reason": "manual"})
