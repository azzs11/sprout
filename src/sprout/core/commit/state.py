"""Operations where git writes the commit message itself, so Sprout should not draft one."""

from __future__ import annotations

from pathlib import Path

_PENDING = (
    ("MERGE_HEAD", "merge"),
    ("REVERT_HEAD", "revert"),
    ("CHERRY_PICK_HEAD", "cherry-pick"),
    ("rebase-merge", "rebase"),
    ("rebase-apply", "rebase"),
)


def pending_operation(git_dir: Path) -> str | None:
    """'merge', 'revert', 'cherry-pick' or 'rebase' when one is in progress, else None."""
    for name, operation in _PENDING:
        if (git_dir / name).exists():
            return operation
    return None
