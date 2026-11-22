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
