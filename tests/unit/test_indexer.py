"""Tests for building, resuming and querying the history index (all models faked)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from sprout.core.git import open_repo
from sprout.core.index import vectors
from sprout.core.index.indexer import IndexOptions, NullProgress, build_index
from sprout.core.index.store import Store
from sprout.core.index.summarise import Summariser
from sprout.core.retrieve.hybrid import fuse, search
from sprout.errors import IndexNotFoundError, NoCommitsError, SproutError, VectorsUnavailableError
from sprout.models import Label, SearchMode
from tests.fakes import FakeEmbedder, FakeProvider, FakeReranker
from tests.fixtures.builder import RepoBuilder

MakeRepo = Callable[[str], RepoBuilder]


@pytest.fixture
def payments(make_repo: MakeRepo) -> RepoBuilder:
    return make_repo("payments")


@pytest.fixture
def store(payments: RepoBuilder) -> Iterator[Store]:
    with Store.open(payments.root, create=True) as s:
        yield s


def _index(built: RepoBuilder, store: Store, **kwargs: object):
    return build_index(open_repo(built.root), store, **kwargs)  # type: ignore[arg-type]


# ----- building -------------------------------------------------------------------


def test_index_records_every_commit(payments: RepoBuilder, store: Store) -> None:
    stats = _index(payments, store)
    assert stats.commits == 7
    assert stats.reverts == 1
    assert stats.head == payments.head()
    assert stats.updated_at is not None


def test_index_folder_is_git_ignored(payments: RepoBuilder, store: Store) -> None:
    _index(payments, store)
    assert (payments.root / ".sprout" / ".gitignore").read_text() == "*\n"
    assert payments.git("status", "--porcelain") == ""


def test_empty_repository_raises_with_hint(make_repo: MakeRepo) -> None:
    built = make_repo("empty")
    with Store.open(built.root, create=True) as s, pytest.raises(NoCommitsError) as info:
        _index(built, s)
    assert info.value.hint is not None


def test_open_without_index_raises(tmp_path: Path) -> None:
    with pytest.raises(IndexNotFoundError):
        Store.open(tmp_path, create=False)


def test_schema_mismatch_asks_for_rebuild(payments: RepoBuilder, store: Store) -> None:
    store.set_meta("schema_version", "999")
    store.close()
    with pytest.raises(SproutError) as info:
        Store.open(payments.root, create=False)
    assert "--rebuild" in (info.value.hint or "")


# ----- incremental and resumable --------------------------------------------------


def test_reindex_only_adds_new_commits(payments: RepoBuilder, store: Store) -> None:
    _index(payments, store)
    payments.write("src/new.py", "def added():\n    return 1\n").commit("feat: add new module")
    progress = _CountingProgress()
    stats = _index(payments, store, progress=progress)
    assert stats.commits == 8
    assert progress.totals["commits"] == 1


def test_interrupted_index_resumes(payments: RepoBuilder, store: Store) -> None:
    with pytest.raises(KeyboardInterrupt):
        _index(payments, store, progress=_InterruptAfter(2), options=IndexOptions(batch_size=2))
    assert store.stats().commits == 2  # the finished batch survived, the next one rolled back
    assert _index(payments, store).commits == 7


def test_rewritten_history_is_pruned(payments: RepoBuilder, store: Store) -> None:
    _index(payments, store)
    payments.git("reset", "--quiet", "--hard", "HEAD~2")
    payments.git("reflog", "expire", "--expire=now", "--all")
    payments.git("gc", "--quiet", "--prune=now")
    assert _index(payments, store).commits == 5


def test_since_limits_history(payments: RepoBuilder, store: Store) -> None:
    from datetime import UTC, datetime

    stats = _index(
        payments, store, options=IndexOptions(since=datetime(2024, 1, 1, 14, tzinfo=UTC))
    )
    assert 0 < stats.commits < 7


# ----- keyword search --------------------------------------------------------------


def test_bm25_finds_by_message_and_symbol(payments: RepoBuilder, store: Store) -> None:
    _index(payments, store)
    results = search(store, "retry failed charges three times", mode=SearchMode.BM25)
    assert results.hits[0].commit.summary.startswith("feat(payments): retry failed charges")
    by_symbol = search(store, "verify_token", mode=SearchMode.BM25)
    assert all("verify_token" in h.symbols for h in by_symbol.hits)
    assert len(by_symbol.hits) == 3


def test_camel_and_snake_case_are_split(payments: RepoBuilder, store: Store) -> None:
    _index(payments, store)
    hits = search(store, "payment client", mode=SearchMode.BM25).hits
    assert any("PaymentClient" in h.symbols for h in hits)


@pytest.mark.parametrize("query", ['"', "NEAR(", "a AND OR", "*", "-- DROP TABLE commits", ""])
def test_hostile_queries_do_not_crash(payments: RepoBuilder, store: Store, query: str) -> None:
    _index(payments, store)
    search(store, query, mode=SearchMode.BM25)


def test_reverted_commit_knows_its_revert(payments: RepoBuilder, store: Store) -> None:
    _index(payments, store)
    hits = search(store, "disable charge retries latency", mode=SearchMode.BM25).hits
    perf = next(h for h in hits if h.commit.summary.startswith("perf(payments)"))
    assert len(perf.reverted_by) == 1
    revert = next(h for h in hits if Label.REVERT in h.labels)
    assert perf.reverted_by == [revert.commit.hash]


def test_hits_carry_refs_and_labels(payments: RepoBuilder, store: Store) -> None:
    _index(payments, store)
    hit = search(store, "reject empty tokens", mode=SearchMode.BM25).hits[0]
    assert hit.refs[0].number == 42
    assert Label.FIX in hit.labels


# ----- vectors -------------------------------------------------------------------


def test_embeddings_and_hybrid_search(payments: RepoBuilder, store: Store) -> None:
    embedder = FakeEmbedder()
    stats = _index(payments, store, embedder=embedder)
    assert stats.embedded == 7
    assert stats.embedding_model == "fake-embedder"
    results = search(
        store, "constant time token compare", embedder=embedder, reranker=FakeReranker()
    )
    assert results.reranked
    assert results.hits[0].commit.summary.startswith("fix(auth): compare tokens in constant time")
    assert "rerank" in results.hits[0].retrievers


def test_embedding_is_incremental(payments: RepoBuilder, store: Store) -> None:
    embedder = FakeEmbedder()
    _index(payments, store, embedder=embedder)
    calls = embedder.calls
    _index(payments, store, embedder=embedder)
    assert embedder.calls == calls


def test_model_change_re_embeds(payments: RepoBuilder, store: Store) -> None:
    _index(payments, store, embedder=FakeEmbedder("a", dim=32))
    stats = _index(payments, store, embedder=FakeEmbedder("b", dim=48))
    assert (stats.embedding_model, stats.embedded) == ("b", 7)


def test_vector_mode_without_vectors_raises(payments: RepoBuilder, store: Store) -> None:
    _index(payments, store)
    with pytest.raises(VectorsUnavailableError):
        search(store, "retry", mode=SearchMode.VECTOR, embedder=FakeEmbedder())


def test_hybrid_without_vectors_notes_and_falls_back(payments: RepoBuilder, store: Store) -> None:
    _index(payments, store)
    results = search(store, "retry", embedder=FakeEmbedder())
    assert results.hits
    assert results.notes


def test_deleting_commits_removes_vectors(payments: RepoBuilder, store: Store) -> None:
    _index(payments, store, embedder=FakeEmbedder())
    assert store.delete_hashes([payments.head(), "f" * 40]) == 1
    assert store.stats().embedded == 6
    assert vectors.count_unembedded(store) == 0


def test_rrf_rewards_agreement() -> None:
    fused = fuse({"bm25": [(1, 9.0), (2, 8.0)], "vector": [(2, 0.9), (3, 0.8)]})
    assert [i for i, _, _ in fused] == [2, 1, 3]
    assert fused[0][2] == ["bm25", "vector"]


# ----- summaries -----------------------------------------------------------------


def test_summaries_are_redacted_stored_and_searchable(payments: RepoBuilder, store: Store) -> None:
    secret = "sk-ant-" + "api03-" + "x" * 40
    payments.write("src/config.py", f'ANTHROPIC_KEY = "{secret}"\n').commit("chore: add config")
    provider = FakeProvider(reply="Adds a configuration module holding the zebra credentials.")
    stats = _index(payments, store, summariser=Summariser(provider), embedder=FakeEmbedder())
    assert stats.summarised == 8
    assert provider.prompts
    assert all(secret not in prompt for prompt in provider.prompts)
    assert any("[REDACTED:" in prompt for prompt in provider.prompts)
    assert search(store, "zebra", mode=SearchMode.BM25).hits
    assert stats.embedded == 8  # vectors were rebuilt after summaries were added


def test_summary_limit(payments: RepoBuilder, store: Store) -> None:
    provider = FakeProvider()
    stats = _index(
        payments, store, summariser=Summariser(provider), options=IndexOptions(summary_limit=2)
    )
    assert stats.summarised == 2
    assert len(provider.prompts) == 2


# ----- helpers -------------------------------------------------------------------


class _CountingProgress(NullProgress):
    def __init__(self) -> None:
        self.totals: dict[str, int] = {}

    def stage(self, name: str, total: int) -> None:
        self.totals[name] = total


class _InterruptAfter(NullProgress):
    """Simulates Ctrl-C once ``limit`` commits have been reported done."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.done = 0

    def advance(self, amount: int = 1) -> None:
        self.done += amount
        if self.done >= self.limit:
            raise KeyboardInterrupt
