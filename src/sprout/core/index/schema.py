"""SQLite schema for ``.sprout/index.db``."""

from __future__ import annotations

SCHEMA_VERSION = "2"  # 2: vectors moved from sqlite-vec to a plain BLOB table

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

-- Regression Memory: normalised line hashes of fix, security and revert commits.
CREATE TABLE IF NOT EXISTS lines (
    commit_id INTEGER NOT NULL REFERENCES commits (id) ON DELETE CASCADE,
    added     INTEGER NOT NULL,
    hash      INTEGER NOT NULL,
    path      TEXT NOT NULL,
    line      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS lines_hash ON lines (hash);
CREATE INDEX IF NOT EXISTS lines_commit ON lines (commit_id);
CREATE TABLE IF NOT EXISTS line_commits (
    commit_id INTEGER PRIMARY KEY REFERENCES commits (id) ON DELETE CASCADE,
    kept      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS vectors (
    commit_id INTEGER PRIMARY KEY REFERENCES commits (id) ON DELETE CASCADE,
    embedding BLOB NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5 (
    summary, body, paths, symbols, code, llm_summary,
    tokenize = 'porter unicode61'
);
"""

# Column weights for bm25(): summary, body, paths, symbols, code, llm_summary.
BM25_WEIGHTS = (6.0, 2.0, 1.5, 3.0, 0.5, 3.0)
