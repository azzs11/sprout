"""The ``sprout`` Typer application."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from sprout import __version__
from sprout.cli.diff import diff
from sprout.cli.history import history
from sprout.cli.index import index
from sprout.cli.mcp import mcp_app
from sprout.cli.risk import risk
from sprout.cli.search import search
from sprout.cli.setup import init, uninstall
from sprout.cli.status import status
from sprout.cli.why import why
from sprout.core.git import open_repo
from sprout.core.index.store import Store
from sprout.errors import SproutError

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
app.command()(index)
app.command()(search)
app.command()(why)
app.command()(risk)
app.command()(init)
app.command()(uninstall)
app.add_typer(mcp_app)


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
        typer.echo(ctx.get_help())
        typer.echo(_index_line())


def _index_line() -> str:
    """One line about the current repository's index, for the bare ``sprout`` overview."""
    try:
        git = open_repo(Path())
        with Store.open(git.root, create=False) as store:
            stats = store.stats()
    except SproutError as exc:
        return exc.hint or exc.message
    when = stats.updated_at.strftime("%Y-%m-%d %H:%M") if stats.updated_at else "never"
    return f"Index: {stats.commits:,} commits, {stats.embedded:,} embedded, updated {when}."


def main() -> None:
    """Console-script entry point."""
    app()
