"""Walk a line's history backwards, like ``git log -L`` for a single line."""

from __future__ import annotations

import shutil
import subprocess

from sprout.core.answer.blame import BlameLine, blame_line
from sprout.core.git.pygit2_repo import Pygit2Repo
from sprout.models import ChangeKind, CommitRecord, Hunk, LineHop

MAX_HOPS = 6
MAX_LOG = 20


def line_history(
    repo: Pygit2Repo, path: str, line: int, *, rev: str, max_hops: int = MAX_HOPS
) -> list[LineHop]:
    """Commits that shaped ``path:line`` as of ``rev``, newest first.

    Each hop blames the line, finds the hunk that changed it, maps it to the line it replaced
    in the parent, and blames that. It stops when a commit created the line from nothing.
    """
    hops: list[LineHop] = []
    seen: set[str] = set()
    target: tuple[str, str, int] | None = (rev, path, line)
    while target is not None and len(hops) < max_hops:
        blamed = blame_line(repo.root, *target)
        if blamed.commit in seen:
            break
        seen.add(blamed.commit)
        record = repo.read_commit(blamed.commit)
        hunk = _covering_hunk(record, blamed)
        introduced = (
            blamed.previous is None
            or hunk is None
            or hunk.old_lines == 0
            or _file_kind(record, blamed.path) is ChangeKind.ADDED
        )
        hops.append(
            LineHop(
                commit=record.commit,
                path=blamed.path,
                line=blamed.line,
                text=blamed.text,
                introduced=introduced,
            )
        )
        target = None if introduced or hunk is None else _parent_target(blamed, hunk)
    return hops


def line_log(
    repo: Pygit2Repo, path: str, line: int, *, rev: str, limit: int = MAX_LOG
) -> list[str]:
    """``git log -L`` for one line: every commit that changed it, newest first.

    The blame walk maps a line into each parent by offset, which can land on the wrong line
    when a hunk is rewritten unevenly, and ``blame -C`` can credit a copy of generic text
    elsewhere. ``git log -L`` tracks the line range itself, so its commits are kept too.
    Returns ``[]`` when the git CLI is missing or the line cannot be traced.
    """
    if limit <= 0 or not shutil.which("git"):
        return []
    args = ["git", "-C", str(repo.root), "log", rev, f"-L{line},{line}:{path}", "--format=%H"]
    args += ["-s", f"--max-count={limit}"]
    done = subprocess.run(args, capture_output=True, check=False)  # noqa: S603 - fixed argv
    if done.returncode != 0:
        return []
    return [h for h in done.stdout.decode().split() if len(h) == 40]


def _covering_hunk(record: CommitRecord, blamed: BlameLine) -> Hunk | None:
    for file in record.files:
        if file.path != blamed.path:
            continue
        for hunk in file.hunks:
            if hunk.new_lines and hunk.new_start <= blamed.line < hunk.new_start + hunk.new_lines:
                return hunk
    return None


def _file_kind(record: CommitRecord, path: str) -> ChangeKind | None:
    return next((f.kind for f in record.files if f.path == path), None)


def _parent_target(blamed: BlameLine, hunk: Hunk) -> tuple[str, str, int] | None:
    if blamed.previous is None:
        return None
    parent, parent_path = blamed.previous
    offset = min(blamed.line - hunk.new_start, hunk.old_lines - 1)
    return parent, parent_path, hunk.old_start + offset
