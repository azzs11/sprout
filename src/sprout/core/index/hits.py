"""Load indexed commits back into ``SearchHit`` models."""

from __future__ import annotations

import json
from collections.abc import Sequence

from sprout.core.index.store import Store
from sprout.models import Commit, IssueRef, Label, SearchHit

MAX_LISTED = 12


def load_hits(store: Store, ranked: Sequence[tuple[int, float, list[str]]]) -> list[SearchHit]:
    """Build hits for ``(commit id, score, retrievers)`` in the given order."""
    hits: list[SearchHit] = []
    for rank, (commit_id, score, retrievers) in enumerate(ranked, start=1):
        row = store.db.execute(
            "SELECT commit_json, labels, refs, hash, summary FROM commits WHERE id = ?",
            (commit_id,),
        ).fetchone()
        if row is None:
            continue
        hits.append(
            SearchHit(
                rank=rank,
                score=round(score, 6),
                commit=Commit.model_validate_json(row[0]),
                labels=[Label(v) for v in json.loads(row[1])],
                files=_column(store, "SELECT path FROM files WHERE commit_id = ?", commit_id),
                symbols=_column(
                    store, "SELECT DISTINCT name FROM symbols WHERE commit_id = ?", commit_id
                ),
                refs=[IssueRef.model_validate(r) for r in json.loads(row[2])],
                reverted_by=reverted_by(store, row[3], row[4]),
                retrievers=retrievers,
            )
        )
    return hits


def reverted_by(store: Store, hash_: str, summary: str) -> list[str]:
    """Indexed commits that revert this one, by hash or by quoted summary."""
    rows = store.db.execute(
        "SELECT c.hash FROM reverts r JOIN commits c ON c.id = r.commit_id"
        " WHERE r.target = ? OR (length(r.target) < 40 AND ? LIKE r.target || '%')"
        " UNION SELECT hash FROM commits WHERE reverts_summary = ? AND hash != ?",
        (hash_, hash_, summary, hash_),
    ).fetchall()
    return sorted({str(r[0]) for r in rows})


def _column(store: Store, sql: str, commit_id: int) -> list[str]:
    rows = store.db.execute(sql + f" LIMIT {MAX_LISTED}", (commit_id,)).fetchall()
    return [str(r[0]) for r in rows]
