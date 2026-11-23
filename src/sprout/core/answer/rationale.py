"""Score how clearly a commit message states *why* a change was made.

Heuristic and explainable on purpose: every point comes with a short reason that the CLI and
MCP tools can show, and WhyBench measures how well the ranking works.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sprout.models import Label

# Words that explain *why* (strong) versus words that describe *what happened* (weak).
_STRONG = re.compile(
    r"\b(because|so that|so we|in order to|to avoid|to prevent|prevents?|otherwise|due to"
    r"|caused by|workaround|work around|needed for|required by|instead of|rather than"
    r"|the reason|the idea|the goal|this way|why)\b",
    re.IGNORECASE,
)
_WEAK = re.compile(
    r"\b(since|causes?|causing|regression|broke|breaks|broken|fails?|failing|failed"
    r"|crash(?:es|ed)?|bug|issue|security|vulnerab\w*)\b",
    re.IGNORECASE,
)
STRONG_WEIGHT = 1.5
WEAK_WEIGHT = 0.5
_NOISE = re.compile(
    r"^(?:style|ci|build|chore\(deps\))(?:\(|:)"
    r"|\b(typo|formatting|format code|reformat|black|isort|ruff|prettier|lint(?:ing)?|whitespace"
    r"|rename[ds]?|bump(?:ed)?|merge branch|merge pull request|cleanup|clean up|pre-commit"
    r"|pep8|pep 8|flake8|pyupgrade|codespell|mypy|eslint|rustfmt|gofmt|clippy"
    r"|autoupdate|update copyright)\b",
    re.IGNORECASE,
)
_BOILERPLATE = re.compile(
    r"(this reverts commit|signed-off-by:|co-authored-by:|reviewed-by:|change-id:"
    r"|merge (branch|pull))",
    re.IGNORECASE,
)
_PARAGRAPH = re.compile(r"\n\s*\n")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class RationaleScore:
    """How strongly a message explains itself, with human-readable reasons."""

    score: float
    reasons: list[str]
    excerpt: str | None  # the sentence that states the reason, quoted verbatim
    clipped: bool = False  # True when ``excerpt`` was cut short


def score_message(message: str, *, labels: list[Label], refs: int) -> RationaleScore:
    """Score one commit message."""
    subject, _, body = message.strip().partition("\n")
    body = body.strip()
    strong = list(dict.fromkeys(m.lower() for m in _STRONG.findall(message)))
    weak = list(dict.fromkeys(m.lower() for m in _WEAK.findall(message)))
    markers = strong + weak
    score = min(len(strong), 2) * STRONG_WEIGHT + min(len(weak), 2) * WEAK_WEIGHT
    reasons: list[str] = []
    if markers:
        reasons.append("states a reason (" + ", ".join(f'"{m}"' for m in markers[:3]) + ")")
    if body:
        score += 0.5 + (0.5 if len(body) >= 200 else 0.0)
        reasons.append("has a message body")
    if refs:
        score += 0.75
        reasons.append(f"links {refs} issue{'s' if refs > 1 else ''}")
    flagged = [label for label in labels if label in (Label.FIX, Label.SECURITY, Label.REVERT)]
    if flagged:
        score += 0.5
        reasons.append("marked " + "/".join(label.value for label in flagged))
    if _NOISE.search(subject) and not markers:
        score -= 1.5
        reasons.append("looks like a mechanical change (format, rename, bump)")
    sentence = _reason_sentence(message)
    excerpt = _clip(sentence) if sentence else None
    return RationaleScore(round(score, 3), reasons, excerpt, excerpt != sentence)


def states_reason(text: str, *, strong: bool = False) -> bool:
    """True when ``text`` contains a word that explains why (because, to avoid, fails, ...).

    With ``strong``, only words that state a cause count (because, due to, to avoid, ...).
    """
    return bool(_STRONG.search(text) or (not strong and _WEAK.search(text)))


def _reason_sentence(message: str) -> str | None:
    """The first sentence that contains a reason marker, else the body's first sentence."""
    sentences: list[str] = []
    for paragraph in _PARAGRAPH.split(message.strip()):
        flowed = " ".join(paragraph.split())  # re-join lines wrapped at ~72 columns
        sentences += [s for s in _SENTENCE.split(flowed) if s and not _BOILERPLATE.match(s)]
    for sentence in sentences:
        if _STRONG.search(sentence):
            return sentence
    for sentence in sentences:
        if _WEAK.search(sentence):
            return sentence
    return sentences[1] if len(sentences) > 1 else None


def _clip(sentence: str, limit: int = 240) -> str:
    """Cut at a word boundary. The result stays a verbatim prefix of the message."""
    if len(sentence) <= limit:
        return sentence
    return sentence[:limit].rsplit(" ", 1)[0].rstrip(",;:")
