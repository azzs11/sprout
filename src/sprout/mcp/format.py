"""Compact plain-text tool output for agents: cited, hash-first and under ~1,500 tokens.

Hashes are 12 characters, long enough to stay unique in large repositories and to paste
into ``git show``.
"""

from __future__ import annotations

from sprout.core.answer.reasons import has_body, vet_reason
from sprout.models import (
    AnswerMode,
    ChangedFile,
    CommitExplanation,
    Evidence,
    IssueRef,
    Label,
    RiskCard,
    RiskFinding,
    RiskKind,
    SearchHit,
    SearchResults,
    WhyAnswer,
)

HASH = 12
MAX_CHARS = 6_000  # about 1,500 tokens
_SUMMARY = 100
_QUOTE = 240
_BODIES = 3  # unchecked message bodies shown, for the top commits only
_ROLES = {
    "line_origin": "last changed this line",
    "line_history": "earlier change to this line",
    "symbol_history": "changed the same function",
    "revert": "revert",
    "related": "related",
}


def why_text(answer: WhyAnswer) -> str:
    """Render a ``WhyAnswer`` for an agent."""
    head = f"why {answer.target}"
    if answer.symbol:
        head += f" (in {answer.symbol})"
    source = (
        "written by a model; every sentence passed the citation check"
        if answer.mode is AnswerMode.LLM
        else "facts from git history, no model"
    )
    lines = [f"{head} @ {answer.as_of[:HASH]}", "", f"Answer ({source}):"]
    lines += [f"- {s.text} [{', '.join(h[:HASH] for h in s.citations)}]" for s in answer.sentences]
    if not answer.sentences:
        lines.append("- No history found for this target.")
    quotes = [_quote(e) for e in answer.evidence]
    lines += ["", f"Basis: {_basis(quotes)}", "", "Commits:"]
    for i, (e, quote) in enumerate(zip(answer.evidence, quotes, strict=True)):
        lines.append(_commit_line(e))
        if quote:
            lines.append(f'    reason: "{quote}"')
        elif i < _BODIES and (body := _body(e.commit.message)):
            lines.append(f'    message (not checked as a reason): "{body}"')
    lines += [f"Note: {n}" for n in answer.notes]
    return fit(lines)


def search_text(results: SearchResults) -> str:
    """Render ``SearchResults`` for an agent."""
    how = results.mode.value + (", reranked" if results.reranked else "")
    lines = [f'search "{results.query}" ({how}): {len(results.hits)} commits']
    lines += [f"Note: {n}" for n in results.notes]
    for hit in results.hits:
        lines.append(f"{hit.rank}. {_hit_line(hit)}")
        where = hit.symbols[:3] or hit.files[:3]
        if where:
            lines.append("   in " + ", ".join(where))
    if not results.hits:
        lines.append("No commits match. Try other words, or check the index with sprout doctor.")
    return fit(lines)


def commit_text(ex: CommitExplanation) -> str:
    """Render a ``CommitExplanation`` for an agent."""
    c = ex.commit
    flags = _flags(ex.labels, ex.refs, ex.reverted_by).lstrip("; ")
    lines = [
        f"commit {c.hash[:HASH]} {c.authored_at:%Y-%m-%d} {c.author.name}",
        c.summary + (f" ({flags})" if flags else ""),
    ]
    if ex.reverts:
        lines.append("This commit REVERTS " + ", ".join(h[:HASH] for h in ex.reverts) + ".")
    if not ex.indexed:
        lines.append("Note: no index, so commits that revert this one are unknown (sprout index).")
    lines.append(
        f'Reason, quoted from the message: "{_clip(ex.reason, _QUOTE)}"'
        if ex.reason
        else "Reason: the message does not state one; don't guess."
    )
    body = c.message.strip().partition("\n")[2].strip()
    if body:
        lines += ["", "Message:", *(f"  {ln}" for ln in body.splitlines()[:15])]
    more = " (more not listed)" if ex.files_truncated else ""
    lines += ["", f"Files ({len(ex.files)}{more}):", *(_file_line(f) for f in ex.files[:15])]
    if ex.patch:
        note = ", cut short" if ex.patch_truncated else ""
        note += f", {ex.redacted} secret(s) redacted" if ex.redacted else ""
        lines += ["", f"Diff (first parent{note}):", *ex.patch.splitlines()]
    return fit(lines)


def _file_line(f: ChangedFile) -> str:
    name = f"{f.old_path} -> {f.path}" if f.old_path and f.old_path != f.path else f.path
    where = f" in {', '.join(f.symbols[:4])}" if f.symbols else ""
    size = "binary" if f.binary else f"+{f.additions} -{f.deletions}"
    return f"  {f.kind.value} {name} {size}{where}"


_KINDS = {
    RiskKind.REAPPLIES_REVERTED: "re-applies code that this revert removed",
    RiskKind.REINTRODUCES_FIXED: "re-adds lines that this fix removed",
    RiskKind.REMOVES_FIX: "removes lines that this fix added",
    RiskKind.REMOVES_RESTORED: "removes code that this revert restored",
}


def risk_text(card: RiskCard) -> str:
    """Render a ``RiskCard`` as a verdict an agent can act on and quote."""
    if not card.findings:
        lines = [
            f"check_edit: PROCEED ({card.method}, no model). None of the {card.checked_lines}"
            " changed lines match a past fix, revert or security commit."
        ]
        return fit(lines + [f"Note: {note}" for note in card.notes])
    n = len(card.findings)
    lines = [
        f"check_edit: {card.verdict.value.upper()} (level: {card.level.value}; {card.method},"
        " no model; the level says what the change undoes, not how sure Sprout is)."
        f" {n} past commit{'s' if n > 1 else ''} warn{'' if n > 1 else 's'} against this change:",
    ]
    for f in card.findings[:5]:
        lines += _finding_lines(f)
    lines += [f"Note: {note}" for note in card.notes]
    lines.append(
        "What to do: read the cited commit with explain_commit. If you still make the change,"
        " tell the user which past fix or revert it undoes, and why that is fine now."
        if card.verdict.value == "review"
        else "What to do: stop and ask the user before making this change; cite the commits above."
    )
    return fit(lines)


def _finding_lines(f: RiskFinding) -> list[str]:
    c = f.commit
    tags = "".join(f"; {label.value}" for label in f.labels if label is not Label.MERGE)
    out = [
        f"- {c.hash[:HASH]} {c.authored_at:%Y-%m-%d} {c.author.name}: {_clip(c.summary, _SUMMARY)}"
        f" ({f.level.value}{tags})",
        f"  {_KINDS[f.kind]} ({f.matched} of {f.total} lines):",
        *(f"    {example}" for example in f.examples),
    ]
    if f.reverts:
        out.append("  it reverted " + ", ".join(h[:HASH] for h in f.reverts))
    if f.reason:
        out.append(f'  reason: "{_clip(f.reason, _QUOTE)}"')
    return out


def fit(lines: list[str], limit: int = MAX_CHARS) -> str:
    """Join ``lines``, dropping whole lines from the end to stay under ``limit`` characters."""
    out: list[str] = []
    size = 0
    for i, line in enumerate(lines):
        if size + len(line) + 1 > limit - 60:
            out.append(f"[{len(lines) - i} more lines cut to keep this short]")
            break
        out.append(line)
        size += len(line) + 1
    return "\n".join(out)


def _basis(quotes: list[str | None]) -> str:
    if quotes and quotes[0]:
        return "the top commit's message states the reason (quoted below)."
    if any(quotes):
        return "only related commits state a reason; the top commit does not."
    return (
        "no commit message states a reason Sprout's check accepts. Message text is shown as"
        " written: quote it, but don't call it the reason unless it says so, and don't guess."
    )


def _body(message: str) -> str | None:
    """The message after its subject line, clipped, when it says anything besides trailers."""
    if not has_body(message):
        return None
    return _clip(message.strip().partition("\n")[2], _QUOTE)


def _quote(e: Evidence) -> str | None:
    excerpt = vet_reason(None, e.commit.message).quote
    return _clip(excerpt, _QUOTE) if excerpt else None


def _commit_line(e: Evidence) -> str:
    c = e.commit
    text = f"{c.hash[:HASH]} {c.authored_at:%Y-%m-%d} {c.author.name}: {_clip(c.summary, _SUMMARY)}"
    return text + f" ({_ROLES[e.role.value]}{_flags(e.labels, e.refs, e.reverted_by)})"


def _hit_line(hit: SearchHit) -> str:
    c = hit.commit
    text = f"{c.hash[:HASH]} {c.authored_at:%Y-%m-%d} {c.author.name}: {_clip(c.summary, _SUMMARY)}"
    flags = _flags(hit.labels, hit.refs, hit.reverted_by).lstrip("; ")
    return text + (f" ({flags})" if flags else "")


def _flags(labels: list[Label], refs: list[IssueRef], reverted_by: list[str]) -> str:
    parts = [label.value for label in labels if label is not Label.MERGE]
    parts += [f"#{r.number}" for r in refs[:3]]
    if reverted_by:
        parts.append("REVERTED by " + ", ".join(h[:HASH] for h in reverted_by))
    return "".join(f"; {p}" for p in parts)


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
