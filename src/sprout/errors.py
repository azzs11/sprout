"""Exceptions raised by Sprout.

Every error carries a short message and, where possible, a hint telling the user
exactly what to do next. The CLI, MCP server and API decide how to show them.
"""

from __future__ import annotations


class SproutError(Exception):
    """Base class for all expected, user-facing errors."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class NotARepositoryError(SproutError):
    """Raised when no git repository is found at or above a path."""

    def __init__(self, path: str) -> None:
        super().__init__(
            f"No git repository found at {path}.",
            hint="Run Sprout inside a git repository, or create one with: git init",
        )


class BareRepositoryError(SproutError):
    """Raised when a command needs a working tree but the repository is bare."""

    def __init__(self, path: str) -> None:
        super().__init__(
            f"{path} is a bare repository, so it has no working tree.",
            hint="Run this command in a normal clone instead of a bare repository.",
        )


class RevisionNotFoundError(SproutError):
    """Raised when a revision such as a branch, tag or hash cannot be resolved."""

    def __init__(self, rev: str) -> None:
        super().__init__(
            f"Revision {rev!r} was not found.",
            hint="Check the name with: git branch -a, git tag, or git log --oneline",
        )


class PathOutsideRepositoryError(SproutError):
    """Raised when a path filter points outside the repository's working tree."""

    def __init__(self, path: str, root: str) -> None:
        super().__init__(
            f"{path} is outside the repository at {root}.",
            hint="Pass a path inside the repository.",
        )


class NoCommitsError(SproutError):
    """Raised when indexing a repository whose branch has no commits yet."""

    def __init__(self) -> None:
        super().__init__("No commits yet.", hint="Make a first commit, then run: sprout index")


class IndexNotFoundError(SproutError):
    """Raised when a command needs the history index but it has not been built."""

    def __init__(self, root: str) -> None:
        super().__init__(f"No Sprout index found for {root}.", hint="Build it with: sprout index")


class VectorsUnavailableError(SproutError):
    """Raised when semantic search is requested but no vectors can be used."""

    def __init__(self, reason: str) -> None:
        super().__init__(
            f"Semantic search is unavailable: {reason}",
            hint="Use --mode bm25, or run sprout index with an embedding model enabled.",
        )


class ModelError(SproutError):
    """Raised when a local or remote model cannot be loaded or called."""
