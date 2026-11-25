"""Models for Regression Memory: changed lines, findings and the risk card."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from sprout.models.base import Model
from sprout.models.git import Commit
from sprout.models.index import Label


class ChangedLine(Model):
    """One added or removed line of a diff."""

    path: str = Field(description="New path for added lines, old path for removed ones.")
    added: bool
    text: str
    line: int = Field(description="1-based line number on its side of the diff (0 if unknown).")


class RiskKind(StrEnum):
    """How a change runs into a past commit."""

    REAPPLIES_REVERTED = "reapplies_reverted"  # re-adds code that a revert removed
    REINTRODUCES_FIXED = "reintroduces_fixed"  # re-adds lines that a fix removed
    REMOVES_FIX = "removes_fix"  # removes lines that a fix added
    REMOVES_RESTORED = "removes_restored"  # removes code that a revert put back


class RiskLevel(StrEnum):
    """How loudly to warn. Shown as a word, never as colour alone."""

    LOW = "low"  # nothing citable: stay silent
    REVIEW = "review"
    HIGH = "high"


class Verdict(StrEnum):
    """What an agent should do (MCP ``check_edit``)."""

    PROCEED = "proceed"
    REVIEW = "review"
    STOP = "stop"


class RiskFinding(Model):
    """A past commit that this change runs into, with the lines that prove it."""

    commit: Commit
    kind: RiskKind
    level: RiskLevel
    labels: list[Label]
    matched: int = Field(description="Lines of this change that match the commit's lines.")
    total: int = Field(description="Distinct lines of that side of the commit that Sprout keeps.")
    examples: list[str] = Field(description="Up to three matching lines, prefixed + or -.")
    paths: list[str]
    reverts: list[str] = Field(
        default_factory=list, description="For a revert: the commits it reverted."
    )
    reason: str | None = Field(default=None, description="The commit's stated reason, quoted.")


class RiskCard(Model):
    """The answer to "does history warn against this change?"."""

    level: RiskLevel
    verdict: Verdict
    findings: list[RiskFinding]
    checked_lines: int = Field(description="Changed lines compared with history.")
    method: str = Field(description="Matching rules version, e.g. risk@2.")
    notes: list[str] = Field(default_factory=list)


class AckKind(StrEnum):
    """Why a commit's warnings are switched off."""

    ACK = "ack"  # the risk is known and accepted
    SUPERSEDE = "supersede"  # the fix or revert no longer applies (e.g. the code was redesigned)


class Ack(Model):
    """One entry of ``.sprout-acks.toml``: Sprout stops warning about this commit."""

    commit: str = Field(description="Full hash of the cited fix, security or revert commit.")
    kind: AckKind
    reason: str
    by: str = Field(description="Who acknowledged it (git user.name).")
    date: str = Field(description="YYYY-MM-DD.")
    superseded_by: str | None = Field(default=None, description="The commit that replaced it.")


class AckList(Model):
    """Everything in ``.sprout-acks.toml``."""

    path: str
    acks: list[Ack]
