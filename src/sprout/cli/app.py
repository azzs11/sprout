"""The ``sprout`` Typer application."""

from __future__ import annotations

from typing import Annotated

import typer

from sprout import __version__
from sprout.cli.diff import diff
from sprout.cli.history import history
from sprout.cli.status import status

app = typer.Typer(
    name="sprout",
    help="Your codebase's memory: explore and explain git history.",
    invoke_without_command=True,
    add_completion=False,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)

app.command()(status)
app.command()(diff)
app.command()(history)


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"sprout {__version__}")
        raise typer.Exit


@app.callback()
def _root(
    ctx: typer.Context,
    version: Annotated[  # noqa: ARG001 - handled by its eager callback
        bool,
        typer.Option(
            "--version",
            "-V",
            help="Show the version and exit.",
            callback=_show_version,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Your codebase's memory: explore and explain git history."""
    if ctx.invoked_subcommand is None:
        # Phase 2 replaces this with an overview of the repository's index.
        typer.echo(ctx.get_help())


def main() -> None:
    """Console-script entry point."""
    app()
