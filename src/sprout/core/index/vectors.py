"""Commit embeddings stored as float32 BLOBs, searched with a numpy dot product.

No SQLite extension is needed, so this works on every Python build. Some, such as the
python.org macOS builds, cannot load extensions at all. The search is a brute-force scan,
as sqlite-vec's would be, and the vector matrix is cached per open index.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from sprout.core.index.store import Store

# Bump when the document layout changes, so existing vectors are rebuilt.
DOC_VERSION = "2"
_CACHE_KEY = "vectors"
_MISSING = (
    "SELECT {cols} FROM commits c"
    " WHERE NOT EXISTS (SELECT 1 FROM vectors v WHERE v.commit_id = c.id)"
)

# What each commit's embedding is built from (also reused as the reranker's document text).
DOC_SQL = """
SELECT f.rowid, f.summary, substr(f.body, 1, 800), substr(f.paths, 1, 600),
       substr(f.symbols, 1, 600), f.llm_summary
FROM fts f WHERE f.rowid IN ({ids})
"""


def ensure_table(store: Store, model: str, dim: int) -> None:
    """Prepare for ``model``'s vectors; drop old ones if the model or document format changed."""
    if (
        store.get_meta("embedding_model") == model
        and store.get_meta("embedding_dim") == str(dim)
        and store.get_meta("embedding_doc_version") == DOC_VERSION
    ):
        return
    db = store.db
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute("DELETE FROM vectors")
        store.set_meta("embedding_model", model)
        store.set_meta("embedding_dim", str(dim))
        store.set_meta("embedding_doc_version", DOC_VERSION)
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
    store.cache.pop(_CACHE_KEY, None)


def unembedded(store: Store, limit: int) -> list[tuple[int, str]]:
    """Up to ``limit`` commits without a vector, as ``(id, document text)``."""
    rows = store.db.execute(
        _MISSING.format(cols="c.id") + " ORDER BY c.committed_at DESC LIMIT ?", (limit,)
    ).fetchall()
    ids = [int(r[0]) for r in rows]
    texts = documents(store, ids)
    return [(i, texts[i]) for i in ids if i in texts]


def count_unembedded(store: Store) -> int:
    """How many commits still need a vector."""
    return store.count(_MISSING.format(cols="count(*)"))


def add(store: Store, items: Sequence[tuple[int, Sequence[float]]]) -> None:
    """Store unit-length vectors in one transaction."""
    db = store.db
    db.execute("BEGIN IMMEDIATE")
    try:
        db.executemany(
            "INSERT OR REPLACE INTO vectors (commit_id, embedding) VALUES (?, ?)",
            [(i, _unit(v).tobytes()) for i, v in items],
        )
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
    store.cache.pop(_CACHE_KEY, None)


def knn(store: Store, query: Sequence[float], limit: int) -> list[tuple[int, float]]:
    """Nearest commits by cosine similarity (best first), with similarity scores."""
    ids, matrix = _matrix(store)
    if not len(ids):
        return []
    scores = matrix @ _unit(query)
    k = min(limit, len(ids))
    top = np.argpartition(-scores, k - 1)[:k]
    order = top[np.argsort(-scores[top])]
    return [(int(ids[i]), float(scores[i])) for i in order]


def documents(store: Store, ids: Sequence[int]) -> dict[int, str]:
    """Text used to embed and rerank each commit."""
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = store.db.execute(DOC_SQL.format(ids=marks), list(ids)).fetchall()
    out: dict[int, str] = {}
    for row in rows:
        summary, body, paths, symbols, llm = (str(x or "") for x in row[1:])
        # Most informative first: the embedder truncates at ~128 tokens.
        parts = [
            summary,
            llm,
            f"Symbols: {symbols[:300]}" if symbols else "",
            f"Files: {paths[:300]}" if paths else "",
            body,
        ]
        out[int(row[0])] = "\n".join(p for p in parts if p.strip())
    return out


def _unit(vector: Sequence[float]) -> NDArray[np.float32]:
    arr = np.asarray(vector, dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    return arr / norm if norm else arr


def _matrix(store: Store) -> tuple[NDArray[np.int64], NDArray[np.float32]]:
    cached = store.cache.get(_CACHE_KEY)
    if isinstance(cached, tuple):
        return cached  # pyright: ignore[reportUnknownVariableType]
    rows = store.db.execute("SELECT commit_id, embedding FROM vectors").fetchall()
    dim = int(store.get_meta("embedding_dim") or 0)
    ids = np.fromiter((int(r[0]) for r in rows), dtype=np.int64, count=len(rows))
    if rows and dim:
        matrix = np.frombuffer(b"".join(r[1] for r in rows), dtype=np.float32).reshape(-1, dim)
    else:
        matrix = np.zeros((0, max(dim, 1)), dtype=np.float32)
    store.cache[_CACHE_KEY] = (ids, matrix)
    return ids, matrix
