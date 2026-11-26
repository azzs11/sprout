"""``sprout commit``: draft a message for the staged changes. It never runs ``git commit``."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from sprout import services
from sprout.cli.output import JsonOption, RepoOption, console, emit, err_console, handle_errors
from sprout.config import load_settings
from sprout.core.commit.message import draft_message, with_why
from sprout.core.commit.state import pending_operation
from sprout.core.git import open_repo
from sprout.core.git.pygit2_repo import Pygit2Repo
from sprout.models import CommitDraft, DraftSource


def commit(
    repo: RepoOption = Path(),
    why: Annotated[
        str | None,
        typer.Option("--why", help="Why this change is needed; kept word for word in Why:."),
    ] = None,
    fixes: Annotated[
        list[int] | None,
        typer.Option(
            "--fixes", metavar="N", help="Issue this closes (Fixes: #N). Repeat for more."
        ),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write the message here, for: git commit -F FILE."),
    ] = None,
    ask: Annotated[
        bool | None,
        typer.Option("--ask/--no-ask", help="Ask the why question (default: in a terminal)."),
    ] = None,
    no_llm: Annotated[
        bool, typer.Option("--no-llm", help="Never call a language model; draft a skeleton.")
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Draft a commit message for the staged changes, asking you one question about why.

    Sprout prints the message; you commit it, e.g. with git commit -F FILE.
    """
    with handle_errors(as_json=as_json):
        git = open_repo(repo)
        draft = _draft(git, why=why, fixes=fixes or [], no_llm=no_llm)
        if why is None and _should_ask(ask, as_json=as_json):
            draft = with_why(draft, _ask(draft))
        if output is not None:
            output.write_text(draft.message, encoding="utf-8")
        _emit(draft, output=output, as_json=as_json)


def _draft(git: Pygit2Repo, *, why: str | None, fixes: list[int], no_llm: bool) -> CommitDraft:
    """The draft plus notes about the model and any merge or rebase in progress."""
    settings = load_settings(git.root)
    writer, note = (None, None) if no_llm else services.build_commit_writer(settings)
    draft = draft_message(git, git.diff(staged=True), writer=writer, why=why, fixes=fixes)
    notes = [*draft.notes, *([note] if note else [])]
    operation = pending_operation(git.git_dir)
    if operation:
        notes.append(f"A {operation} is in progress; git already prepared its message.")
    return draft.model_copy(update={"notes": notes})


def _should_ask(ask: bool | None, *, as_json: bool) -> bool:
    if ask is not None:
        return ask
    return not as_json and sys.stdin.isatty() and sys.stdout.isatty()


def _ask(draft: CommitDraft) -> str:
    err = err_console()
    err.print(Text(draft.question, style="bold"))
    return typer.prompt("Why (Enter to skip)", default="", show_default=False, err=True)


def _emit(draft: CommitDraft, *, output: Path | None, as_json: bool) -> None:
    if as_json:
        emit(draft, as_json=True, render=render_draft)
    elif output is not None or sys.stdout.isatty():
        render_draft(draft, console(), output=output)
    else:  # piped: the bare message, so `git commit -F <(sprout commit ...)` works
        typer.echo(draft.message, nl=False)
        for line in draft.notes:
            typer.echo(line, err=True)


def render_draft(draft: CommitDraft, out: Console, *, output: Path | None = None) -> None:
    """The message in a panel, then where it came from and what to do next."""
    source = (
        "written by " + draft.model.split("|")[0]
        if draft.source is DraftSource.MODEL and draft.model
        else "skeleton, no model"
    )
    out.print(Panel(Text(draft.message.rstrip()), title="commit message", subtitle=source,
                    title_align="left", subtitle_align="right"))  # fmt: skip
    lines = [Text(n, style="dim") for n in draft.notes]
    if draft.why is None:
        lines.append(Text("No Why: trailer; pass --why to keep the reason.", style="dim"))
    if draft.redacted and draft.source is DraftSource.MODEL:
        lines.append(Text(f"{draft.redacted} secret(s) hidden from the model.", style="dim"))
    target = str(output) if output else "FILE"
    for line in lines:
        out.print(line)
    # Never wrapped, so the command can be copied as one line.
    out.print(Text(f"Commit with: git commit -F {target}", style="bold"), soft_wrap=True)
