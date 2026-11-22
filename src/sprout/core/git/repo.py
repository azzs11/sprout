"""The ``GitRepo`` interface every git backend implements."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from sprout.models import Diff, History, RepoStatus


class GitRepo(Protocol):
    """Read-only access to one git repository."""

    @property
    def root(self) -> Path:
        """Absolute path of the working tree (or the git dir for bare repositories)."""
        ...

    def status(self) -> RepoStatus:
        """Return branch, HEAD and working-tree changes. Works before the first commit."""
        ...

    def diff(self, *, staged: bool) -> Diff:
        """Return staged changes (index vs HEAD) or unstaged ones (worktree vs index)."""
        ...

    def history(
        self,
        *,
        limit: int | None = None,
        rev: str | None = None,
        path: str | None = None,
    ) -> History:
        """Return commits reachable from ``rev`` (default HEAD), newest first.

        Args:
            limit: Maximum number of commits; ``None`` means all.
            rev: Branch, tag or hash to start from.
            path: Only commits that changed this repo-relative path.
        """
        ...

    def relative_path(self, path: Path) -> str:
        """Convert a filesystem path to a POSIX path relative to the root."""
        ...
