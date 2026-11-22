"""``sprout diff``: staged or unstaged changes."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table

from sprout.cli.output import JsonOption, RepoOption, emit, handle_errors, load_repo
from sprout.models import Diff

StagedOption = Annotated[
    bool, typer.Option("--staged", "-s", help="Show staged changes instead of unstaged ones.")
]
StatOption = Annotated[bool, typer.Option("--stat", help="Show only the per-file summary.")]


def diff(
    repo: RepoOption = Path(),
    staged: StagedOption = False,
    stat: StatOption = False,
    as_json: JsonOption = False,
) -> None:
    """Show changes in the working tree, or in the index with --staged."""
    with handle_errors(as_json=as_json):
        result = load_repo(repo).diff(staged=staged)
        emit(result, as_json=as_json, render=lambda d, out: render_diff(d, out, stat_only=stat))


def render_diff(result: Diff, out: Console, *, stat_only: bool = False) -> None:
    """Render a ``Diff`` for people."""
    where = "staged" if result.staged else "unstaged"
    if not result.files:
        hint = "" if result.staged else " Use --staged to see staged changes."
        out.print(f"No {where} changes.{hint}")
        return
    out.print(_summary(result))
    if stat_only:
        return
    for file in result.files:
        out.print()
        if file.binary:
            out.print(f"[bold]{file.path}[/]: binary file {file.kind.value}", markup=True)
        else:
            out.print(Syntax(file.patch.rstrip("\n"), "diff", theme="ansi_dark", word_wrap=True))


def _summary(result: Diff) -> Table:
    table = Table(box=None, pad_edge=False, show_footer=True)
    count = len(result.files)
    table.add_column("change", style="dim", footer=f"{count} file{'' if count == 1 else 's'}")
    table.add_column("path", overflow="fold")
    table.add_column("+", justify="right", style="green", footer=f"+{result.additions}")
    table.add_column("-", justify="right", style="red", footer=f"-{result.deletions}")
    for file in result.files:
        name = f"{file.old_path} → {file.path}" if file.old_path else file.path
        added = "bin" if file.binary else f"+{file.additions}"
        removed = "" if file.binary else f"-{file.deletions}"
        table.add_row(file.kind.value, name, added, removed)
    return table
