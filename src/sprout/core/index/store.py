"""The history index: one SQLite file holding metadata, FTS5 and sqlite-vec vectors."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType

from sprout.core.index import schema
from sprout.core.index.text import expand_identifiers, fts_query
from sprout.errors import IndexNotFoundError, SproutError
from sprout.models import CommitRecord, IndexStats

INDEX_DIR = ".sprout"
INDEX_FILE = "index.db"


class Store:
    """Read and write one repository's index. Every write method is one transaction."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._db = sqlite3.connect(path, isolation_level=None)
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.execute("PRAGMA synchronous = NORMAL")
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA busy_timeout = 5000")
        self.vectors_available = _load_sqlite_vec(self._db)
        self._db.executescript(schema.SCHEMA)
        version = self.get_meta("schema_version")
        if version is None:
            self.set_meta("schema_version", schema.SCHEMA_VERSION)
        elif version != schema.SCHEMA_VERSION:
            raise SproutError(
                f"The index at {path} uses schema {version}, "
                f"but this Sprout needs {schema.SCHEMA_VERSION}.",
                hint="Rebuild it with: sprout index --rebuild",
            )

    @classmethod
    def open(cls, base: Path, *, create: bool) -> Store:
        """Open ``base/.sprout/index.db``. With ``create``, make the folder if needed."""
        folder = base / INDEX_DIR
        db = folder / INDEX_FILE
        if not db.exists():
            if not create:
                raise IndexNotFoundError(str(base))
            folder.mkdir(parents=True, exist_ok=True)
            # Keeps the index out of `git status` without touching the user's .gitignore.
            (folder / ".gitignore").write_text("*\n", encoding="utf-8")
        return cls(db)

    def close(self) -> None:
        """Close the connection."""
        self._db.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # ----- meta -------------------------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        """Read a metadata value."""
        row = self._db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row[0])

    def set_meta(self, key: str, value: str) -> None:
        """Write a metadata value."""
        self._db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))

    # ----- commits ----------------------------------------------------------------

    def known_hashes(self) -> set[str]:
        """Hashes of every indexed commit."""
        return {str(r[0]) for r in self._db.execute("SELECT hash FROM commits")}

    def add_records(self, records: Sequence[CommitRecord]) -> None:
        """Insert commits (skipping ones already present) in a single transaction."""
        with self._transaction():
            for record in records:
                self._insert(record)

    def delete_hashes(self, hashes: Iterable[str]) -> int:
        """Remove commits (for example after history was rewritten and garbage-collected)."""
        removed = 0
        with self._transaction():
            for hash_ in hashes:
                row = self._db.execute("SELECT id FROM commits WHERE hash = ?", (hash_,)).fetchone()
                if row is None:
                    continue
                self._db.execute("DELETE FROM fts WHERE rowid = ?", (row[0],))
                if self._has_vec_table():
                    self._db.execute("DELETE FROM vec WHERE rowid = ?", (row[0],))
                self._db.execute("DELETE FROM commits WHERE id = ?", (row[0],))
                removed += 1
        return removed

    def _insert(self, record: CommitRecord) -> None:
        commit = record.commit
        info = record.message_info
        cursor = self._db.execute(
            "INSERT OR IGNORE INTO commits (hash, committed_at, summary, commit_json, labels, refs,"
            " conv_type, reverts_summary, files_truncated, additions, deletions)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                commit.hash,
                int(commit.committed_at.timestamp()),
                commit.summary,
                commit.model_dump_json(),
                json.dumps([label.value for label in info.labels]),
                json.dumps([ref.model_dump() for ref in info.refs]),
                info.conventional_type,
                info.reverts_summary,
                int(record.files_truncated),
                sum(f.additions for f in record.files),
                sum(f.deletions for f in record.files),
            ),
        )
        if cursor.rowcount == 0:
            return
        commit_id = cursor.lastrowid
        self._insert_children(commit_id, record)
        body = commit.message.split("\n", 1)[1] if "\n" in commit.message else ""
        symbols = list(dict.fromkeys(s for f in record.files for s in f.symbols))
        self._db.execute(
            "INSERT INTO fts (rowid, summary, body, paths, symbols, code, llm_summary)"
            " VALUES (?, ?, ?, ?, ?, ?, '')",
            (
                commit_id,
                expand_identifiers(commit.summary),
                body,
                expand_identifiers(" ".join(f.path for f in record.files)),
                expand_identifiers(" ".join(symbols)),
                expand_identifiers(" ".join(record.code_terms)),
            ),
        )

    def _insert_children(self, commit_id: int | None, record: CommitRecord) -> None:
        for file in record.files:
            self._db.execute(
                "INSERT INTO files (commit_id, path, old_path, kind, additions, deletions, binary)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    commit_id,
                    file.path,
                    file.old_path,
                    file.kind.value,
                    file.additions,
                    file.deletions,
                    int(file.binary),
                ),
            )
            self._db.executemany(
                "INSERT INTO hunks (commit_id, path, old_start, old_lines, new_start, new_lines,"
                " symbols) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        commit_id,
                        file.path,
                        h.old_start,
                        h.old_lines,
                        h.new_start,
                        h.new_lines,
                        json.dumps(h.symbols),
                    )
                    for h in file.hunks
                ],
            )
            self._db.executemany(
                "INSERT INTO symbols (commit_id, path, name) VALUES (?, ?, ?)",
                [(commit_id, file.path, name) for name in file.symbols],
            )
        self._db.executemany(
            "INSERT INTO reverts (commit_id, target) VALUES (?, ?)",
            [(commit_id, target) for target in record.message_info.reverts],
        )

    # ----- keyword search -----------------------------------------------------------

    def bm25(self, query: str, limit: int) -> list[tuple[int, float]]:
        """Commit ids ranked by BM25 (best first) with their scores (higher is better)."""
        match = fts_query(query)
        if match is None:
            return []
        weights = ", ".join(str(w) for w in schema.BM25_WEIGHTS)
        rows = self._db.execute(
            f"SELECT rowid, bm25(fts, {weights}) AS score FROM fts WHERE fts MATCH ?"  # noqa: S608
            " ORDER BY score LIMIT ?",
            (match, limit),
        ).fetchall()
        return [(int(r[0]), -float(r[1])) for r in rows]

    # ----- stats --------------------------------------------------------------------

    def count(self, sql: str) -> int:
        """Return the single integer a counting query produces."""
        return int(self._db.execute(sql).fetchone()[0])

    def stats(self) -> IndexStats:
        """Summary of what is indexed."""
        updated = self.get_meta("updated_at")
        embedded = self.count("SELECT count(*) FROM vec") if self._has_vec_table() else 0
        return IndexStats(
            db_path=str(self.path),
            commits=self.count("SELECT count(*) FROM commits"),
            embedded=embedded,
            summarised=self.count("SELECT count(*) FROM commits WHERE llm_summary IS NOT NULL"),
            reverts=self.count("SELECT count(*) FROM commits WHERE labels LIKE '%\"revert\"%'"),
            head=self.get_meta("head"),
            updated_at=datetime.fromisoformat(updated) if updated else None,
            embedding_model=self.get_meta("embedding_model"),
            vectors_available=self.vectors_available,
        )

    def mark_updated(self, head: str | None) -> None:
        """Record the HEAD and time of the latest successful index run."""
        with self._transaction():
            self.set_meta("head", head or "")
            self.set_meta("updated_at", datetime.now(UTC).isoformat())

    # ----- helpers ------------------------------------------------------------------

    @property
    def db(self) -> sqlite3.Connection:
        """Raw connection, used by the vector and hit helpers in this package."""
        return self._db

    def _has_vec_table(self) -> bool:
        row = self._db.execute("SELECT 1 FROM sqlite_master WHERE name = 'vec'").fetchone()
        return row is not None

    def _transaction(self) -> _Transaction:
        return _Transaction(self._db)


class _Transaction:
    """``BEGIN IMMEDIATE`` ... ``COMMIT``, rolled back on any error (including Ctrl-C)."""

    def __init__(self, db: sqlite3.Connection) -> None:
        self._db = db

    def __enter__(self) -> None:
        self._db.execute("BEGIN IMMEDIATE")

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._db.execute("ROLLBACK" if exc_type else "COMMIT")


def _load_sqlite_vec(db: sqlite3.Connection) -> bool:
    """Load the sqlite-vec extension. Some Python builds cannot load extensions at all."""
    try:
        import sqlite_vec  # pyright: ignore[reportMissingTypeStubs]

        db.enable_load_extension(True)
        sqlite_vec.load(db)
        db.enable_load_extension(False)
    except (AttributeError, ImportError, sqlite3.OperationalError):
        return False
    return True
