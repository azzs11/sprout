"""``sprout why``: explain a line of code, or answer a question, with cited commits."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sprout import services
from sprout.cli.output import JsonOption, RepoOption, emit, handle_errors
from sprout.config import load_settings
from sprout.core.answer.target import why_target
from sprout.core.answer.why import Models, WhyOptions
from sprout.core.git import open_repo
from sprout.core.git.pygit2_repo import Pygit2Repo
from sprout.core.index.store import Store
from sprout.errors import IndexNotFoundError
from sprout.models import AnswerMode, EvidenceRole, WhyAnswer

_ROLE_NAMES = {
    EvidenceRole.LINE_ORIGIN: "this line",
    EvidenceRole.LINE_HISTORY: "earlier line",
    EvidenceRole.SYMBOL_HISTORY: "same code",
    EvidenceRole.REVERT: "revert",
    EvidenceRole.RELATED: "related",
}


def why(
    target: Annotated[
        str, typer.Argument(help="A line like src/auth.py:42, or a question in quotes.")
    ],
    repo: RepoOption = Path(),
    at: Annotated[
        str | None, typer.Option("--at", help="Ask as of this commit, branch or tag.")
    ] = None,
    no_llm: Annotated[
        bool, typer.Option("--no-llm", help="Facts only: never call a language model.")
    ] = False,
    limit: Annotated[int, typer.Option("--limit", "-n", min=1, max=30)] = 8,
    as_json: JsonOption = False,
) -> None:
    """Explain why code is the way it is, citing the commits that prove it."""
    with handle_errors(as_json=as_json):
        git = open_repo(repo)
        settings = load_settings(git.root)
        store = _open_store(git)
        answerer, note = (None, None) if no_llm else services.build_answerer(settings)
        models = Models(
            answerer=answerer,
            embedder=services.build_embedder(settings),
            reranker=services.build_reranker(settings),
        )
        answer = why_target(
            git, store, target, cwd=repo, rev=at, models=models, options=WhyOptions(limit=limit)
        )
        if store is not None:
            store.close()
        if note:
            answer = answer.model_copy(update={"notes": [*answer.notes, note]})
        emit(answer, as_json=as_json, render=render_answer)


def render_answer(answer: WhyAnswer, out: Console) -> None:
    """Render a ``WhyAnswer``: cited sentences, then the evidence table."""
    body = Text()
    for i, sentence in enumerate(answer.sentences):
        if i:
            body.append("\n")
        body.append(sentence.text)
        body.append(" " + " ".join(f"[{h[:7]}]" for h in sentence.citations), style="yellow")
    title = answer.target + (f"  ({answer.symbol})" if answer.symbol else "")
    subtitle = (
        "written by " + answer.model.split("|")[0]
        if answer.mode is AnswerMode.LLM and answer.model
        else "facts from history"
    )
    out.print(
        Panel(
            body or Text("No history found.", style="dim"),
            title=title,
            subtitle=subtitle,
            title_align="left",
            subtitle_align="right",
        )
    )
    if answer.evidence:
        out.print(_evidence_table(answer))
    for note in answer.notes:
        out.print(Text(note, style="dim"))


def _evidence_table(answer: WhyAnswer) -> Group:
    table = Table(box=None, pad_edge=False, show_header=True, header_style="dim")
    table.add_column("commit", style="yellow", no_wrap=True)
    table.add_column("date", style="dim", no_wrap=True)
    table.add_column("role", no_wrap=True)
    table.add_column("summary", overflow="fold")
    for e in answer.evidence:
        summary = Text(e.commit.summary)
        if e.reverted_by:
            summary.append("  reverted", style="bold red")
        if e.reasons:
            summary.append("\n" + "; ".join(e.reasons[:2]), style="dim")
        table.add_row(
            e.commit.short_hash, f"{e.commit.authored_at:%Y-%m-%d}", _ROLE_NAMES[e.role], summary
        )
    return Group(Text("Evidence", style="bold"), table)


def _open_store(git: Pygit2Repo) -> Store | None:
    try:
        return Store.open(git.root, create=False)
    except IndexNotFoundError:
        return None
