"""Models for commit messages: the repository's learned style and drafted messages."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from sprout.models.base import Model


class Count(Model):
    """How often a value was seen in the sample."""

    value: str
    count: int


class CommitStyle(Model):
    """How this repository writes commit messages, learned from recent non-merge commits."""

    sample_size: int = Field(description="Commits read (merges and reverts are skipped).")
    conventional_share: float = Field(description="Share with a Conventional Commit prefix.")
    types: list[Count] = Field(description="Conventional types, most used first.")
    scopes: list[Count] = Field(description="Conventional scopes, most used first.")
    subject_p50: int = Field(description="Median subject length in characters.")
    subject_p90: int = Field(description="90th-percentile subject length in characters.")
    capitalised_share: float = Field(description="Share whose description starts upper-case.")
    period_share: float = Field(description="Share whose subject ends with a full stop.")
    imperative_share: float = Field(
        description="Share whose first word looks imperative ('add', not 'added' or 'adds')."
    )
    body_share: float = Field(description="Share with a body after the subject.")
    pr_suffix_share: float = Field(description="Share whose subject ends with '(#123)'.")
    trailers: list[Count] = Field(description="Trailer keys (e.g. Signed-off-by), most used first.")
    examples: list[str] = Field(description="Recent subjects, newest first.")


class DraftSource(StrEnum):
    """Who wrote the subject and body of a draft."""

    MODEL = "model"
    SKELETON = "skeleton"


class TrailerSource(StrEnum):
    """Where a trailer's value came from."""

    AUTHOR = "author"  # typed by the author: the why answer or --fixes
    BRANCH = "branch"  # an issue number in the branch name
    DIFF = "diff"  # the staged diff undoes a past commit


class Trailer(Model):
    """One ``Key: value`` line at the end of a message, read back by the index."""

    key: str
    value: str
    source: TrailerSource


class CommitDraft(Model):
    """A proposed commit message. Sprout never commits; the author edits and commits it."""

    message: str = Field(description="Full message, ready for git commit -F.")
    subject: str
    body: str | None = Field(description="What changed, in the repository's style.")
    question: str = Field(description="The one question that asks the author why.")
    why: str | None = Field(description="The author's answer, kept word for word.")
    trailers: list[Trailer] = Field(description="Why, Fixes, Refs and Reverts, in that order.")
    source: DraftSource
    model: str | None = Field(description="Provider and prompt id when a model wrote it.")
    examples: list[str] = Field(description="Subjects of the past commits shown as examples.")
    files: list[str] = Field(description="Paths in the diff.")
    redacted: int = Field(description="Secrets removed from the diff before any model call.")
    diff_truncated: bool
    notes: list[str]
