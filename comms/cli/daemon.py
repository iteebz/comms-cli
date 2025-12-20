"""Daemon management commands."""

import typer

app = typer.Typer()


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
