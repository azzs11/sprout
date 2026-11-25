"""Turn an agent's file edit (old text to new text) into lines for ``check_changes``."""

from __future__ import annotations

import difflib
from collections.abc import Sequence
from pathlib import Path

from sprout.core.git.pygit2_repo import Pygit2Repo
from sprout.models import ChangedLine


def edit_lines(path: str, old: str, new: str, *, start: int = 1) -> list[ChangedLine]:
    """Lines removed from ``old`` and added in ``new``, as a line diff would show them.

    ``start`` is the 1-based line where ``old`` begins in the file, when known.
    """
    before, after = old.splitlines(), new.splitlines()
    out: list[ChangedLine] = []
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        out += [
            ChangedLine(path=path, added=False, text=before[i], line=start + i)
            for i in range(i1, i2)
        ]
        out += [
            ChangedLine(path=path, added=True, text=after[j], line=start + j) for j in range(j1, j2)
        ]
    return out


def file_change(
    repo: Pygit2Repo, path: str, edits: Sequence[tuple[str | None, str]]
) -> tuple[list[ChangedLine], list[ChangedLine]]:
    """The whole file's changed lines against HEAD, before and after a proposed edit.

    Comparing the whole file means a change split across several small edits is still seen as
    one change. ``edits`` are ``(old, new)`` pairs applied in order; ``old=None`` replaces the
    whole file (a Write). An ``old`` text that is not in the file is checked on its own.

    Raises:
        PathOutsideRepositoryError: ``path`` is not inside the repository.
    """
    file = Path(path) if Path(path).is_absolute() else repo.root / path
    rel = repo.relative_path(file)
    current = file.read_text(encoding="utf-8", errors="replace") if file.is_file() else ""
    head = _head_text(repo, rel)
    proposed, unplaced = current, list[ChangedLine]()
    for old, new in edits:
        if old is None:
            proposed = new
        elif old and old in proposed:
            proposed = proposed.replace(old, new, 1)
        else:
            unplaced += edit_lines(rel, old, new)
    return edit_lines(rel, head, current), edit_lines(rel, head, proposed) + unplaced


def _head_text(repo: Pygit2Repo, path: str) -> str:
    head = repo.head_hash
    if head is None:  # no commits yet
        return ""
    data = repo.read_file(head, path)
    return data.decode("utf-8", errors="replace") if data is not None else ""
