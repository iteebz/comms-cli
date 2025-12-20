"""Signal messaging commands."""

from datetime import datetime

import typer

from ..adapters.messaging import signal as signal_module
from .helpers import get_signal_phone

app = typer.Typer()


@app.command()
def messages(
    phone: str = typer.Option(None, "--phone", "-p", help="Signal phone number"),
    timeout: int = typer.Option(5, "--timeout", "-t", help="Receive timeout in seconds"),
):
    """Receive new Signal messages and store them"""
    phone = get_signal_phone(phone)

    typer.echo(f"Receiving messages for {phone}...")
    msgs = signal_module.receive(phone, timeout=timeout)

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
    phone = get_signal_phone(phone)

    convos = signal_module.get_conversations(phone)
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
    phone = get_signal_phone(phone)

    msgs = signal_module.get_messages(phone=phone, sender=contact, limit=limit)
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
    phone = get_signal_phone(phone)

    if group:
        success, msg = signal_module.send_group(phone, recipient, message)
    else:
        success, msg = signal_module.send(phone, recipient, message)

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
    phone = get_signal_phone(phone)

    success, result, original = signal_module.reply(phone, message_id, message)

    if success:
        sender = original["sender_name"] or original["sender_phone"]
        typer.echo(f"Replied to {sender}")
        typer.echo(f"  Original: {original['body'][:50]}...")
    else:
        typer.echo(f"Failed: {result}")
        raise typer.Exit(1)


@app.command()
def signal_draft(
    contact: str = typer.Argument(..., help="Phone number to reply to"),
    instructions: str = typer.Option(None, "--instructions", "-i", help="Instructions for Claude"),
    phone: str = typer.Option(None, "--phone", "-p"),
):
    """Generate Signal reply using Claude"""
    from .. import claude

    phone = get_signal_phone(phone)
    msgs = signal_module.get_messages(phone=phone, sender=contact, limit=10)

    if not msgs:
        typer.echo(f"No messages from {contact}")
        raise typer.Exit(1)

    typer.echo("Generating reply...")
    body, reasoning = claude.generate_signal_reply(msgs, instructions)

    if not body:
        typer.echo(f"Failed: {reasoning}")
        raise typer.Exit(1)

    typer.echo(f"\nReasoning: {reasoning}")
    typer.echo(f"\nDraft reply to {contact}:")
    typer.echo(f"  {body}\n")

    if typer.confirm("Send this reply?"):
        success, result = signal_module.send(phone, contact, body)
        if success:
            typer.echo("Sent!")
        else:
            typer.echo(f"Failed: {result}")
            raise typer.Exit(1)


@app.command()
def signal_contacts(phone: str = typer.Option(None, "--phone", "-p")):
    """List Signal contacts"""
    phone = get_signal_phone(phone)
    contacts = signal_module.list_contacts(phone)
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
    phone = get_signal_phone(phone)
    groups = signal_module.list_groups(phone)
    if not groups:
        typer.echo("No groups")
        return

    for g in groups:
        typer.echo(f"{g.get('id', '')[:16]} | {g.get('name', '')}")


@app.command()
def signal_status():
    """Check Signal connection status"""
    accounts = signal_module.list_accounts()
    if not accounts:
        typer.echo("No Signal accounts registered with signal-cli")
        typer.echo("Run: comms link signal")
        return

    for phone in accounts:
        success, msg = signal_module.test_connection(phone)
        status = "OK" if success else f"FAIL: {msg}"
        typer.echo(f"{phone}: {status}")
