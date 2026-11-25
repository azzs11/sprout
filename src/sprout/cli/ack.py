"""``sprout ack`` and ``sprout supersede``: switch off warnings about a commit, saying why."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from sprout.cli.output import JsonOption, RepoOption, emit, handle_errors
from sprout.core.git import open_repo
from sprout.core.git.pygit2_repo import Pygit2Repo
from sprout.core.index.store import Store
from sprout.core.risk import acks
from sprout.errors import IndexNotFoundError, SproutError
from sprout.models import Ack, AckKind, AckList

ReasonOption = Annotated[
    str | None, typer.Option("--reason", "-m", help="Why the warning no longer applies.")
]
_SIGNALS = ('"fix"', '"security"', '"revert"')


def ack(
    commit: Annotated[
        str | None, typer.Argument(help="The fix, security or revert commit to stop citing.")
    ] = None,
    reason: ReasonOption = None,
    remove: Annotated[
        bool, typer.Option("--remove", help="Turn this commit's warnings back on.")
    ] = False,
    repo: RepoOption = Path(),
    as_json: JsonOption = False,
) -> None:
    """Stop warning about a commit whose risk is known and accepted (no commit: list all)."""
    with handle_errors(as_json=as_json):
        git = open_repo(repo)
        entries = acks.load(git.root)
        if commit is not None:
            full = git.resolve(commit)
            if remove:
                entries = [a for a in entries if a.commit != full]
            else:
                entries = acks.upsert(entries, _new(git, full, AckKind.ACK, reason, None))
            acks.save(git.root, entries)
        emit(_listing(git, entries), as_json=as_json, render=render_acks)


def supersede(
    commit: Annotated[str, typer.Argument(help="The fix or revert that no longer applies.")],
    reason: ReasonOption = None,
    by: Annotated[
        str | None, typer.Option("--by", help="The commit that replaced it, if there is one.")
    ] = None,
    repo: RepoOption = Path(),
    as_json: JsonOption = False,
) -> None:
    """Stop warning about a fix or revert that a later change made obsolete."""
    with handle_errors(as_json=as_json):
        git = open_repo(repo)
        full = git.resolve(commit)
        replaced = git.resolve(by) if by else None
        entries = acks.upsert(
            acks.load(git.root), _new(git, full, AckKind.SUPERSEDE, reason, replaced)
        )
        acks.save(git.root, entries)
        emit(_listing(git, entries), as_json=as_json, render=render_acks)


def _new(
    git: Pygit2Repo, commit: str, kind: AckKind, reason: str | None, replaced: str | None
) -> Ack:
    if not reason or not reason.strip():
        raise SproutError(
            "Say why the warning no longer applies.",
            hint=f'sprout {kind.value} {commit[:7]} -m "the reason, for whoever reads this later"',
        )
    _require_signal(git, commit)
    return Ack(
        commit=commit,
        kind=kind,
        reason=" ".join(reason.split()),
        by=git.user_name or "unknown",
        date=datetime.now(UTC).strftime("%Y-%m-%d"),
        superseded_by=replaced,
    )


def _require_signal(git: Pygit2Repo, commit: str) -> None:
    """Refuse commits Sprout never cites, so an entry is never silently useless."""
    try:
        with Store.open(git.root, create=False) as store:
            row = store.db.execute(
                "SELECT labels FROM commits WHERE hash = ?", (commit,)
            ).fetchone()
    except IndexNotFoundError:
        return  # cannot tell without an index; accept it
    labels = str(row[0]) if row else ""  # a JSON list such as ["fix"]
    if not any(s in labels for s in _SIGNALS):
        raise SproutError(
            f"{commit[:7]} is not a fix, security or revert commit,"
            " so Sprout never warns about it.",
            hint="Pass the commit a warning cites (the hash shown by sprout risk).",
        )


def _listing(git: Pygit2Repo, entries: list[Ack]) -> AckList:
    return AckList(path=str(git.root / acks.ACK_FILE), acks=entries)


def render_acks(listing: AckList, out: Console) -> None:
    """Render ``.sprout-acks.toml``."""
    if not listing.acks:
        out.print("No acknowledged commits: every warning is on.")
        return
    table = Table(box=None, pad_edge=False, show_header=True, header_style="dim")
    for column in ("commit", "kind", "date", "by", "reason"):
        table.add_column(column, overflow="fold")
    for a in listing.acks:
        reason = a.reason + (f" (replaced by {a.superseded_by[:7]})" if a.superseded_by else "")
        table.add_row(Text(a.commit[:7], style="yellow"), a.kind.value, a.date, a.by, reason)
    out.print(table)
    out.print(Text(f"Stored in {listing.path}; commit it to share with your team.", style="dim"))
