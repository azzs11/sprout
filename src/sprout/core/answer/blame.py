"""Blame one line.

Uses ``git blame --porcelain`` (fast, follows moves and renames, ignores whitespace, honours
``.git-blame-ignore-revs``) and falls back to libgit2 when the git CLI is unavailable.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pygit2

from sprout.errors import SproutError

IGNORE_REVS_FILE = ".git-blame-ignore-revs"


@dataclass(frozen=True)
class BlameLine:
    """Who last changed one line, and where that line was in their commit."""

    commit: str
    path: str  # path in ``commit``
    line: int  # 1-based line in ``commit``'s version of the file
    text: str
    previous: tuple[str, str] | None  # (parent commit, path in parent), None if introduced


class LineNotFoundError(SproutError):
    """Raised when a file or line does not exist at the requested revision."""


def blame_line(root: Path, rev: str, path: str, line: int) -> BlameLine:
    """Blame ``path:line`` as of ``rev``."""
    if shutil.which("git"):
        return _blame_cli(root, rev, path, line)
    return _blame_libgit2(root, rev, path, line)


def _blame_cli(root: Path, rev: str, path: str, line: int) -> BlameLine:
    # -w ignores whitespace-only edits; -M and -C follow lines moved within and across files
    # (measured on pytest: -C traces 6/7 lines past a "split into own module" commit, +20 ms).
    args = ["git", "-C", str(root), "blame", "--porcelain", "-w", "-M", "-C"]
    args += ["-L", f"{line},{line}"]
    if (root / IGNORE_REVS_FILE).is_file():
        args += ["--ignore-revs-file", IGNORE_REVS_FILE]
    done = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [*args, rev, "--", path], capture_output=True, check=False
    )
    if done.returncode != 0:
        message = done.stderr.decode("utf-8", errors="replace").strip()
        raise LineNotFoundError(
            f"Could not blame {path}:{line} at {rev[:12]}: {message}",
            hint="Check the path and that the line number is inside the file at that commit.",
        )
    return parse_porcelain(done.stdout, fallback_path=path)


def parse_porcelain(raw: bytes, *, fallback_path: str) -> BlameLine:
    """Parse the porcelain output for a single blamed line."""
    lines = raw.split(b"\n")
    header = lines[0].decode("ascii").split()
    commit, orig_line = header[0], int(header[1])
    path = fallback_path
    previous: tuple[str, str] | None = None
    text = ""
    for raw_line in lines[1:]:
        if raw_line.startswith(b"\t"):
            text = raw_line[1:].decode("utf-8", errors="replace")
            break
        key, _, value = raw_line.decode("utf-8", errors="replace").partition(" ")
        if key == "filename":
            path = value
        elif key == "previous":
            prev_commit, _, prev_path = value.partition(" ")
            previous = (prev_commit, prev_path)
    return BlameLine(commit=commit, path=path, line=orig_line, text=text, previous=previous)


def _blame_libgit2(root: Path, rev: str, path: str, line: int) -> BlameLine:
    repo = pygit2.Repository(str(root))
    try:
        newest = repo.revparse_single(rev).peel(pygit2.Commit)
        blame = repo.blame(path, newest_commit=newest.id, min_line=line, max_line=line)
        hunk = blame.for_line(line)
    except (KeyError, ValueError, IndexError, pygit2.GitError) as exc:
        raise LineNotFoundError(f"Could not blame {path}:{line} at {rev[:12]}: {exc}") from exc
    commit = repo[hunk.final_commit_id].peel(pygit2.Commit)
    orig_path = hunk.orig_path or path
    orig_line = hunk.orig_start_line_number + (line - hunk.final_start_line_number)
    text = _line_text(repo, commit, orig_path, orig_line)
    previous = (str(commit.parent_ids[0]), orig_path) if commit.parent_ids else None
    return BlameLine(str(commit.id), orig_path, orig_line, text, previous)


def _line_text(repo: pygit2.Repository, commit: pygit2.Commit, path: str, line: int) -> str:
    try:
        blob = repo.get(commit.tree[path].id)
    except KeyError:
        return ""
    if not isinstance(blob, pygit2.Blob):
        return ""
    rows = blob.data.split(b"\n")
    return rows[line - 1].decode("utf-8", errors="replace") if 0 < line <= len(rows) else ""
