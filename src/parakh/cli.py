"""Command-line entry point for Parakh."""

import typer

from parakh import __version__

app = typer.Typer(help="Test voice agents on Indian speech.", no_args_is_help=True)


@app.callback()
def main() -> None:
    """Parakh command-line interface."""


@app.command()
def version() -> None:
    """Print the Parakh version."""
    typer.echo(f"parakh {__version__}")
