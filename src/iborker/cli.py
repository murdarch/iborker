"""Command-line interface for iborker tools."""

import os
import sys
from pathlib import Path

import typer

from iborker import contracts, history, stdev

SPLASH = """\
   ⢀⣤⣶⣶⣤⡀
 ⣴⣿⣿⣿⣿⣿⣦
 ⣿⣿ ⠶⠶ ⣿⣿   iborker ▮
 ⣿⣿  ⣿⣿ ⣿⣿
 ⠘⠿⠿⠿⠿⠟⠃

you tried your best
"""


def _show_splash_once() -> None:
    """Show splash art once per terminal session."""
    if not sys.stdout.isatty():
        return

    # Use TTY name to track session (persists across uv run invocations)
    try:
        tty = os.ttyname(sys.stdout.fileno()).replace("/", "_")
    except OSError:
        return

    marker = Path(f"/tmp/iborker-splash{tty}")

    if not marker.exists():
        typer.echo(SPLASH)
        marker.touch()


app = typer.Typer(
    name="iborker",
    help="CLI tools for Interactive Brokers futures trading.",
)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """CLI tools for Interactive Brokers futures trading."""
    _show_splash_once()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


app.add_typer(history.app, name="history")
app.add_typer(contracts.app, name="contract")
app.add_typer(stdev.app, name="stdev")


@app.command()
def version() -> None:
    """Show version information."""
    from iborker import __version__

    typer.echo(f"iborker {__version__}")


@app.command()
def status() -> None:
    """Check IB connection status."""
    typer.echo("Connection status: Not implemented yet")


if __name__ == "__main__":
    app()
