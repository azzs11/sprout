"""Collect and rank the commits that can explain a line or answer a question."""

from __future__ import annotations

import re
from collections.abc import Iterable

from sprout.core.answer.rationale import score_message
from sprout.core.code.symbols import definitions
from sprout.core.git.message import parse_message
from sprout.core.git.pygit2_repo import Pygit2Repo
from sprout.core.index.embedder import Embedder
from sprout.core.index.hits import reverted_by
from sprout.core.index.store import Store
from sprout.core.retrieve.hybrid import search
from sprout.core.retrieve.rerank import Reranker
from sprout.models import Commit, Evidence, EvidenceRole, LineHop, SearchMode

_ROLE_BONUS = {
    EvidenceRole.LINE_ORIGIN: 0.5,
    EvidenceRole.LINE_HISTORY: 0.25,
    EvidenceRole.REVERT: 1.0,
    EvidenceRole.SYMBOL_HISTORY: 0.0,
    EvidenceRole.RELATED: -0.25,
}
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
SYMBOL_LIMIT = 4
RELATED_LIMIT = 5


def enclosing_symbol(repo: Pygit2Repo, rev: str, path: str, line: int) -> str | None:
    """Innermost function or class containing ``line`` at ``rev``."""
    source = repo.read_file(rev, path)
    if not source:
        return None
    inside = [d for d in definitions(path, source) if d.start <= line - 1 <= d.end]
    return max(inside, key=lambda d: d.depth).name if inside else None


class EvidenceSet:
    """Evidence keyed by hash; the first role a commit is added with wins."""

    def __init__(self, repo: Pygit2Repo, store: Store | None, as_of: str) -> None:
        self._repo = repo
        self._store = store
        self._as_of = as_of
        self._items: dict[str, Evidence] = {}
        self._rank: dict[str, float] = {}

    def add(
        self, commit: Commit, role: EvidenceRole, *extra: str, rank: float | None = None
    ) -> None:
        """Add a commit unless it is already present or newer than ``as_of``.

        ``rank`` is the commit's search rank (1 is best), used by ``ranked(by_relevance=True)``.
        """
        if commit.hash in self._items or not self._repo.is_ancestor(commit.hash, self._as_of):
            return
        if rank is not None:
            self._rank[commit.hash] = rank
        info = parse_message(commit.message, is_merge=len(commit.parents) > 1)
        rationale = score_message(commit.message, labels=info.labels, refs=len(info.refs))
        self._items[commit.hash] = Evidence(
            commit=commit,
            role=role,
            score=round(rationale.score + _ROLE_BONUS[role], 3),
            reasons=[*extra, *rationale.reasons],
            labels=info.labels,
            refs=info.refs,
            reverted_by=self._reverted_by(commit),
            files=self._files(commit.hash),
        )

    def hashes(self) -> list[str]:
        """Hashes added so far, in insertion order."""
        return list(self._items)

    def first(self, role: EvidenceRole) -> Evidence | None:
        """The first evidence added with ``role``."""
        return next((e for e in self._items.values() if e.role is role), None)

    def rank_of(self, hash_: str) -> float | None:
        """Search rank a commit was added with, if any."""
        return self._rank.get(hash_)

    def ranked(self, limit: int, *, by_relevance: bool = False) -> list[Evidence]:
        """Best evidence first.

        By default the rationale score decides. With ``by_relevance``, search rank leads and
        the rationale score only breaks ties; commits without a rank come last.
        """
        if by_relevance:
            last = float("inf")
            order = sorted(
                self._items.values(),
                key=lambda e: (self._rank.get(e.commit.hash, last), -e.score),
            )
        else:
            order = sorted(self._items.values(), key=lambda e: -e.score)
        return order[:limit]

    def _reverted_by(self, commit: Commit) -> list[str]:
        if self._store is None:
            return []
        hashes = reverted_by(self._store, commit.hash, commit.summary)
        return [h for h in hashes if self._repo.is_ancestor(h, self._as_of)]

    def _files(self, hash_: str) -> list[str]:
        if self._store is None:
            return []
        rows = self._store.db.execute(
            "SELECT f.path FROM files f JOIN commits c ON c.id = f.commit_id WHERE c.hash = ?"
            " LIMIT 12",
            (hash_,),
        ).fetchall()
        return [str(r[0]) for r in rows]


def add_line_history(evidence: EvidenceSet, hops: list[LineHop]) -> None:
    """The commits blame walked through, newest first."""
    for index, hop in enumerate(hops):
        role = EvidenceRole.LINE_ORIGIN if index == 0 else EvidenceRole.LINE_HISTORY
        note = "created this line" if hop.introduced else "last changed this line"
        if index:
            note = "wrote an earlier version of this line" if not hop.introduced else note
        evidence.add(hop.commit, role, note)


def add_line_log(evidence: EvidenceSet, repo: Pygit2Repo, hashes: Iterable[str]) -> None:
    """Commits from ``git log -L`` that the blame walk did not reach."""
    for hash_ in hashes:
        if repo.has_commit(hash_):
            evidence.add(repo.commit(hash_), EvidenceRole.LINE_HISTORY, "changed this line earlier")


def add_symbol_history(
    evidence: EvidenceSet,
    store: Store,
    symbol: str,
    paths: Iterable[str],
    limit: int = SYMBOL_LIMIT,
) -> None:
    """Other commits that changed the same function or class."""
    names = list(dict.fromkeys(paths))
    marks = ",".join("?" * len(names))
    rows = store.db.execute(
        "SELECT DISTINCT c.commit_json FROM symbols s JOIN commits c ON c.id = s.commit_id"  # noqa: S608
        f" WHERE s.name = ? AND s.path IN ({marks}) ORDER BY c.committed_at DESC LIMIT ?",
        (symbol, *names, limit),
    ).fetchall()
    for row in rows:
        evidence.add(
            Commit.model_validate_json(row[0]), EvidenceRole.SYMBOL_HISTORY, f"changed {symbol}"
        )


def add_reverts(evidence: EvidenceSet, store: Store, repo: Pygit2Repo) -> None:
    """Reverts of the evidence so far, and the commits those reverts undid.

    Each one inherits the search rank of the commit it is linked to, placed just after it.
    """
    for hash_ in evidence.hashes():
        rank = evidence.rank_of(hash_)
        near = None if rank is None else rank + 0.5
        for revert in reverted_by(store, hash_, repo.commit(hash_).summary):
            evidence.add(
                repo.commit(revert), EvidenceRole.REVERT, f"reverted {hash_[:7]}", rank=near
            )
        rows = store.db.execute(
            "SELECT r.target FROM reverts r JOIN commits c ON c.id = r.commit_id WHERE c.hash = ?",
            (hash_,),
        ).fetchall()
        for (target,) in rows:
            if repo.has_commit(str(target)):
                evidence.add(
                    repo.commit(str(target)),
                    EvidenceRole.REVERT,
                    f"was reverted by {hash_[:7]}",
                    rank=near,
                )


def add_related(
    evidence: EvidenceSet,
    store: Store,
    query: str,
    *,
    limit: int = RELATED_LIMIT,
    embedder: Embedder | None = None,
    reranker: Reranker | None = None,
) -> list[str]:
    """Commits found by searching the index, with their search rank; returns search notes."""
    mode = SearchMode.HYBRID if embedder is not None else SearchMode.BM25
    results = search(store, query, mode=mode, limit=limit * 3, embedder=embedder, reranker=reranker)
    added = 0
    for hit in results.hits:
        before = len(evidence.hashes())
        evidence.add(
            hit.commit, EvidenceRole.RELATED, f"matched the search (rank {hit.rank})", rank=hit.rank
        )
        added += len(evidence.hashes()) - before
        if added >= limit:
            break
    return results.notes


def line_query(symbol: str | None, text: str, path: str) -> str:
    """Search query for a line: its enclosing symbol, identifiers and file name."""
    words = [symbol or "", *_IDENT.findall(text), path.rsplit("/", 1)[-1]]
    return " ".join(dict.fromkeys(w for w in words if w))
