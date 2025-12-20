"""Daemon and agent management commands."""

import typer

app = typer.Typer()


@app.command()
def agent_authorize(phone: str = typer.Argument(..., help="Phone number to authorize")):
    """Authorize a phone number to send commands"""
    from .. import agent

    agent.add_authorized_sender(phone)
    typer.echo(f"Authorized: {phone}")


@app.command()
def agent_revoke(phone: str = typer.Argument(..., help="Phone number to revoke")):
    """Revoke command authorization from a phone number"""
    from .. import agent

    if agent.remove_authorized_sender(phone):
        typer.echo(f"Revoked: {phone}")
    else:
        typer.echo(f"Not authorized: {phone}")


@app.command()
def agent_list():
    """List authorized command senders"""
    from .. import agent

    senders = agent.get_authorized_senders()
    if not senders:
        typer.echo("No authorized senders (all senders allowed)")
        return

    typer.echo("Authorized senders:")
    for s in sorted(senders):
        typer.echo(f"  {s}")


@app.command()
def agent_config(
    enable: bool = typer.Option(None, "--enable/--disable", help="Enable or disable agent"),
    nlp: bool = typer.Option(None, "--nlp/--no-nlp", help="Enable natural language parsing"),
):
    """Configure agent settings"""
    from ..config import get_agent_config, set_agent_config

    config = get_agent_config()

    if enable is not None:
        config["enabled"] = enable
    if nlp is not None:
        config["nlp"] = nlp

    set_agent_config(config)

    typer.echo(f"Agent: {'enabled' if config.get('enabled', True) else 'disabled'}")
    typer.echo(f"NLP: {'enabled' if config.get('nlp', False) else 'disabled'}")


@app.command()
def daemon_start(
    interval: int = typer.Option(5, "--interval", "-i", help="Polling interval in seconds"),
    foreground: bool = typer.Option(False, "--foreground", "-f", help="Run in foreground"),
):
    """Start Signal daemon (background polling)"""
    from .. import daemon

    success, msg = daemon.start(interval=interval, foreground=foreground)
    typer.echo(msg)
    if not success:
        raise typer.Exit(1)


@app.command()
def daemon_stop():
    """Stop Signal daemon"""
    from .. import daemon

    success, msg = daemon.stop()
    typer.echo(msg)
    if not success:
        raise typer.Exit(1)


@app.command()
def daemon_status():
    """Show daemon status"""
    from .. import daemon, launchd

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
    from .. import launchd

    success, msg = launchd.install(interval=interval)
    typer.echo(msg)
    if not success:
        raise typer.Exit(1)


@app.command()
def daemon_uninstall():
    """Uninstall daemon launchd service"""
    from .. import launchd

    success, msg = launchd.uninstall()
    typer.echo(msg)
    if not success:
        raise typer.Exit(1)
