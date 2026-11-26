"""Parse commit messages: Conventional Commit type, issue refs, reverts and labels.

Pure functions with no git access, so they are cheap to test exhaustively.
"""

from __future__ import annotations

import re

from sprout.models import IssueRef, Label, MessageInfo

_CONVENTIONAL = re.compile(r"^(?P<type>[a-zA-Z]+)(?:\((?P<scope>[^()\n]+)\))?(?P<bang>!)?:\s")
_REVERT_HASH = re.compile(
    r"(?:This reverts commit |^Reverts:[ \t]*)(?P<hash>[0-9a-f]{7,40})\b",
    re.IGNORECASE | re.MULTILINE,
)
_WHY = re.compile(r"^Why:[ \t]*(?P<first>\S.*)\n?(?P<more>(?:[ \t]+\S.*\n?)*)", re.MULTILINE)
_REVERT_SUBJECT = re.compile(r'^Revert\s+"(?P<summary>.+)"(?:\s*\(#\d+\))?\s*$')
_REF = re.compile(
    r"(?<![\w/#&.:])"
    r"(?:(?P<keyword>close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+)?"
    r"(?:(?P<repo>[A-Za-z0-9][\w.-]*/[\w.-]+)#|#|GH-)"
    r"(?P<number>\d{1,7})\b",
    re.IGNORECASE,
)
_FIX_WORDS = re.compile(r"\b(fix(e[sd])?|bug|hotfix|regression|crash|broken)\b", re.IGNORECASE)
_SECURITY_WORDS = re.compile(
    r"\b(security|vulnerab\w*|CVE-\d{4}-\d+|GHSA-[\w-]+|XSS|CSRF|SSRF|injection|exploit"
    r"|timing[- ]attacks?|path traversal|privilege escalation|auth(?:entication)? bypass|RCE)\b",
    re.IGNORECASE,
)
_BREAKING = re.compile(r"^BREAKING[ -]CHANGE:", re.MULTILINE)


def parse_message(message: str, *, is_merge: bool = False) -> MessageInfo:
    """Read type, scope, refs, reverts and labels from a commit message."""
    subject = message.split("\n", 1)[0].strip()
    conventional = _CONVENTIONAL.match(subject)
    ctype = conventional["type"].lower() if conventional else None
    scope = conventional["scope"] if conventional else None
    reverts = list(dict.fromkeys(m["hash"].lower() for m in _REVERT_HASH.finditer(message)))
    quoted = _REVERT_SUBJECT.match(subject)
    labels = _labels(
        message,
        subject=subject,
        ctype=ctype,
        breaking=bool(conventional and conventional["bang"]) or bool(_BREAKING.search(message)),
        is_revert=bool(reverts or quoted or ctype == "revert"),
        is_merge=is_merge,
    )
    return MessageInfo(
        conventional_type=ctype,
        scope=scope,
        labels=labels,
        refs=parse_refs(message),
        reverts=reverts,
        reverts_summary=quoted["summary"] if quoted else None,
    )


def why_trailer(message: str) -> str | None:
    """The author's reason from a ``Why:`` trailer (continuation lines joined), if any."""
    paragraphs = [p for p in message.replace("\r\n", "\n").strip().split("\n\n") if p.strip()]
    if len(paragraphs) < 2:
        return None
    match = _WHY.search(paragraphs[-1] + "\n")
    return " ".join(f"{match['first']} {match['more']}".split()) if match else None


def parse_refs(message: str) -> list[IssueRef]:
    """Find issue and pull-request references, de-duplicated in order of appearance."""
    found: dict[tuple[str | None, int], IssueRef] = {}
    for match in _REF.finditer(message):
        repo = match["repo"]
        key = (repo, int(match["number"]))
        closes = match["keyword"] is not None
        if key in found:
            closes = closes or found[key].closes
        found[key] = IssueRef(number=key[1], repo=repo, closes=closes)
    return list(found.values())


def _labels(
    message: str,
    *,
    subject: str,
    ctype: str | None,
    breaking: bool,
    is_revert: bool,
    is_merge: bool,
) -> list[Label]:
    labels: list[Label] = []
    if ctype == "fix" or (ctype is None and _FIX_WORDS.search(subject)):
        labels.append(Label.FIX)
    if ctype == "security" or _SECURITY_WORDS.search(message):
        labels.append(Label.SECURITY)
    if is_revert:
        labels.append(Label.REVERT)
    if is_merge:
        labels.append(Label.MERGE)
    if breaking:
        labels.append(Label.BREAKING)
    return labels
