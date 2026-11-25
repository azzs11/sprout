"""Pydantic models shared by every Sprout surface (CLI, MCP, API).

``core/`` returns these models and never formats output itself.
"""

from sprout.models.answer import (
    AnswerMode,
    CommitExplanation,
    Evidence,
    EvidenceRole,
    LineHop,
    Sentence,
    WhyAnswer,
)
from sprout.models.git import (
    ChangeKind,
    Commit,
    Diff,
    FileChange,
    FileDiff,
    History,
    Person,
    RepoStatus,
)
from sprout.models.index import (
    ChangedFile,
    CommitRecord,
    Hunk,
    IndexStats,
    IssueRef,
    Label,
    MessageInfo,
    SearchHit,
    SearchMode,
    SearchResults,
)

__all__ = [
    "AnswerMode",
    "ChangeKind",
    "ChangedFile",
    "Commit",
    "CommitExplanation",
    "CommitRecord",
    "Diff",
    "Evidence",
    "EvidenceRole",
    "FileChange",
    "FileDiff",
    "History",
    "Hunk",
    "IndexStats",
    "IssueRef",
    "Label",
    "LineHop",
    "MessageInfo",
    "Person",
    "RepoStatus",
    "SearchHit",
    "SearchMode",
    "SearchResults",
    "Sentence",
    "WhyAnswer",
]
