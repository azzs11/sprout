"""``sprout index``: build or update the history index in ``.sprout/``."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table

from sprout import services
from sprout.cli.output import JsonOption, RepoOption, emit, err_console, handle_errors
from sprout.config import load_settings
from sprout.core.git import open_repo
from sprout.core.index.indexer import IndexOptions, NullProgress, build_index
from sprout.core.index.store import INDEX_DIR, INDEX_FILE, Store
from sprout.errors import SproutError
from sprout.models import IndexStats

_RELATIVE = re.compile(r"^(?P<n>\d+)(?P<unit>[dwmy])$")
_UNIT_DAYS = {"d": 1, "w": 7, "m": 30, "y": 365}


def index(
    repo: RepoOption = Path(),
    rev: Annotated[
        str | None, typer.Option("--rev", "-r", help="Index history reachable from this ref.")
    ] = None,
    since: Annotated[
        str | None, typer.Option(help="Only commits newer than this: 2y, 6m, 30d or 2024-01-31.")
    ] = None,
    no_embed: Annotated[bool, typer.Option("--no-embed", help="Skip semantic vectors.")] = False,
    summarise: Annotated[
        bool, typer.Option("--summarise", help="Add LLM summaries (slow; local Ollama by default).")
    ] = False,
    summary_limit: Annotated[
        int | None, typer.Option(min=1, help="Summarise at most this many commits this run.")
    ] = None,
    rebuild: Annotated[
        bool, typer.Option(help="Delete the index and build it from scratch.")
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Build or update the history index. Safe to stop and resume at any time."""
    with handle_errors(as_json=as_json):
        git = open_repo(repo)
        base = git.root  # the work tree, or the git dir itself for bare repositories
        if rebuild:
            _delete_index(base)
        settings = load_settings(git.root)
        embedder = None if no_embed else services.build_embedder(settings)
        summariser = services.build_summariser(settings) if summarise else None
        if summariser is not None and summariser.provider.remote and not as_json:
            err_console().print(
                f"Sending redacted diffs to [bold]{summariser.provider.name}[/] for summaries.",
                markup=True,
            )
        options = IndexOptions(rev=rev, since=_parse_since(since), summary_limit=summary_limit)
        with Store.open(base, create=True) as store:
            try:
                if as_json:
                    stats = build_index(
                        git,
                        store,
                        embedder=embedder,
                        summariser=summariser,
                        progress=NullProgress(),
                        options=options,
                    )
                else:
                    with _RichProgress() as progress:
                        stats = build_index(
                            git,
                            store,
                            embedder=embedder,
                            summariser=summariser,
                            progress=progress,
                            options=options,
                        )
            except KeyboardInterrupt:
                err_console().print(
                    "Stopped. Finished batches are saved; run sprout index again to continue."
                )
                raise typer.Exit(code=130) from None
        emit(stats, as_json=as_json, render=render_stats)


def render_stats(stats: IndexStats, out: Console) -> None:
    """Render ``IndexStats`` for people."""
    table = Table(box=None, show_header=False, pad_edge=False)
    table.add_column(style="dim")
    table.add_column()
    table.add_row("commits", f"{stats.commits:,}")
    table.add_row("reverts", f"{stats.reverts:,}")
    vectors = f"{stats.embedded:,}" + (
        f" ({stats.embedding_model})" if stats.embedding_model else ""
    )
    table.add_row("embedded", vectors if stats.vectors_available else "unavailable on this Python")
    table.add_row("summarised", f"{stats.summarised:,}")
    table.add_row("index", stats.db_path)
    out.print(table)


def _parse_since(value: str | None) -> datetime | None:
    if value is None:
        return None
    match = _RELATIVE.match(value.strip().lower())
    if match:
        days = int(match["n"]) * _UNIT_DAYS[match["unit"]]
        return datetime.now(UTC) - timedelta(days=days)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise SproutError(
            f"Could not read --since {value!r}.",
            hint="Use a span like 2y, 6m, 30d or a date like 2024-01-31.",
        ) from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _delete_index(base: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        (base / INDEX_DIR / f"{INDEX_FILE}{suffix}").unlink(missing_ok=True)


class _RichProgress:
    """Progress bars on stderr, one per stage, with an ETA."""

    def __init__(self) -> None:
        self._bars = Progress(
            TextColumn("{task.description:<11}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TextColumn("eta"),
            TimeRemainingColumn(),
            console=err_console(),
            transient=False,
        )
        self._task: TaskID | None = None

    def __enter__(self) -> _RichProgress:
        self._bars.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._bars.stop()

    def stage(self, name: str, total: int) -> None:
        """Start a new bar (stages with nothing to do get none)."""
        self._task = self._bars.add_task(name, total=total) if total else None

    def advance(self, amount: int = 1) -> None:
        """Move the current bar."""
        if self._task is not None:
            self._bars.advance(self._task, amount)

    def note(self, message: str) -> None:
        """Print above the bars."""
        self._bars.console.print(message)
