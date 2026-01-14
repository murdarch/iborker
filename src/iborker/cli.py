"""Command-line interface for iborker tools."""

import typer

from iborker import contracts, history, stdev

app = typer.Typer(
    name="iborker",
    help="CLI tools for Interactive Brokers futures trading.",
    no_args_is_help=True,
)

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
