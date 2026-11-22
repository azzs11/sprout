"""Models for repository state: status, diffs, commits and history."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, computed_field

from sprout.models.base import Model


class ChangeKind(StrEnum):
    """How a file changed."""

    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"
    COPIED = "copied"
    TYPE_CHANGED = "type_changed"
    UNTRACKED = "untracked"
    CONFLICTED = "conflicted"


class FileChange(Model):
    """A file listed by ``status``."""

    path: str
    kind: ChangeKind


class RepoStatus(Model):
    """Snapshot of a repository's branch, HEAD and working tree."""

    root: str = Field(description="Absolute path of the working tree.")
    branch: str | None = Field(description="Current branch, or None when HEAD is detached.")
    head: str | None = Field(description="Full hash of HEAD, or None before the first commit.")
    detached: bool
    unborn: bool = Field(description="True when the current branch has no commits yet.")
    staged: list[FileChange]
    unstaged: list[FileChange]
    untracked: list[str]
    conflicted: list[str]

    @computed_field
    @property
    def clean(self) -> bool:
        """True when there is nothing staged, unstaged, untracked or conflicted."""
        return not (self.staged or self.unstaged or self.untracked or self.conflicted)


class FileDiff(Model):
    """One file's changes inside a diff."""

    path: str
    old_path: str | None = Field(description="Previous path for renames and copies.")
    kind: ChangeKind
    additions: int
    deletions: int
    binary: bool
    patch: str


class Diff(Model):
    """A set of file changes, either staged (index vs HEAD) or unstaged (worktree vs index)."""

    staged: bool
    files: list[FileDiff]

    @computed_field
    @property
    def additions(self) -> int:
        """Total added lines across all files."""
        return sum(f.additions for f in self.files)

    @computed_field
    @property
    def deletions(self) -> int:
        """Total deleted lines across all files."""
        return sum(f.deletions for f in self.files)


class Person(Model):
    """An author or committer identity."""

    name: str
    email: str


class Commit(Model):
    """A single commit."""

    hash: str
    short_hash: str
    author: Person
    authored_at: datetime
    committer: Person
    committed_at: datetime
    summary: str = Field(description="First line of the message.")
    message: str
    parents: list[str]


class History(Model):
    """Commits in reverse chronological order."""

    commits: list[Commit]
    path: str | None = Field(default=None, description="Path filter, relative to the root.")
