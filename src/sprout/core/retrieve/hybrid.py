"""Hybrid retrieval: BM25 + vector search fused with Reciprocal Rank Fusion, then reranked."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from sprout.core.index import vectors
from sprout.core.index.embedder import Embedder
from sprout.core.index.hits import load_hits
from sprout.core.index.store import Store
from sprout.core.retrieve.rerank import Reranker
from sprout.errors import ModelError, VectorsUnavailableError
from sprout.models import SearchMode, SearchResults

POOL = 50  # candidates taken from each retriever
RERANK_POOL = 30  # fused candidates passed to the cross-encoder
RRF_K = 60


def search(
    store: Store,
    query: str,
    *,
    mode: SearchMode = SearchMode.HYBRID,
    limit: int = 10,
    embedder: Embedder | None = None,
    reranker: Reranker | None = None,
) -> SearchResults:
    """Rank indexed commits for ``query``.

    In hybrid mode, vector search is used when vectors exist for the configured model and
    quietly skipped otherwise; ``mode=vector`` raises instead.
    """
    lists: dict[str, list[tuple[int, float]]] = {}
    notes: list[str] = []
    if mode is not SearchMode.VECTOR:
        lists["bm25"] = store.bm25(query, POOL)
    if mode is not SearchMode.BM25:
        reason = _vector_problem(store, embedder)
        if reason is None and embedder is not None:
            try:
                lists["vector"] = vectors.knn(store, embedder.embed_query(query), POOL)
            except ModelError as exc:
                if mode is SearchMode.VECTOR:
                    raise
                notes.append(f"Semantic search skipped: {exc.message}")
        elif mode is SearchMode.VECTOR:
            raise VectorsUnavailableError(reason or "no embedding model configured.")
        elif embedder is not None and reason:
            notes.append(f"Semantic search skipped: {reason}")
    fused = fuse(lists)
    reranked = False
    if reranker is not None and fused:
        try:
            fused = _rerank(store, query, fused[:RERANK_POOL], reranker)
            reranked = True
        except ModelError as exc:
            notes.append(f"Reranking skipped: {exc.message}")
    hits = load_hits(store, fused[:limit])
    return SearchResults(query=query, mode=mode, reranked=reranked, hits=hits, notes=notes)


def fuse(lists: dict[str, list[tuple[int, float]]]) -> list[tuple[int, float, list[str]]]:
    """Reciprocal Rank Fusion. Returns ``(id, fused score, retrievers)``, best first."""
    scores: dict[int, float] = defaultdict(float)
    sources: dict[int, list[str]] = defaultdict(list)
    for name, ranked in lists.items():
        for rank, (commit_id, _) in enumerate(ranked, start=1):
            scores[commit_id] += 1.0 / (RRF_K + rank)
            sources[commit_id].append(name)
    order = sorted(scores, key=lambda i: (-scores[i], i))
    return [(i, scores[i], sources[i]) for i in order]


def _rerank(
    store: Store,
    query: str,
    candidates: Sequence[tuple[int, float, list[str]]],
    reranker: Reranker,
) -> list[tuple[int, float, list[str]]]:
    docs = vectors.documents(store, [c[0] for c in candidates])
    kept = [c for c in candidates if c[0] in docs]
    scores = reranker.score(query, [docs[c[0]] for c in kept])
    rescored = [(c[0], s, [*c[2], "rerank"]) for c, s in zip(kept, scores, strict=True)]
    return sorted(rescored, key=lambda c: -c[1])


def _vector_problem(store: Store, embedder: Embedder | None) -> str | None:
    if embedder is None:
        return "no embedding model configured."
    if not store.vectors_available:
        return "this Python cannot load SQLite extensions."
    if store.get_meta("embedding_model") != embedder.name:
        return f"the index has no vectors for {embedder.name}; run sprout index."
    return None
