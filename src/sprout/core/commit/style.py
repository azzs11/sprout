"""Learn how a repository writes commit messages from its own recent history. No model is used."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence

from sprout.core.git.message import parse_message
from sprout.core.git.repo import GitRepo
from sprout.models import Commit, CommitStyle, Count, Label

SAMPLE = 300
TOP = 8
EXAMPLES = 5
_PREFIX = re.compile(r"^[a-zA-Z]+(?:\([^()\n]+\))?!?:\s*")
_PR_SUFFIX = re.compile(r"\(#\d+\)\s*$")
_TRAILER = re.compile(r"^(?P<key>[A-Za-z][A-Za-z0-9-]*): \S")
_SQUASH_LINE = re.compile(r"^(?:\* \S.*|-{3,})$")
# First words ending like this are not imperative even though they end in -s or -ed.
_NOT_THIRD_PERSON = ("ss", "us", "is", "ys")
_IMPERATIVE_ED = frozenset({"embed", "feed", "need", "seed", "shed", "speed", "proceed", "succeed"})


def learn_style(repo: GitRepo, *, limit: int = SAMPLE) -> CommitStyle:
    """Describe the style of up to ``limit`` recent commits, skipping merges and reverts."""
    commits = [c for c in repo.history(limit=limit * 2).commits if is_authored(c)][:limit]
    infos = [parse_message(c.message) for c in commits]
    subjects = [c.summary.strip() for c in commits]
    descriptions = [_PREFIX.sub("", s, count=1) for s in subjects]
    return CommitStyle(
        sample_size=len(commits),
        conventional_share=_share(i.conventional_type is not None for i in infos),
        types=_top(i.conventional_type for i in infos if i.conventional_type),
        scopes=_top(i.scope for i in infos if i.scope),
        subject_p50=_percentile([len(s) for s in subjects], 0.5),
        subject_p90=_percentile([len(s) for s in subjects], 0.9),
        capitalised_share=_share(d[:1].isupper() for d in descriptions if d),
        period_share=_share(s.endswith(".") for s in subjects),
        imperative_share=_share(is_imperative(d) for d in descriptions if d),
        body_share=_share(bool(_body(c.message)) for c in commits),
        pr_suffix_share=_share(bool(_PR_SUFFIX.search(s)) for s in subjects),
        trailers=_top_any_case(key for c in commits for key in trailer_keys(c.message)),
        examples=subjects[:EXAMPLES],
    )


def is_imperative(description: str) -> bool:
    """True when the first word reads as an instruction: 'add', not 'added' or 'adds'."""
    word = description.split(maxsplit=1)[0].lower() if description.split() else ""
    if not word.isalpha():
        return True  # a name, path or symbol: no tense to judge
    if word.endswith("ed") and word not in _IMPERATIVE_ED:
        return False
    return not (word.endswith("s") and not word.endswith(_NOT_THIRD_PERSON))


def trailer_keys(message: str) -> list[str]:
    """Keys of the trailer block (the last paragraph, when every line is ``Key: value``)."""
    paragraphs = [p for p in _lf(message).strip().split("\n\n") if p.strip()]
    if len(paragraphs) < 2:
        return []
    lines = paragraphs[-1].strip().splitlines()
    matches = [_TRAILER.match(line) for line in lines]
    if not all(matches):
        return []
    return [m["key"] for m in matches if m]


def is_authored(commit: Commit) -> bool:
    """People's commits only: no merges, reverts or bot commits."""
    if len(commit.parents) > 1 or "[bot]" in commit.author.name:
        return False
    if commit.summary.lower().startswith("[automated]"):
        return False
    return Label.REVERT not in parse_message(commit.message).labels


def _body(message: str) -> str:
    """Text after the subject, without trailers or a squash merge's generated commit list."""
    message = _lf(message)
    _, _, rest = message.strip().partition("\n")
    keys = trailer_keys(message)
    text = rest.strip()
    if keys:
        text = text.rpartition("\n\n")[0] if "\n\n" in text else ""
    if all(_SQUASH_LINE.match(line) for line in text.splitlines() if line.strip()):
        return ""  # only "* <subject>" bullets and "-----": GitHub wrote it, not the author
    return text.strip()


def _lf(message: str) -> str:
    """Messages written on GitHub often use CRLF; paragraphs are split on blank lines."""
    return message.replace("\r\n", "\n")


def _share(flags: Iterable[bool]) -> float:
    values = list(flags)
    return round(sum(values) / len(values), 3) if values else 0.0


def _top(values: Iterable[str]) -> list[Count]:
    return [Count(value=v, count=n) for v, n in Counter(values).most_common(TOP)]


def _top_any_case(values: Iterable[str]) -> list[Count]:
    """Like ``_top``, counting spellings that differ only in case together (most used shown)."""
    spellings: dict[str, Counter[str]] = {}
    for value in values:
        spellings.setdefault(value.lower(), Counter())[value] += 1
    totals = Counter({k: sum(c.values()) for k, c in spellings.items()})
    return [
        Count(value=spellings[k].most_common(1)[0][0], count=n) for k, n in totals.most_common(TOP)
    ]


def _percentile(values: Sequence[int], q: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]
