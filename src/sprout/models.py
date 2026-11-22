"""Pydantic models shared by every Sprout surface (CLI, MCP, API).

``core/`` returns these models and never formats output itself.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, computed_field


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


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


class FileChange(_Model):
    """A file listed by ``status``."""

    path: str
    kind: ChangeKind


class RepoStatus(_Model):
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


class FileDiff(_Model):
    """One file's changes inside a diff."""

    path: str
    old_path: str | None = Field(description="Previous path for renames and copies.")
    kind: ChangeKind
    additions: int
    deletions: int
    binary: bool
    patch: str


class Diff(_Model):
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


class Person(_Model):
    """An author or committer identity."""

    name: str
    email: str


class Commit(_Model):
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


class History(_Model):
    """Commits in reverse chronological order."""

    commits: list[Commit]
    path: str | None = Field(default=None, description="Path filter, relative to the root.")


# ----- history index ----------------------------------------------------------------


class Label(StrEnum):
    """Signals parsed from a commit message, used for search and risk checks."""

    FIX = "fix"
    SECURITY = "security"
    REVERT = "revert"
    MERGE = "merge"
    BREAKING = "breaking"


class IssueRef(_Model):
    """A reference such as ``#12``, ``GH-12`` or ``owner/repo#12`` in a commit message."""

    number: int
    repo: str | None = Field(default=None, description="owner/repo when the ref names one.")
    closes: bool = Field(default=False, description="True for 'fixes #12', 'closes #12', etc.")


class MessageInfo(_Model):
    """Everything Sprout reads from a commit message alone."""

    conventional_type: str | None
    scope: str | None
    labels: list[Label]
    refs: list[IssueRef]
    reverts: list[str] = Field(description="Hashes (possibly abbreviated) this commit reverts.")
    reverts_summary: str | None = Field(
        description="Summary quoted in a 'Revert \"...\"' subject, used when no hash is given."
    )


class Hunk(_Model):
    """A changed line range in one file (1-based line numbers, zero context)."""

    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    symbols: list[str] = Field(description="Innermost functions/classes the hunk touches.")


class ChangedFile(_Model):
    """One file changed by a commit, compared with its first parent."""

    path: str
    old_path: str | None
    kind: ChangeKind
    additions: int
    deletions: int
    binary: bool
    hunks: list[Hunk]

    @property
    def symbols(self) -> list[str]:
        """Unique symbols touched by any hunk, in first-seen order."""
        return list(dict.fromkeys(s for h in self.hunks for s in h.symbols))


class CommitRecord(_Model):
    """A commit plus everything the index stores about it."""

    commit: Commit
    message_info: MessageInfo
    files: list[ChangedFile]
    files_truncated: bool = Field(description="True when a huge commit was cut to its first files.")
    code_terms: list[str] = Field(description="Identifiers from changed lines, for keyword search.")


class IndexStats(_Model):
    """State of a repository's history index."""

    db_path: str
    commits: int
    embedded: int
    summarised: int
    reverts: int
    head: str | None = Field(description="HEAD when the index was last updated.")
    updated_at: datetime | None
    embedding_model: str | None
    vectors_available: bool = Field(description="False if sqlite-vec could not be loaded.")


class SearchMode(StrEnum):
    """Which retrievers ``search`` combines."""

    HYBRID = "hybrid"
    BM25 = "bm25"
    VECTOR = "vector"


class SearchHit(_Model):
    """One commit returned by ``search``."""

    rank: int
    score: float
    commit: Commit
    labels: list[Label]
    files: list[str]
    symbols: list[str]
    refs: list[IssueRef]
    reverted_by: list[str] = Field(description="Hashes of indexed commits that revert this one.")
    retrievers: list[str] = Field(description="Which retrievers found it: bm25, vector, rerank.")


class SearchResults(_Model):
    """Ranked commits for a query."""

    query: str
    mode: SearchMode
    reranked: bool
    hits: list[SearchHit]
