"""Read added and removed lines from unified diff text (``git diff``, ``diff -u``, a PR patch)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sprout.models import ChangedLine

_HUNK = re.compile(r"^@@ -(?P<old>\d+)(?:,(?P<oc>\d+))? \+(?P<new>\d+)(?:,(?P<nc>\d+))? @@")
_NULL = "/dev/null"


@dataclass
class _Hunk:
    old_no: int
    new_no: int
    old_left: int
    new_left: int

    @property
    def done(self) -> bool:
        return self.old_left <= 0 and self.new_left <= 0


def parse_unified(text: str) -> list[ChangedLine]:
    """Every ``+``/``-`` line inside a hunk, with its file path and line number.

    Hunks end after the line counts in their ``@@`` header, so file headers of the next
    file are never mistaken for changed lines.
    """
    out: list[ChangedLine] = []
    old_path = new_path = ""
    hunk: _Hunk | None = None
    for raw in text.splitlines():
        if hunk is not None and not hunk.done:
            _hunk_line(raw, hunk, old_path, new_path, out)
        elif match := _HUNK.match(raw):
            hunk = _Hunk(
                int(match["old"]),
                int(match["new"]),
                int(match["oc"] or 1),
                int(match["nc"] or 1),
            )
        elif raw.startswith("--- "):
            old_path = _path(raw[4:])
        elif raw.startswith("+++ "):
            new_path = _path(raw[4:])
    return out


def _hunk_line(raw: str, h: _Hunk, old_path: str, new_path: str, out: list[ChangedLine]) -> None:
    if raw.startswith("+"):
        out.append(ChangedLine(path=new_path or old_path, added=True, text=raw[1:], line=h.new_no))
        h.new_no, h.new_left = h.new_no + 1, h.new_left - 1
    elif raw.startswith("-"):
        out.append(ChangedLine(path=old_path or new_path, added=False, text=raw[1:], line=h.old_no))
        h.old_no, h.old_left = h.old_no + 1, h.old_left - 1
    elif not raw.startswith("\\"):  # context (" " or an empty line some tools emit)
        h.old_no, h.new_no = h.old_no + 1, h.new_no + 1
        h.old_left, h.new_left = h.old_left - 1, h.new_left - 1


def _path(header: str) -> str:
    """``a/src/x.py`` → ``src/x.py``; ``/dev/null`` → empty."""
    name = header.split("\t", 1)[0].strip()
    if name == _NULL:
        return ""
    return name[2:] if name[:2] in ("a/", "b/") else name
