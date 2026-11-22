"""Build and update the history index. Resumable: every batch is its own transaction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sprout.core.git.pygit2_repo import Pygit2Repo
from sprout.core.index import summarise, vectors
from sprout.core.index.embedder import Embedder
from sprout.core.index.store import Store
from sprout.core.index.summarise import Summariser
from sprout.errors import ModelError, NoCommitsError, VectorsUnavailableError
from sprout.models import IndexStats


class Progress(Protocol):
    """Receives progress events. The CLI draws bars; core never prints."""

    def stage(self, name: str, total: int) -> None:
        """A new stage starts with ``total`` units of work."""
        ...

    def advance(self, amount: int = 1) -> None:
        """``amount`` units of the current stage finished."""
        ...

    def note(self, message: str) -> None:
        """A one-line notice, such as a skipped stage."""
        ...


class NullProgress:
    """Ignores every event."""

    def stage(self, name: str, total: int) -> None:
        """Ignore."""

    def advance(self, amount: int = 1) -> None:
        """Ignore."""

    def note(self, message: str) -> None:
        """Ignore."""


@dataclass(frozen=True)
class IndexOptions:
    """What ``build_index`` should do."""

    rev: str | None = None
    since: datetime | None = None
    batch_size: int = 200
    embed_batch_size: int = 64
    summary_limit: int | None = None


def build_index(
    repo: Pygit2Repo,
    store: Store,
    *,
    embedder: Embedder | None = None,
    summariser: Summariser | None = None,
    progress: Progress | None = None,
    options: IndexOptions | None = None,
) -> IndexStats:
    """Index new commits, then add summaries and embeddings that are missing.

    Safe to interrupt at any point: finished batches stay in the index and the next
    run continues from there.
    """
    progress = progress or NullProgress()
    options = options or IndexOptions()
    if repo.head_hash is None and options.rev is None:
        raise NoCommitsError
    _prune(repo, store, progress)
    _index_commits(repo, store, progress, options)
    if summariser is not None:
        _summarise(repo, store, summariser, progress, options)
    if embedder is not None:
        _embed(store, embedder, progress, options)
    store.mark_updated(repo.head_hash)
    return store.stats()


def _prune(repo: Pygit2Repo, store: Store, progress: Progress) -> None:
    """Drop commits whose objects are gone (history rewritten and garbage-collected)."""
    missing = [h for h in store.known_hashes() if not repo.has_commit(h)]
    if missing:
        removed = store.delete_hashes(missing)
        progress.note(f"Removed {removed} commits that no longer exist in the repository.")


def _index_commits(
    repo: Pygit2Repo, store: Store, progress: Progress, options: IndexOptions
) -> None:
    since = int(options.since.timestamp()) if options.since else None
    known = store.known_hashes()
    todo = [h for h in repo.walk_hashes(rev=options.rev, since=since) if h not in known]
    progress.stage("commits", len(todo))
    for start in range(0, len(todo), options.batch_size):
        batch = todo[start : start + options.batch_size]
        store.add_records([repo.read_commit(h) for h in batch])
        progress.advance(len(batch))


def _summarise(
    repo: Pygit2Repo,
    store: Store,
    summariser: Summariser,
    progress: Progress,
    options: IndexOptions,
) -> None:
    total = summarise.count_pending(store)
    if options.summary_limit is not None:
        total = min(total, options.summary_limit)
    progress.stage("summaries", total)
    done = 0
    while done < total:
        batch = summarise.pending(store, min(20, total - done))
        if not batch:
            break
        for commit_id, hash_ in batch:
            record = repo.read_commit(hash_)
            patch = repo.commit_patch(hash_)
            text = summariser.summarise(record.commit.message, patch)
            summarise.save(store, commit_id, text, summariser.model_id)
            progress.advance()
            done += 1


def _embed(store: Store, embedder: Embedder, progress: Progress, options: IndexOptions) -> None:
    if not store.vectors_available:
        progress.note(
            str(VectorsUnavailableError("this Python cannot load SQLite extensions.").message)
        )
        return
    vectors.ensure_table(store, embedder.name, embedder.dim)
    progress.stage("embeddings", vectors.count_unembedded(store))
    while batch := vectors.unembedded(store, options.embed_batch_size):
        texts = [text for _, text in batch]
        embedded = embedder.embed_documents(texts)
        if len(embedded) != len(batch):
            raise ModelError(
                f"The embedding model returned {len(embedded)} vectors for {len(batch)} texts."
            )
        vectors.add(
            store, [(commit_id, vec) for (commit_id, _), vec in zip(batch, embedded, strict=True)]
        )
        progress.advance(len(batch))
