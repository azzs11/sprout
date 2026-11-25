"""Models for ``sprout init`` and ``sprout uninstall``."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from sprout.models.base import Model
from sprout.models.git import Commit
from sprout.models.index import IndexStats


class Agent(StrEnum):
    """Agents whose project-level MCP config Sprout can write."""

    CLAUDE = "claude"  # Claude Code: .mcp.json
    CURSOR = "cursor"  # .cursor/mcp.json
    VSCODE = "vscode"  # .vscode/mcp.json


class ConfigAction(StrEnum):
    """What happened to one config file."""

    ADDED = "added"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    REMOVED = "removed"
    DELETED_FILE = "deleted_file"  # the file held only Sprout's entry
    ABSENT = "absent"


class ConfigChange(Model):
    """One MCP config file Sprout touched."""

    agent: Agent
    path: str = Field(description="Relative to the repository root.")
    action: ConfigAction


class HookChange(Model):
    """Sprout's git pre-commit hook, and what happened to it."""

    path: str
    action: ConfigAction


class ServerCommand(Model):
    """How an agent should start ``sprout mcp serve``."""

    command: str
    args: list[str]
    portable: bool = Field(description="False when the command is a path on this machine only.")


class RevertLink(Model):
    """A revert and the commit it undid, both found in the index."""

    revert: Commit
    reverted_hash: str
    reverted_summary: str


class EmbedState(StrEnum):
    """What ``init`` did about semantic vectors."""

    BACKGROUND = "background"  # a ``sprout index`` process is adding them now
    DONE = "done"
    SKIPPED = "skipped"


class InitReport(Model):
    """Everything ``sprout init`` set up."""

    root: str
    stats: IndexStats | None = Field(description="None when the repository has no commits yet.")
    configs: list[ConfigChange]
    server: ServerCommand
    embedding: EmbedState
    embed_log: str | None = Field(default=None, description="Log of the background indexer.")
    answers: str = Field(description="Where written answers come from, or why they are off.")
    recent_reverts: list[RevertLink]
    git_hook: HookChange | None = Field(default=None, description="Set with --git-hook.")
    notes: list[str] = Field(default_factory=list)


class UninstallReport(Model):
    """Everything ``sprout uninstall`` removed."""

    root: str
    configs: list[ConfigChange]
    git_hook: HookChange
    index_removed: bool
    notes: list[str] = Field(default_factory=list)
