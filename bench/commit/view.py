"""A repository as it looked just before one commit, with that commit's changes staged.

``draft_message`` reads style, examples and revert candidates through ``GitRepo``. This view
answers every call from the history before the commit, so a draft never sees the message it is
compared with or anything newer (no time-travel leakage). No checkout is needed.
"""

from __future__ import annotations

from pathlib import Path

from sprout.core.git.pygit2_repo import Pygit2Repo
from sprout.models import ChangedLine, Diff, History, RepoStatus


class AtCommit:
    """``GitRepo`` for the moment before ``hash_`` was committed."""

    def __init__(self, repo: Pygit2Repo, hash_: str) -> None:
        self._repo = repo
        self._hash = hash_
        parents = repo.history(rev=hash_, limit=1).commits[0].parents
        self._parent = parents[0] if parents else None

    @property
    def root(self) -> Path:
        """The clone's working tree (never read: everything comes from objects)."""
        return self._repo.root

    def status(self) -> RepoStatus:
        """No branch name: real branch names would hint at the answer for old commits."""
        return RepoStatus(
            root=str(self.root), branch=None, head=self._parent, detached=True,
            unborn=self._parent is None, staged=[], unstaged=[], untracked=[], conflicted=[],
        )  # fmt: skip

    def diff(self, *, staged: bool) -> Diff:
        """The commit's own changes when ``staged``; nothing unstaged."""
        return self._repo.commit_diff(self._hash) if staged else Diff(staged=False, files=[])

    def history(
        self, *, limit: int | None = None, rev: str | None = None, path: str | None = None
    ) -> History:
        """History from the parent (or from ``rev``, which callers only take from this view)."""
        start = rev or self._parent
        if start is None:
            return History(commits=[], path=path)
        return self._repo.history(limit=limit, rev=start, path=path)

    def uncommitted_lines(self, *, staged_only: bool, limit: int = 20_000) -> list[ChangedLine]:
        """The commit's changed lines, as if staged."""
        del staged_only
        return self._repo.commit_lines(self._hash, limit=limit)

    def commit_lines(self, hash_: str, *, limit: int = 2_000) -> list[ChangedLine]:
        """Changed lines of an earlier commit."""
        return self._repo.commit_lines(hash_, limit=limit)

    def relative_path(self, path: Path) -> str:
        """Repo-relative POSIX path."""
        return self._repo.relative_path(path)
