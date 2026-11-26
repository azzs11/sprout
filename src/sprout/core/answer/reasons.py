"""Decide, without a model, whether a "reason" sentence may be shown for a commit.

The citation checker proves a quote appears somewhere in the evidence. Judging kept sentences
on WhyBench showed that this is not enough: small models quote the subject line ("what") as the
reason, quote code from the diff, or say no reason is given when the body explains it. So a
reason is shown only when it is copied from the commit *message* and actually states a cause.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sprout.core.answer.rationale import score_message, states_reason
from sprout.core.git.message import why_trailer

_PR_NUMBER = re.compile(r"\s*\(#\d+\)\s*$")
_PREFIX = re.compile(r"^[\w-]+(?:\([^)]*\))?!?:\s*")
_REF_ONLY = re.compile(
    r"^(?:this\s+)?(?:fix(?:es|ed)?|close[sd]?|resolve[sd]?|see|refs?)?\s*:?\s*"
    r"(?:#\d+[\s,]*(?:and\s+)?)+\.?$",
    re.IGNORECASE,
)
_TRAILER = re.compile(r"^[\w-]+(?:-by)?:\s|^--HG--|^branch\s*:", re.IGNORECASE)
_BULLET = re.compile(r"^\s*[*-]\s")
MIN_REASON_WORDS = 3
# Recorded in the answer's model id; bump when the rules change. 1.1 = @1 plus Why: trailers,
# which no bench repo uses, so published reasons@1 numbers still hold.
GATE_ID = "reasons@1.1"


@dataclass(frozen=True)
class Reason:
    """What to say about a commit's reason: a verbatim quote, "none stated", or nothing."""

    quote: str | None
    none_stated: bool = False


def _norm(text: str) -> str:
    return " ".join(text.split()).strip(" .\"'“”").lower()


def _subject(message: str) -> str:
    first = message.strip().partition("\n")[0]
    return _norm(_PREFIX.sub("", _PR_NUMBER.sub("", first)))


def has_body(message: str) -> bool:
    """True when the message has text after the subject line, ignoring trailers."""
    _, _, body = message.strip().partition("\n")
    return any(line.strip() and not _TRAILER.match(line.strip()) for line in body.splitlines())


def acceptable(quote: str, message: str) -> bool:
    """A quote copied from ``message`` that states a cause, not just what changed."""
    text = _norm(quote)
    if len(text.split()) < MIN_REASON_WORDS or _REF_ONLY.match(text):
        return False
    if text not in _norm(message):
        return False
    restates_subject = text in _subject(message) or _subject(message) in text
    if restates_subject or _BULLET.match(quote):  # a "what"; only a stated cause makes it a why
        return states_reason(quote, strong=True)
    return True


def vet_reason(quote: str | None, message: str) -> Reason:
    """The author's ``Why:``, else the model's quote, else Sprout's excerpt, else what is safe.

    A ``Why:`` trailer is the author's own statement, so it is shown as given.
    """
    stated = why_trailer(message)
    if stated:
        return Reason(stated)
    if quote and acceptable(quote, message):
        return Reason(quote)
    excerpt = score_message(message, labels=[], refs=0).excerpt
    if excerpt and states_reason(excerpt) and acceptable(excerpt, message):
        return Reason(excerpt)
    return Reason(None, none_stated=not has_body(message))
