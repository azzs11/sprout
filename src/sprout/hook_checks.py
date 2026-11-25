"""The checks behind ``sprout-hook``, imported only once an index is known to exist."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import IO, cast

from sprout.core.git import open_repo
from sprout.core.git.pygit2_repo import Pygit2Repo
from sprout.core.index.store import Store
from sprout.core.risk import acks
from sprout.core.risk.check import check_changes
from sprout.core.risk.edits import edit_lines, line_of
from sprout.errors import IndexNotFoundError
from sprout.models import ChangedLine, Label, RiskCard, RiskFinding, RiskKind, RiskLevel

BLOCKED = 2
_KIND = {
    RiskKind.REAPPLIES_REVERTED: "re-applies code that this revert removed",
    RiskKind.REINTRODUCES_FIXED: "re-adds lines that this fix removed",
    RiskKind.REMOVES_FIX: "removes lines that this fix added",
    RiskKind.REMOVES_RESTORED: "removes code that this revert restored",
}
Event = dict[str, object]


def pre_commit(cwd: Path) -> int:
    """Check the staged diff; print findings to stderr. Exit 2 for security fixes or strict mode."""
    repo = open_repo(cwd)
    card = _check(repo, repo.uncommitted_lines(staged_only=True))
    shown = _shown(card)
    if not shown:
        return 0
    lines = ["Sprout: history warns about this commit (advisory)."]
    lines += [line for f in shown[:3] for line in _describe(f)]
    block = _blocks(shown)
    lines.append(
        "Commit stopped: it undoes a past security fix."
        if block and not _strict()
        else "Commit stopped (SPROUT_STRICT=1)."
        if block
        else "Committing anyway."
    )
    if block:
        lines.append("To commit regardless: git commit --no-verify, or SPROUT_SKIP=1 git commit.")
    print("\n".join(lines), file=sys.stderr)
    return BLOCKED if block else 0


def agent(event: Event, stdout: IO[str]) -> int:
    """Answer a PreToolUse event: a note for review findings, a question for high ones."""
    found = _event_lines(event)
    if found is None:
        return 0
    repo, changed = found
    shown = _shown(_check(repo, changed))
    if not shown:
        return 0
    note = "\n".join(
        ["Sprout (git history check, no model): this edit runs into past commits."]
        + [line for f in shown[:3] for line in _describe(f)]
        + [
            "Read the cited commit (the sprout explain_commit tool, or git show) before going on."
            " If you are undoing that fix or revert on purpose, tell the user why."
        ]
    )
    high = any(f.level is RiskLevel.HIGH for f in shown)
    decision = "deny" if high and _strict() else "ask" if high else "allow"
    output: dict[str, object] = {"hookEventName": "PreToolUse", "permissionDecision": decision}
    output["additionalContext"] = note
    if decision != "allow":
        output["permissionDecisionReason"] = note
    stdout.write(json.dumps({"hookSpecificOutput": output}) + "\n")
    return 0


def _event_lines(event: Event) -> tuple[Pygit2Repo, list[ChangedLine]] | None:
    """The repository and changed lines of an Edit, MultiEdit or Write event."""
    tool = event.get("tool_name")
    data = event.get("tool_input")
    if not isinstance(data, dict):
        return None
    tool_input = cast("Event", data)
    raw = tool_input.get("file_path")
    if tool not in ("Edit", "MultiEdit", "Write") or not isinstance(raw, str):
        return None
    file = Path(raw)
    cwd = event.get("cwd")
    repo = open_repo(file.parent if file.parent.is_dir() else str(cwd or "."))
    path = repo.relative_path(file)
    current = file.read_text(encoding="utf-8", errors="replace") if file.is_file() else ""
    if tool == "Write":
        return repo, edit_lines(path, current, str(tool_input.get("content", "")))
    edits = tool_input.get("edits") if tool == "MultiEdit" else [tool_input]
    changed: list[ChangedLine] = []
    for item in cast("list[Event]", edits if isinstance(edits, list) else []):
        old, new = str(item.get("old_string", "")), str(item.get("new_string", ""))
        changed += edit_lines(path, old, new, start=line_of(current, old))
    return repo, changed


def _check(repo: Pygit2Repo, changed: list[ChangedLine]) -> RiskCard | None:
    if not changed:
        return None
    try:
        with Store.open(repo.root, create=False) as store:
            return check_changes(store, changed, ignore=acks.ignored(repo.root))
    except IndexNotFoundError:
        return None


def _shown(card: RiskCard | None) -> list[RiskFinding]:
    """Findings at or above ``SPROUT_RISK_LEVEL`` (default review)."""
    if card is None:
        return []
    high_only = os.environ.get("SPROUT_RISK_LEVEL", "review").lower() == "high"
    return [f for f in card.findings if f.level is RiskLevel.HIGH or not high_only]


def _blocks(shown: list[RiskFinding]) -> bool:
    return bool(shown) and (_strict() or any(Label.SECURITY in f.labels for f in shown))


def _strict() -> bool:
    return os.environ.get("SPROUT_STRICT") == "1"


def _describe(f: RiskFinding) -> list[str]:
    c = f.commit
    tag = " [security]" if Label.SECURITY in f.labels else ""
    out = [
        f'- {f.level.value}: {c.hash[:12]} {c.authored_at:%Y-%m-%d} "{c.summary}"{tag}',
        f"  {_KIND[f.kind]} ({f.matched} of {f.total} lines): " + "; ".join(f.examples),
    ]
    if f.reason:
        out.append(f'  reason given: "{f.reason}"')
    return out
