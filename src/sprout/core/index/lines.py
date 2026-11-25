"""Line fingerprints of fix, security and revert commits, for Regression Memory.

Each kept line is whitespace-normalised and hashed, so matches survive re-indentation and
renames. Lines too short to mean anything are dropped. Bump ``LINES_VERSION`` when the
rules change: existing fingerprints are then rebuilt on the next ``sprout index``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from sprout.core.index.store import Store
from sprout.models import ChangedLine

LINES_VERSION = "1"
MAX_LINES = 2_000  # commits changing more lines (mass reformat, vendoring) are not fingerprinted
MIN_CHARS = 6
MIN_ALNUM = 4
_PENDING = """
SELECT {cols} FROM commits c
WHERE (c.labels LIKE '%"fix"%' OR c.labels LIKE '%"security"%' OR c.labels LIKE '%"revert"%')
  AND c.labels NOT LIKE '%"merge"%'
  AND NOT EXISTS (SELECT 1 FROM line_commits l WHERE l.commit_id = c.id)
"""


def normalize(text: str) -> str | None:
    """``text`` with whitespace collapsed, or None when the line is too trivial to match on."""
    norm = " ".join(text.split())
    if len(norm) < MIN_CHARS or sum(ch.isalnum() for ch in norm) < MIN_ALNUM:
        return None
    return norm


def line_hash(norm: str) -> int:
    """A stable signed 64-bit hash (Python's ``hash`` changes between runs)."""
    digest = hashlib.blake2b(norm.encode("utf-8", errors="replace"), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


def ensure_version(store: Store) -> None:
    """Drop fingerprints made by older rules, so they are rebuilt."""
    if store.get_meta("lines_version") == LINES_VERSION:
        return
    db = store.db
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute("DELETE FROM lines")
        db.execute("DELETE FROM line_commits")
        store.set_meta("lines_version", LINES_VERSION)
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise


def count_pending(store: Store) -> int:
    """Signal commits whose lines are not fingerprinted yet."""
    return store.count(_PENDING.format(cols="count(*)"))


def pending(store: Store, limit: int) -> list[tuple[int, str]]:
    """Up to ``limit`` signal commits to fingerprint, as ``(id, hash)``."""
    rows = store.db.execute(_PENDING.format(cols="c.id, c.hash") + " LIMIT ?", (limit,)).fetchall()
    return [(int(r[0]), str(r[1])) for r in rows]


def save(store: Store, items: Sequence[tuple[int, Sequence[ChangedLine]]]) -> None:
    """Store each commit's kept lines in one transaction; huge commits keep none."""
    db = store.db
    db.execute("BEGIN IMMEDIATE")
    try:
        for commit_id, changed in items:
            rows = _rows(commit_id, changed) if len(changed) < MAX_LINES else []
            db.executemany(
                "INSERT INTO lines (commit_id, added, hash, path, line) VALUES (?, ?, ?, ?, ?)",
                rows,
            )
            db.execute(
                "INSERT OR REPLACE INTO line_commits (commit_id, kept) VALUES (?, ?)",
                (commit_id, len(rows)),
            )
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise


def _rows(commit_id: int, changed: Sequence[ChangedLine]) -> list[tuple[int, int, int, str, int]]:
    seen: set[tuple[bool, int, str]] = set()
    rows: list[tuple[int, int, int, str, int]] = []
    for c in changed:
        norm = normalize(c.text)
        if norm is None:
            continue
        key = (c.added, line_hash(norm), c.path)
        if key not in seen:
            seen.add(key)
            rows.append((commit_id, int(c.added), key[1], c.path, c.line))
    return rows
