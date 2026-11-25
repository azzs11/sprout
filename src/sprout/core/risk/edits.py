"""Turn an agent's file edit (old text to new text) into lines for ``check_changes``."""

from __future__ import annotations

import difflib

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


def line_of(text: str, snippet: str) -> int:
    """1-based line where ``snippet`` first starts in ``text`` (1 if it is not found)."""
    index = text.find(snippet) if snippet else -1
    return text.count("\n", 0, index) + 1 if index >= 0 else 1
