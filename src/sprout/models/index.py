"""Models for the history index and search."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from sprout.models.base import Model
from sprout.models.git import ChangeKind, Commit


class Label(StrEnum):
    """Signals parsed from a commit message, used for search and risk checks."""

    FIX = "fix"
    SECURITY = "security"
    REVERT = "revert"
    MERGE = "merge"
    BREAKING = "breaking"


class IssueRef(Model):
    """A reference such as ``#12``, ``GH-12`` or ``owner/repo#12`` in a commit message."""

    number: int
    repo: str | None = Field(default=None, description="owner/repo when the ref names one.")
    closes: bool = Field(default=False, description="True for 'fixes #12', 'closes #12', etc.")


class MessageInfo(Model):
    """Everything Sprout reads from a commit message alone."""

    conventional_type: str | None
    scope: str | None
    labels: list[Label]
    refs: list[IssueRef]
    reverts: list[str] = Field(description="Hashes (possibly abbreviated) this commit reverts.")
    reverts_summary: str | None = Field(
        description="Summary quoted in a 'Revert \"...\"' subject, used when no hash is given."
    )


class Hunk(Model):
    """A changed line range in one file (1-based line numbers, zero context)."""

    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    symbols: list[str] = Field(description="Innermost functions/classes the hunk touches.")


class ChangedFile(Model):
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


class CommitRecord(Model):
    """A commit plus everything the index stores about it."""

    commit: Commit
    message_info: MessageInfo
    files: list[ChangedFile]
    files_truncated: bool = Field(description="True when a huge commit was cut to its first files.")
    code_terms: list[str] = Field(description="Identifiers from changed lines, for keyword search.")


class IndexStats(Model):
    """State of a repository's history index."""

    db_path: str
    commits: int
    embedded: int
    summarised: int
    reverts: int
    head: str | None = Field(description="HEAD when the index was last updated.")
    updated_at: datetime | None
    embedding_model: str | None


class SearchMode(StrEnum):
    """Which retrievers ``search`` combines."""

    HYBRID = "hybrid"
    BM25 = "bm25"
    VECTOR = "vector"


class SearchHit(Model):
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


class SearchResults(Model):
    """Ranked commits for a query."""

    query: str
    mode: SearchMode
    reranked: bool
    hits: list[SearchHit]
    notes: list[str] = Field(
        default_factory=list, description="Why a retriever or the reranker was skipped."
    )
