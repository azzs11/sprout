"""Commit embeddings stored in a sqlite-vec ``vec0`` table inside the index."""

from __future__ import annotations

from collections.abc import Sequence

from sprout.core.index.store import Store

# What each commit's embedding is built from (also reused as the reranker's document text).
DOC_SQL = """
SELECT f.rowid, f.summary, substr(f.body, 1, 800), substr(f.paths, 1, 600),
       substr(f.symbols, 1, 600), f.llm_summary
FROM fts f WHERE f.rowid IN ({ids})
"""


def ensure_table(store: Store, model: str, dim: int) -> None:
    """Create the vector table for ``model``; drop old vectors if the model changed."""
    current = store.get_meta("embedding_model")
    current_dim = store.get_meta("embedding_dim")
    exists = _exists(store)
    if exists and current == model and current_dim == str(dim):
        return
    db = store.db
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute("DROP TABLE IF EXISTS vec")
        db.execute(
            "CREATE VIRTUAL TABLE vec USING vec0("
            f"embedding float[{int(dim)}] distance_metric=cosine)"
        )
        store.set_meta("embedding_model", model)
        store.set_meta("embedding_dim", str(dim))
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise


def unembedded(store: Store, limit: int) -> list[tuple[int, str]]:
    """Up to ``limit`` commits without a vector, as ``(id, document text)``."""
    rows = store.db.execute(
        "SELECT c.id FROM commits c WHERE NOT EXISTS (SELECT 1 FROM vec v WHERE v.rowid = c.id)"
        " ORDER BY c.committed_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    ids = [int(r[0]) for r in rows]
    texts = documents(store, ids)
    return [(i, texts[i]) for i in ids if i in texts]


def count_unembedded(store: Store) -> int:
    """How many commits still need a vector."""
    return store.count(
        "SELECT count(*) FROM commits c WHERE NOT EXISTS (SELECT 1 FROM vec v WHERE v.rowid = c.id)"
    )


def add(store: Store, items: Sequence[tuple[int, Sequence[float]]]) -> None:
    """Store vectors in one transaction."""
    import sqlite_vec  # pyright: ignore[reportMissingTypeStubs]

    db = store.db
    db.execute("BEGIN IMMEDIATE")
    try:
        db.executemany(
            "INSERT OR REPLACE INTO vec (rowid, embedding) VALUES (?, ?)",
            [(i, sqlite_vec.serialize_float32(list(v))) for i, v in items],
        )
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise


def knn(store: Store, query: Sequence[float], limit: int) -> list[tuple[int, float]]:
    """Nearest commits by cosine similarity (best first), with similarity scores."""
    import sqlite_vec  # pyright: ignore[reportMissingTypeStubs]

    rows = store.db.execute(
        "SELECT rowid, distance FROM vec WHERE embedding MATCH ? AND k = ? ORDER BY distance",
        (sqlite_vec.serialize_float32(list(query)), limit),
    ).fetchall()
    return [(int(r[0]), 1.0 - float(r[1])) for r in rows]


def documents(store: Store, ids: Sequence[int]) -> dict[int, str]:
    """Text used to embed and rerank each commit."""
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = store.db.execute(DOC_SQL.format(ids=marks), list(ids)).fetchall()
    out: dict[int, str] = {}
    for row in rows:
        summary, body, paths, symbols, llm = (str(x or "") for x in row[1:])
        parts = [
            summary,
            llm,
            body,
            f"Files: {paths}" if paths else "",
            f"Symbols: {symbols}" if symbols else "",
        ]
        out[int(row[0])] = "\n".join(p for p in parts if p.strip())
    return out


def _exists(store: Store) -> bool:
    return store.db.execute("SELECT 1 FROM sqlite_master WHERE name = 'vec'").fetchone() is not None
