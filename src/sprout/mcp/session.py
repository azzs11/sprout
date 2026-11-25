"""Long-lived state for one repository's MCP server: the open index and loaded models.

Tools run in worker threads, so every call takes ``lock``. Keeping one ``Store`` open keeps
its vector matrix cached between calls; the cache is dropped when another process (such as
``sprout index``) updates the index.
"""

from __future__ import annotations

import threading
from pathlib import Path

from sprout import services
from sprout.config import Settings, load_settings
from sprout.core.answer.commit import explain_commit
from sprout.core.answer.target import why_target
from sprout.core.answer.why import Models, WhyOptions
from sprout.core.git import open_repo
from sprout.core.index.store import Store
from sprout.core.retrieve.hybrid import search
from sprout.errors import IndexNotFoundError
from sprout.models import CommitExplanation, SearchResults, WhyAnswer


class Session:
    """One repository, its index and its models, shared by every tool call."""

    def __init__(self, path: Path, settings: Settings | None = None) -> None:
        self.repo = open_repo(path)
        self.settings = settings or load_settings(self.repo.root)
        self.lock = threading.Lock()
        self._store: Store | None = None
        self._version: tuple[str | None, int] | None = None
        self._embedder = services.build_embedder(self.settings)  # loads on first use
        self._reranker = services.build_reranker(self.settings)

    def why(self, target: str, *, at: str | None, facts_only: bool, limit: int) -> WhyAnswer:
        """Answer ``why`` for a ``path:line`` or a question."""
        with self.lock:
            store = self._open_store()
            answerer, note = (None, None) if facts_only else services.build_answerer(self.settings)
            models = Models(answerer=answerer, embedder=self._embedder, reranker=self._reranker)
            answer = why_target(
                self.repo,
                store,
                target,
                cwd=self.repo.root,
                rev=at,
                models=models,
                options=WhyOptions(limit=limit),
            )
        if note:
            answer = answer.model_copy(update={"notes": [*answer.notes, note]})
        return answer

    def search(self, query: str, *, limit: int) -> SearchResults:
        """Search the history index.

        Raises:
            IndexNotFoundError: the repository has not been indexed yet.
        """
        with self.lock:
            store = self._open_store()
            if store is None:
                raise IndexNotFoundError(str(self.repo.root))
            return search(
                store, query, limit=limit, embedder=self._embedder, reranker=self._reranker
            )

    def explain(self, rev: str) -> CommitExplanation:
        """Explain one commit; revert links need the index."""
        with self.lock:
            return explain_commit(self.repo, self._open_store(), rev)

    def close(self) -> None:
        """Close the index."""
        with self.lock:
            if self._store is not None:
                self._store.close()
                self._store = None

    def _open_store(self) -> Store | None:
        """The index, opened on first use and refreshed if it changed. Call under ``lock``."""
        if self._store is None:
            try:
                self._store = Store.open(self.repo.root, create=False, any_thread=True)
            except IndexNotFoundError:
                return None
        version = (
            self._store.get_meta("updated_at"),
            self._store.count("SELECT count(*) FROM vectors"),
        )
        if version != self._version:
            self._store.cache.clear()
            self._version = version
        return self._store
