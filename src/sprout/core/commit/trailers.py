"""Trailers that let the history index learn from new commits.

``Why:`` holds the author's own words and is shown by ``sprout why`` as the stated reason.
``Fixes:`` is written only when the author names the issue, because GitHub closes it on merge;
an issue number in the branch name becomes ``Refs:``, which closes nothing. ``Reverts:`` is
added when the staged diff undoes a recent commit, so the index records the revert link even
when it was made by hand instead of with ``git revert``.
"""

from __future__ import annotations

import re
import textwrap
from collections import Counter
from collections.abc import Sequence

from sprout.core.commit.style import is_authored
from sprout.core.git.repo import GitRepo
from sprout.errors import SproutError
from sprout.models import ChangedLine, Commit, FileDiff, Trailer, TrailerSource

WRAP = 72
CANDIDATE_FILES = 5
CANDIDATES_PER_FILE = 20
REVERT_COVERAGE = 0.8  # share of the past commit's changed lines the diff must undo
_BRANCH_ISSUE = re.compile(
    r"^(?:issues?|gh|bug|fix|feat|feature)?[-_]?#?(?P<number>\d{1,6})(?:[-_].*)?$", re.IGNORECASE
)
_DATE_LIKE = re.compile(r"^(?:19|20)\d\d[-_]\d")
_NOT_ISSUE_BRANCHES = frozenset({"release", "releases", "dependabot", "renovate"})


def build_trailers(
    *,
    why: str | None,
    fixes: Sequence[int] = (),
    branch: str | None = None,
    reverts: Commit | None = None,
) -> list[Trailer]:
    """``Why``, then ``Fixes``, ``Refs`` (from the branch, unless already fixed), ``Reverts``."""
    out: list[Trailer] = []
    if why:
        out.append(Trailer(key="Why", value=why, source=TrailerSource.AUTHOR))
    named = list(dict.fromkeys(fixes))
    out += [Trailer(key="Fixes", value=f"#{n}", source=TrailerSource.AUTHOR) for n in named]
    guessed = issue_from_branch(branch) if branch else None
    if guessed is not None and guessed not in named:
        out.append(Trailer(key="Refs", value=f"#{guessed}", source=TrailerSource.BRANCH))
    if reverts is not None:
        out.append(Trailer(key="Reverts", value=reverts.hash, source=TrailerSource.DIFF))
    return out


def format_trailers(trailers: Sequence[Trailer]) -> str:
    """The trailer block; long values continue on indented lines, as git allows."""
    lines = [
        textwrap.fill(f"{t.key}: {t.value}", WRAP, subsequent_indent="  ", break_long_words=False)
        for t in trailers
    ]
    return "\n".join(lines)


def issue_from_branch(branch: str) -> int | None:
    """The issue number in names like ``fix/123-retry``, ``gh-42`` or ``issue_7``."""
    segments = branch.split("/")
    if segments[0].lower() in _NOT_ISSUE_BRANCHES:
        return None
    for segment in reversed(segments):
        match = _BRANCH_ISSUE.match(segment)
        if match and not _DATE_LIKE.match(segment):
            return int(match["number"])
    return None


def find_reverted(repo: GitRepo, files: Sequence[FileDiff]) -> Commit | None:
    """The newest recent commit to these files that the staged diff undoes, if any.

    Every staged line must be the inverse of one of the commit's lines (added back what it
    removed, removed what it added), and together they must cover ``REVERT_COVERAGE`` of it.
    """
    staged = _signature(repo.uncommitted_lines(staged_only=True))
    if not staged:
        return None
    for commit in _candidates(repo, files):
        past = _signature(repo.commit_lines(commit.hash))
        inverse = Counter({(not added, text): n for (added, text), n in past.items()})
        if staged - inverse:  # a staged line the commit did not change
            continue
        if staged.total() >= REVERT_COVERAGE * past.total():
            return commit
    return None


def _candidates(repo: GitRepo, files: Sequence[FileDiff]) -> list[Commit]:
    found: dict[str, Commit] = {}
    for f in files[:CANDIDATE_FILES]:
        try:
            history = repo.history(limit=CANDIDATES_PER_FILE, path=f.old_path or f.path)
        except SproutError:
            return []  # no commits yet
        found.update((c.hash, c) for c in history.commits if is_authored(c))
    return sorted(found.values(), key=lambda c: c.committed_at, reverse=True)


def _signature(lines: Sequence[ChangedLine]) -> Counter[tuple[bool, str]]:
    """Changed lines as (added, stripped text), ignoring blank ones."""
    return Counter((line.added, line.text.strip()) for line in lines if line.text.strip())
