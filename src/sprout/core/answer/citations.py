"""Check every sentence a model writes against the evidence it cites.

A sentence survives only if (1) it is prose, not evidence pasted back (no line breaks, no
evidence header, at most ``MAX_CITATIONS`` commits), (2) it cites at least one commit, (3) every
cited hash belongs to the evidence and exists in the repository, (4) any "quoted" text appears
verbatim in a cited commit, and (5) otherwise most of its content words appear in the cited
evidence. Copying evidence would pass (4) and (5), so (1) rejects it first.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from sprout.core.index.text import split_identifier
from sprout.models import Sentence

_CITE_GROUP = re.compile(r"\[((?:[0-9a-f]{7,40})(?:\s*[,;]\s*[0-9a-f]{7,40})*)\]")
_TRAILING_GROUPS = re.compile(
    r"\s*(?:\[[0-9a-f]{7,40}(?:\s*[,;]\s*[0-9a-f]{7,40})*\]\s*)+([.!?]?)\s*$"
)
# What evidence blocks start with (see compose.evidence_blocks): "<role>, <date>", "message:" ...
_EVIDENCE_HEADER = re.compile(
    r"^(?:(?:line_origin|line_history|symbol_history|revert|related),\s*\d{4}-\d{2}-\d{2}"
    r"|message:|labels:|issues:|reverted by:|diff of |the line at this commit:)",
    re.IGNORECASE,
)
_LEADING_GROUPS = re.compile(r"^(?:\[[0-9a-f]{7,40}(?:\s*[,;]\s*[0-9a-f]{7,40})*\]\s*)+")
MAX_CITATIONS = 3
_HASH = re.compile(r"[0-9a-f]{7,40}")
_QUOTE = re.compile(r"[\"“]([^\"”]{4,})[\"”]")
_TRAILING_CITE = re.compile(r"([.!?])\s*(\[[0-9a-f][0-9a-f\s,;]{6,}\])")
_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"“`(\[])")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_]{3,}")
_STOP_WORDS = """this that with from were have been they them their there which what when where
while into also only some such than then because about after before since commit commits change
changes changed code line lines file files function class history added adds made make makes
does doesn the and for was not but its records record why reason"""
_STOP = frozenset(_STOP_WORDS.split())
SUPPORT_THRESHOLD = 0.5


@dataclass(frozen=True)
class CheckResult:
    """Sentences that passed, and how many were dropped and why."""

    kept: list[Sentence]
    dropped: int
    forged: int  # citations to hashes outside the evidence or not in the repository
    reasons: list[str]


def split_sentences(text: str) -> list[str]:
    """Split prose into sentences, keeping citations written after a full stop with it."""
    text = _TRAILING_CITE.sub(r" \2\1", text.strip())
    parts = [p.strip() for p in _SPLIT.split(text) if p.strip()]
    merged: list[str] = []
    for part in parts:
        if merged and not _CITE_GROUP.sub("", part).strip(" .;"):
            merged[-1] = f"{merged[-1]} {part}"
        else:
            merged.append(part)
    return merged


def check(
    text: str,
    evidence_text: Mapping[str, str],
    *,
    exists: Callable[[str], bool],
) -> CheckResult:
    """Keep only sentences fully supported by the commits they cite.

    Args:
        text: The model's answer.
        evidence_text: Full hash -> everything the model was shown about that commit.
        exists: Returns True if a full hash exists in the repository (``git cat-file``).
    """
    return check_sentences(split_sentences(text), evidence_text, exists=exists)


def check_sentences(
    sentences: list[str],
    evidence_text: Mapping[str, str],
    *,
    exists: Callable[[str], bool],
) -> CheckResult:
    """Like ``check``, for sentences that are already split (each one is checked whole).

    Use it for sentences Sprout composed itself, where a quote may contain a full stop.
    """
    kept: list[Sentence] = []
    dropped = forged = 0
    reasons: list[str] = []
    for raw in sentences:
        sentence = " ".join(raw.split())
        cited, unknown = _resolve(sentence, evidence_text)
        unknown += [h for h in cited if not exists(h)]
        clean = _readable(sentence)
        problem = _copied(raw, cited) or _problem(clean, cited, unknown, evidence_text)
        if problem:
            dropped += 1
            forged += len(unknown)
            reasons.append(f"{problem}: {clean[:80]}")
            continue
        kept.append(Sentence(text=clean, citations=cited))
    return CheckResult(kept, dropped, forged, reasons)


def _readable(sentence: str) -> str:
    """Drop leading and trailing citations; keep mid-sentence ones as plain short hashes."""
    text = _TRAILING_GROUPS.sub(r"\1", sentence.strip())
    text = _LEADING_GROUPS.sub("", text)
    text = _CITE_GROUP.sub(lambda m: m.group(1), text)
    return text.replace(" .", ".").strip()


def _copied(sentence: str, cited: list[str]) -> str | None:
    """Evidence pasted back instead of an answer."""
    bare = _CITE_GROUP.sub("", sentence).strip()
    if "\n" in bare or _EVIDENCE_HEADER.match(bare):
        return "copied evidence, not prose"
    if len(cited) > MAX_CITATIONS:
        return "cites too many commits"
    return None


def _resolve(sentence: str, evidence_text: Mapping[str, str]) -> tuple[list[str], list[str]]:
    cited: list[str] = []
    unknown: list[str] = []
    for group in _CITE_GROUP.findall(sentence):
        for prefix in _HASH.findall(group):
            matches = [h for h in evidence_text if h.startswith(prefix)]
            if len(matches) == 1:
                cited.append(matches[0])
            else:
                unknown.append(prefix)
    return list(dict.fromkeys(cited)), unknown


def _problem(
    clean: str, cited: list[str], unknown: list[str], evidence_text: Mapping[str, str]
) -> str | None:
    if unknown:
        return "cites a commit that is not in the evidence"
    if not cited:
        return "no citation"
    source = _normalise(" ".join(evidence_text[h] for h in cited))
    for quote in _QUOTE.findall(clean):
        if _normalise(quote) not in source:
            return "quote not found in the cited commits"
    if _QUOTE.search(clean):
        return None
    words = _content_words(_CITE_GROUP.sub("", clean))
    if len(words) < 2:
        return None
    vocabulary = set(_content_words(source))
    supported = sum(1 for w in words if w in vocabulary)
    return (
        None
        if supported / len(words) >= SUPPORT_THRESHOLD
        else "not supported by the cited commits"
    )


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


def _content_words(text: str) -> list[str]:
    words: list[str] = []
    for word in _WORD.findall(text):
        for part in [word.lower(), *split_identifier(word)]:
            if len(part) >= 4 and part not in _STOP:
                words.append(part)
    return list(dict.fromkeys(words))
