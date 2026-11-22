"""Real local models (downloads ~150 MB once). Opt-in: SPROUT_TEST_MODELS=1 pytest -m models."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest

from sprout.core.git import open_repo
from sprout.core.index.embedder import DEFAULT_EMBED_MODEL, FastEmbedder
from sprout.core.index.indexer import build_index
from sprout.core.index.store import Store
from sprout.core.retrieve.hybrid import search
from sprout.core.retrieve.rerank import DEFAULT_RERANK_MODEL, FastReranker
from tests.fixtures.builder import RepoBuilder

pytestmark = [
    pytest.mark.models,
    pytest.mark.skipif(
        os.environ.get("SPROUT_TEST_MODELS") != "1", reason="set SPROUT_TEST_MODELS=1"
    ),
]

CACHE = Path(
    os.environ.get("SPROUT_TEST_MODEL_CACHE", Path.home() / ".cache" / "sprout-test-models")
)


def test_semantic_search_finds_paraphrase(make_repo: Callable[[str], RepoBuilder]) -> None:
    built = make_repo("payments")
    embedder = FastEmbedder(DEFAULT_EMBED_MODEL, CACHE)
    reranker = FastReranker(DEFAULT_RERANK_MODEL, CACHE)
    with Store.open(built.root, create=True) as store:
        stats = build_index(open_repo(built.root), store, embedder=embedder)
        assert stats.embedded == 7
        results = search(
            store, "protect against timing side channels", embedder=embedder, reranker=reranker
        )
    assert results.reranked
    assert not results.notes
    top = [h.commit.summary for h in results.hits[:2]]
    assert any("constant time" in s for s in top)
