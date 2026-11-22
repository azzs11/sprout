"""``sprout history``: recent commits, optionally for one path."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from sprout.cli.output import JsonOption, RepoOption, emit, handle_errors, load_repo
from sprout.models import History

PathArgument = Annotated[
    Path | None,
    typer.Argument(help="Only show commits that changed this file or folder.", show_default=False),
]
LimitOption = Annotated[
    int, typer.Option("--limit", "-n", min=1, help="Maximum number of commits to show.")
]
RevOption = Annotated[
    str | None,
    typer.Option("--rev", "-r", help="Start from this branch, tag or commit.", show_default="HEAD"),
]


def history(
    path: PathArgument = None,
    repo: RepoOption = Path(),
    limit: LimitOption = 20,
    rev: RevOption = None,
    as_json: JsonOption = False,
) -> None:
    """Show recent commits, newest first."""
    with handle_errors(as_json=as_json):
        git = load_repo(repo)
        rel = git.relative_path(repo / path) if path is not None else None
        emit(git.history(limit=limit, rev=rev, path=rel), as_json=as_json, render=render_history)


def render_history(result: History, out: Console) -> None:
    """Render a ``History`` for people."""
    if not result.commits:
        scope = f" for {result.path}" if result.path else ""
        out.print(f"No commits yet{scope}.")
        return
    table = Table(box=None, pad_edge=False)
    table.add_column("commit", style="yellow", no_wrap=True)
    table.add_column("date", style="dim", no_wrap=True)
    table.add_column("author", no_wrap=True, max_width=24)
    table.add_column("summary", overflow="fold")
    for commit in result.commits:
        table.add_row(
            commit.short_hash,
            commit.authored_at.strftime("%Y-%m-%d"),
            commit.author.name,
            commit.summary,
        )
    out.print(table)
