"""A risk card as a GitHub pull request comment (``sprout risk --markdown``).

Commit messages are not trusted: anything that could ping people (``@name``), open HTML or
break out of a table cell or code block is escaped. Plain hashes are left bare so GitHub links
them to the commit.
"""

from __future__ import annotations

import re

from sprout.models import Label, RiskCard, RiskFinding, RiskKind, RiskLevel

MARKER = "<!-- sprout-risk -->"
HASH = 12
_LEVEL = {RiskLevel.REVIEW: "! review", RiskLevel.HIGH: "▲ high", RiskLevel.LOW: "✓ low"}
_KIND = {
    RiskKind.REAPPLIES_REVERTED: "re-applies code that this revert removed",
    RiskKind.REINTRODUCES_FIXED: "re-adds lines that this fix removed",
    RiskKind.REMOVES_FIX: "removes lines that this fix added",
    RiskKind.REMOVES_RESTORED: "removes code that this revert restored",
}
_MENTION = re.compile(r"@(?=[\w-])")


def card_markdown(card: RiskCard) -> str:
    """The comment body, or an empty string when there is nothing to cite."""
    if not card.findings:
        return ""
    n = len(card.findings)
    who = f"{n} past commits warn" if n > 1 else "1 past commit warns"
    out = [
        MARKER,
        f"### Sprout history check: {_LEVEL[card.level]}",
        "",
        f"{who} against this change. Matched on changed lines with `{card.method}`; no model"
        " was used. The level says what the change undoes, not how sure Sprout is.",
        "",
        "| Level | Commit | This change |",
        "|---|---|---|",
    ]
    out += [_row(f) for f in card.findings]
    out += ["", "<details><summary>Matching lines and stated reasons</summary>", ""]
    for f in card.findings:
        out += _detail(f)
    out += ["</details>", ""]
    out += [f"_{_text(note)}_" for note in card.notes]
    first = card.findings[0].commit.hash[:7]
    out += [
        "",
        "If the change is intended, say why in the pull request. To stop this warning for good,"
        f' run `sprout ack {first} -m "why"` and commit `.sprout-acks.toml`.',
    ]
    return "\n".join(out) + "\n"


def _row(f: RiskFinding) -> str:
    tag = " (security)" if Label.SECURITY in f.labels else ""
    commit = f"{f.commit.hash[:HASH]} {_text(f.commit.summary)}"
    return (
        f"| {_LEVEL[f.level]}{tag} | {commit} | {_KIND[f.kind]} ({f.matched} of {f.total} lines) |"
    )


def _detail(f: RiskFinding) -> list[str]:
    out = [f"**{f.commit.hash[:HASH]}** ({f.commit.authored_at:%Y-%m-%d})", "", "````diff"]
    out += [example.replace("````", "` ` ` `") for example in f.examples]
    out.append("````")
    if f.reverts:
        out.append("It reverted " + ", ".join(h[:HASH] for h in f.reverts) + ".")
    if f.reason:
        out.append(f"Reason given: “{_text(f.reason)}”")
    out.append("")
    return out


def _text(value: str) -> str:
    """Safe inside a table cell or paragraph: no mentions, HTML or cell breaks."""
    value = " ".join(value.split())
    value = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    value = value.replace("|", "\\|")
    return _MENTION.sub("@​", value)
