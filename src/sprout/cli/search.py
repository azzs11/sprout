"""``sprout search``: find the commits that best match a question."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from sprout import services
from sprout.cli.output import JsonOption, RepoOption, emit, handle_errors
from sprout.config import load_settings
from sprout.core.git import open_repo
from sprout.core.index.store import Store
from sprout.core.retrieve.hybrid import search as run_search
from sprout.models import Label, SearchHit, SearchMode, SearchResults


def search(
    query: Annotated[
        str, typer.Argument(help='What to look for, e.g. "why do we retry payments".')
    ],
    repo: RepoOption = Path(),
    limit: Annotated[int, typer.Option("--limit", "-n", min=1, max=100)] = 10,
    mode: Annotated[SearchMode, typer.Option(help="Which retrievers to use.")] = SearchMode.HYBRID,
    no_rerank: Annotated[bool, typer.Option("--no-rerank", help="Skip the cross-encoder.")] = False,
    as_json: JsonOption = False,
) -> None:
    """Search the history index (build it first with sprout index)."""
    with handle_errors(as_json=as_json):
        git = open_repo(repo)
        base = git.root  # the work tree, or the git dir itself for bare repositories
        settings = load_settings(git.root)
        embedder = None if mode is SearchMode.BM25 else services.build_embedder(settings)
        reranker = None if no_rerank else services.build_reranker(settings)
        with Store.open(base, create=False) as store:
            results = run_search(
                store, query, mode=mode, limit=limit, embedder=embedder, reranker=reranker
            )
        emit(results, as_json=as_json, render=render_results)


def render_results(results: SearchResults, out: Console) -> None:
    """Render ``SearchResults`` for people."""
    for note in results.notes:
        out.print(Text(note, style="dim"))
    if not results.hits:
        out.print(f"No commits match {results.query!r}.")
        return
    table = Table(box=None, pad_edge=False, show_header=True)
    table.add_column("#", justify="right", style="dim")
    table.add_column("commit", style="yellow", no_wrap=True)
    table.add_column("date", style="dim", no_wrap=True)
    table.add_column("summary", overflow="fold")
    for hit in results.hits:
        table.add_row(
            str(hit.rank),
            hit.commit.short_hash,
            hit.commit.authored_at.strftime("%Y-%m-%d"),
            _describe(hit),
        )
    out.print(table)


def _describe(hit: SearchHit) -> Text:
    text = Text(hit.commit.summary)
    if hit.reverted_by:
        text.append("  reverted", style="bold red")
        text.append(f" by {', '.join(h[:7] for h in hit.reverted_by)}", style="red")
    tags = [label.value for label in hit.labels if label is not Label.MERGE]
    if tags:
        text.append(f"  [{', '.join(tags)}]", style="cyan")
    where = hit.symbols[:3] or hit.files[:3]
    if where:
        text.append("\n" + ", ".join(where), style="dim")
    return text
