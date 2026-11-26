"""Scores for one drafted message against the repository's style and the real message.

All deterministic. ROUGE-L compares words with the real subject, which rewards wording
the author happened to choose, so it is reported with that caveat and is not the headline.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from sprout.core.answer.rationale import states_reason
from sprout.core.commit.subject import subject_limit
from sprout.core.git.message import parse_message
from sprout.models import CommitStyle

_WORD = re.compile(r"[a-z0-9]+")
_PREFIX = re.compile(r"^[a-zA-Z]+(?:\([^()\n]*\))?!?:\s*")
_ASKS_WHAT = re.compile(r"\bwhat (?:changes?|was changed|were)\b", re.IGNORECASE)
RESTATE_JACCARD = 0.6


def words(text: str) -> list[str]:
    """Lower-case alphanumeric tokens."""
    return _WORD.findall(text.lower())


def rouge_l(candidate: str, reference: str) -> float:
    """ROUGE-L F1 over words (longest common subsequence)."""
    a, b = words(candidate), words(reference)
    if not a or not b:
        return 0.0
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b):
            cur.append(prev[j] + 1 if x == y else max(prev[j + 1], cur[j]))
        prev = cur
    lcs = prev[-1]
    if lcs == 0:
        return 0.0
    precision, recall = lcs / len(a), lcs / len(b)
    return 2 * precision * recall / (precision + recall)


def style_checks(subject: str, real: str, style: CommitStyle) -> dict[str, bool]:
    """Does ``subject`` format like the author's own subject for this commit?

    Prefix, capitalisation and full stop are compared with the author's subject, not with
    Sprout's learned style, so Sprout is not scored against its own rules. Length is checked
    against the repository's 90th percentile before the commit.
    """
    has_prefix = bool(parse_message(subject).conventional_type)
    first, real_first = _first(subject), _first(real)
    return {
        "prefix": has_prefix == bool(parse_message(real).conventional_type),
        "capital": not (first.isalpha() and real_first.isalpha())
        or first.isupper() == real_first.isupper(),
        "period": subject.endswith(".") == real.endswith("."),
        "length": len(subject) <= subject_limit(style),
    }


def style_score(subject: str, real: str, style: CommitStyle) -> float:
    """Share of ``style_checks`` passed."""
    checks = style_checks(subject, real, style)
    return sum(checks.values()) / len(checks)


def _first(subject: str) -> str:
    return _PREFIX.sub("", subject, count=1)[:1]


def type_match(subject: str, real_subject: str) -> bool | None:
    """Same Conventional Commit type as the real one; None when the real one has none."""
    real = parse_message(real_subject).conventional_type
    if real is None:
        return None
    return parse_message(subject).conventional_type == real


def restates_subject(subject: str, body: str | None) -> bool:
    """The body's first line says the same words as the subject."""
    if not body:
        return False
    first = set(words(body.strip().splitlines()[0]))
    sub = set(words(_PREFIX.sub("", subject, count=1)))
    if not first or not sub:
        return False
    return len(first & sub) / len(first | sub) >= RESTATE_JACCARD


def gives_reason(subject: str, body: str | None) -> bool:
    """The message states a cause: a strong causal word, as in the reasons gate."""
    parts = (subject, *(body or "").splitlines())
    return any(states_reason(p, strong=True) for p in parts if p)


def asks_why(question: str | None) -> bool:
    """The question is about the reason, not about what changed."""
    if not question:
        return False
    return "why" in words(question) and not _ASKS_WHAT.search(question)


def mean(values: Sequence[float]) -> float | None:
    """Average, or None for no values."""
    return round(sum(values) / len(values), 3) if values else None
