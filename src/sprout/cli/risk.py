"""``sprout risk``: does history warn against this change? Advisory unless asked to block."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.text import Text

from sprout.cli.output import JsonOption, RepoOption, emit, handle_errors
from sprout.cli.risk_markdown import card_markdown
from sprout.core.git import open_repo
from sprout.core.index.store import Store
from sprout.core.risk import acks
from sprout.core.risk.check import check_changes
from sprout.core.risk.patch import parse_unified
from sprout.models import Label, RiskCard, RiskFinding, RiskKind, RiskLevel, Verdict

BLOCKED = 2
_LEVEL = {
    RiskLevel.LOW: "✓ low",
    RiskLevel.REVIEW: "! review",
    RiskLevel.HIGH: "▲ high",
}
_KIND = {
    RiskKind.REAPPLIES_REVERTED: "re-applies code this revert removed",
    RiskKind.REINTRODUCES_FIXED: "re-adds lines this fix removed",
    RiskKind.REMOVES_FIX: "removes lines this fix added",
    RiskKind.REMOVES_RESTORED: "removes code this revert restored",
}


def risk(
    repo: RepoOption = Path(),
    staged: Annotated[
        bool, typer.Option("--staged", help="Check staged changes only (what git commit takes).")
    ] = False,
    diff: Annotated[
        Path | None,
        typer.Option("--diff", help="Check a unified diff file instead ('-' reads stdin)."),
    ] = None,
    level: Annotated[
        RiskLevel, typer.Option(help="Lowest level to show: review (default) or high.")
    ] = RiskLevel.REVIEW,
    strict: Annotated[
        bool, typer.Option("--strict", help="Exit 2 on any warning, not only on security fixes.")
    ] = False,
    markdown: Annotated[
        bool,
        typer.Option("--markdown", help="Print a pull request comment (nothing if no findings)."),
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Check uncommitted changes against past fixes, reverts and security commits."""
    if os.environ.get("SPROUT_SKIP") == "1":
        typer.echo("Sprout risk check skipped (SPROUT_SKIP=1).", err=True)
        return
    with handle_errors(as_json=as_json):
        git = open_repo(repo)
        if diff is None:
            changed = git.uncommitted_lines(staged_only=staged)
        else:
            text = sys.stdin.read() if str(diff) == "-" else diff.read_text(encoding="utf-8")
            changed = parse_unified(text)
        with Store.open(git.root, create=False) as store:
            ignore = frozenset(a.commit for a in acks.load(git.root))
            card = at_level(check_changes(store, changed, ignore=ignore), level)
        if markdown and not as_json:
            typer.echo(card_markdown(card), nl=False)
        else:
            emit(card, as_json=as_json, render=render_card)
    if blocks(card, strict=strict):
        raise typer.Exit(code=BLOCKED)


def at_level(card: RiskCard, level: RiskLevel) -> RiskCard:
    """Keep findings at ``level`` or above; the card's level follows what is kept."""
    if level is not RiskLevel.HIGH:
        return card
    kept = [f for f in card.findings if f.level is RiskLevel.HIGH]
    if len(kept) == len(card.findings):
        return card
    hidden = len(card.findings) - len(kept)
    note = f"{hidden} review-level finding{'s' if hidden > 1 else ''} hidden by --level high."
    return card.model_copy(
        update={
            "findings": kept,
            "level": RiskLevel.HIGH if kept else RiskLevel.LOW,
            "verdict": card.verdict if kept else Verdict.PROCEED,
            "notes": [*card.notes, note],
        }
    )


def blocks(card: RiskCard, *, strict: bool) -> bool:
    """Exit 2 in strict mode on any finding, and always when a past security fix is involved."""
    if strict:
        return bool(card.findings)
    return any(Label.SECURITY in f.labels for f in card.findings)


def render_card(card: RiskCard, out: Console) -> None:
    """Render a ``RiskCard``: the level as a word, then 1-3 explaining commits."""
    if not card.checked_lines:
        out.print("No changed lines to check.")
    elif not card.findings and any(" hidden by " in n for n in card.notes):
        out.print(f"{_LEVEL[RiskLevel.LOW]}: no findings left to show (see below).")
    elif not card.findings:
        out.print(
            f"{_LEVEL[RiskLevel.LOW]}: none of the {card.checked_lines} changed lines match a past"
            " fix, revert or security commit."
        )
    else:
        n = len(card.findings)
        who = f"{n} past commits warn" if n > 1 else "1 past commit warns"
        head = Text(f"Risk: {_LEVEL[card.level]}", style="bold")
        head.append(f"  ({who} against this change)")
        out.print(head)
        for finding in card.findings[:3]:
            out.print(_finding_text(finding))
        if len(card.findings) > 3:
            out.print(Text(f"  and {len(card.findings) - 3} more (use --json)", style="dim"))
    for note in card.notes:
        out.print(Text(note, style="dim"))


def _finding_text(f: RiskFinding) -> Text:
    c = f.commit
    text = Text("\n  ")
    text.append(c.short_hash, style="yellow")
    text.append(f" {c.authored_at:%Y-%m-%d} {c.author.name}: {c.summary}")
    if Label.SECURITY in f.labels:
        text.append("  [security]", style="bold")
    text.append(f"\n    {_KIND[f.kind]} ({f.matched} of {f.total} lines)")
    for example in f.examples:
        text.append(f"\n      {example}", style="dim")
    if f.reverts:
        text.append("\n    it reverted " + ", ".join(h[:7] for h in f.reverts))
    if f.reason:
        text.append(f'\n    reason: "{f.reason}"')
    return text
