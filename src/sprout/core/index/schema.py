"""SQLite schema for ``.sprout/index.db``."""

from __future__ import annotations

SCHEMA_VERSION = "1"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS commits (
    id              INTEGER PRIMARY KEY,
    hash            TEXT NOT NULL UNIQUE,
    committed_at    INTEGER NOT NULL,
    summary         TEXT NOT NULL,
    commit_json     TEXT NOT NULL,
    labels          TEXT NOT NULL,
    refs            TEXT NOT NULL,
    conv_type       TEXT,
    reverts_summary TEXT,
    files_truncated INTEGER NOT NULL,
    additions       INTEGER NOT NULL,
    deletions       INTEGER NOT NULL,
    llm_summary     TEXT,
    llm_model       TEXT
);
CREATE INDEX IF NOT EXISTS commits_time ON commits (committed_at);
CREATE INDEX IF NOT EXISTS commits_summary ON commits (summary);
CREATE INDEX IF NOT EXISTS commits_reverts_summary ON commits (reverts_summary);

CREATE TABLE IF NOT EXISTS files (
    commit_id INTEGER NOT NULL REFERENCES commits (id) ON DELETE CASCADE,
    path      TEXT NOT NULL,
    old_path  TEXT,
    kind      TEXT NOT NULL,
    additions INTEGER NOT NULL,
    deletions INTEGER NOT NULL,
    binary    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS files_path ON files (path);
CREATE INDEX IF NOT EXISTS files_commit ON files (commit_id);

CREATE TABLE IF NOT EXISTS hunks (
    commit_id INTEGER NOT NULL REFERENCES commits (id) ON DELETE CASCADE,
    path      TEXT NOT NULL,
    old_start INTEGER NOT NULL,
    old_lines INTEGER NOT NULL,
    new_start INTEGER NOT NULL,
    new_lines INTEGER NOT NULL,
    symbols   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS hunks_path ON hunks (path);
CREATE INDEX IF NOT EXISTS hunks_commit ON hunks (commit_id);

CREATE TABLE IF NOT EXISTS symbols (
    commit_id INTEGER NOT NULL REFERENCES commits (id) ON DELETE CASCADE,
    path      TEXT NOT NULL,
    name      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS symbols_name ON symbols (name);
CREATE INDEX IF NOT EXISTS symbols_commit ON symbols (commit_id);

CREATE TABLE IF NOT EXISTS reverts (
    commit_id INTEGER NOT NULL REFERENCES commits (id) ON DELETE CASCADE,
    target    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS reverts_target ON reverts (target);

CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5 (
    summary, body, paths, symbols, code, llm_summary,
    tokenize = 'porter unicode61'
);
"""

# Column weights for bm25(): summary, body, paths, symbols, code, llm_summary.
BM25_WEIGHTS = (6.0, 2.0, 1.5, 3.0, 0.5, 3.0)
