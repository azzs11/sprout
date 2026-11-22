"""``sprout status``: branch, HEAD and working-tree changes."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.text import Text

from sprout.cli.output import JsonOption, RepoOption, emit, handle_errors, load_repo
from sprout.models import FileChange, RepoStatus


def status(repo: RepoOption = Path(), as_json: JsonOption = False) -> None:
    """Show the current branch and what has changed."""
    with handle_errors(as_json=as_json):
        emit(load_repo(repo).status(), as_json=as_json, render=render_status)


def render_status(status: RepoStatus, out: Console) -> None:
    """Render a ``RepoStatus`` for people."""
    out.print(_headline(status))
    if status.clean:
        out.print("Nothing to commit, working tree clean.")
        return
    sections: list[tuple[str, list[FileChange]]] = [
        ("Staged", status.staged),
        ("Unstaged", status.unstaged),
    ]
    for title, changes in sections:
        if changes:
            out.print(_table(title, [(c.kind.value, c.path) for c in changes]))
    if status.untracked:
        out.print(_table("Untracked", [("untracked", p) for p in status.untracked]))
    if status.conflicted:
        out.print(_table("Conflicted", [("conflicted", p) for p in status.conflicted]))


def _headline(status: RepoStatus) -> Text:
    line = Text()
    if status.detached:
        line.append("HEAD detached", style="bold yellow")
    else:
        line.append("On branch ")
        line.append(status.branch or "?", style="bold")
    if status.unborn:
        line.append(" · no commits yet", style="dim")
    elif status.head:
        line.append(f" · {status.head[:7]}", style="dim")
    return line


def _table(title: str, rows: list[tuple[str, str]]) -> Table:
    table = Table(title=title, title_justify="left", show_header=False, box=None, pad_edge=False)
    table.add_column("kind", style="dim", no_wrap=True)
    table.add_column("path", overflow="fold")
    for kind, path in rows:
        table.add_row(kind, path)
    return table
