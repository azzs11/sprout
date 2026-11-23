"""Models for ``sprout why``: line history, evidence and cited answers."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from sprout.models.base import Model
from sprout.models.git import Commit
from sprout.models.index import IssueRef, Label


class EvidenceRole(StrEnum):
    """How a commit relates to the question."""

    LINE_ORIGIN = "line_origin"  # last commit to change the line (what blame shows)
    LINE_HISTORY = "line_history"  # earlier commits in the line's history
    SYMBOL_HISTORY = "symbol_history"  # other commits that changed the enclosing function/class
    REVERT = "revert"  # reverts of, or reverted by, the commits above
    RELATED = "related"  # found by searching the history index


class LineHop(Model):
    """One step back through a line's history."""

    commit: Commit
    path: str = Field(description="File path in that commit (follows renames).")
    line: int = Field(description="1-based line number in that commit's version of the file.")
    text: str = Field(description="The line's content in that commit.")
    introduced: bool = Field(description="True if this commit created the line from nothing.")


class Evidence(Model):
    """A commit offered as evidence, with why it was chosen."""

    commit: Commit
    role: EvidenceRole
    score: float = Field(description="Higher means more likely to state the rationale.")
    reasons: list[str] = Field(description="Short notes on why this commit was included.")
    labels: list[Label] = Field(default_factory=list[Label])
    refs: list[IssueRef] = Field(default_factory=list[IssueRef])
    reverted_by: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)


class Sentence(Model):
    """One sentence of an answer and the commits it cites."""

    text: str
    citations: list[str] = Field(description="Full hashes of the cited commits.")


class AnswerMode(StrEnum):
    """How the answer was produced."""

    LLM = "llm"  # a model wrote sentences; every kept sentence passed the citation check
    RETRIEVAL = "retrieval"  # no model: deterministic sentences built from the evidence


class WhyAnswer(Model):
    """A cited answer to 'why is this code like this?'."""

    target: str = Field(description="'path:line' or the question asked.")
    as_of: str = Field(description="Commit the question was asked about (default HEAD).")
    symbol: str | None = Field(default=None, description="Enclosing function or class, if known.")
    line_text: str | None = None
    mode: AnswerMode
    model: str | None = Field(default=None, description="Provider and prompt, when mode is llm.")
    sentences: list[Sentence]
    dropped: int = Field(default=0, description="Model sentences removed by the citation check.")
    drop_reasons: list[str] = Field(
        default_factory=list, description="Why each dropped sentence failed, with its start."
    )
    history: list[LineHop] = Field(default_factory=list[LineHop])
    evidence: list[Evidence]
    notes: list[str] = Field(default_factory=list)
