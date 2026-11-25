"""Explain one commit: what it changed, the reason its message states, and its revert links."""

from __future__ import annotations

from sprout.core.answer.reasons import vet_reason
from sprout.core.git.pygit2_repo import Pygit2Repo
from sprout.core.index.hits import reverted_by
from sprout.core.index.store import Store
from sprout.core.redact import redact
from sprout.errors import RevisionNotFoundError
from sprout.models import CommitExplanation

_TRUNCATED = "\n[diff truncated]\n"
_READ = 100_000  # diff characters read and redacted before cutting to ``max_patch``


def explain_commit(
    repo: Pygit2Repo, store: Store | None, rev: str, *, max_patch: int = 2_500
) -> CommitExplanation:
    """Everything worth knowing about ``rev`` before changing the code it touched.

    Works from git alone; with an index it also lists the commits that revert this one.
    The patch has secrets redacted, because it is handed to an agent's model.

    Raises:
        RevisionNotFoundError: ``rev`` does not name a commit.
    """
    hash_ = repo.resolve(rev)
    record = repo.read_commit(hash_)
    info = record.message_info
    # Redact before cutting, so a secret that straddles the cut is still caught whole.
    patch, redacted = redact(repo.commit_patch(hash_, max_chars=_READ).removesuffix(_TRUNCATED))
    truncated = len(patch) > max_patch
    patch = patch[:max_patch] if truncated else patch
    reason = vet_reason(None, record.commit.message).quote  # the gate WhyBench measured
    reverts = [_full_hash(repo, h) for h in info.reverts]
    if store is not None and info.reverts_summary and not reverts:
        reverts = _by_summary(store, info.reverts_summary, hash_)
    return CommitExplanation(
        commit=record.commit,
        labels=info.labels,
        refs=info.refs,
        reason=reason,
        reverts=reverts,
        reverted_by=reverted_by(store, hash_, record.commit.summary) if store else [],
        files=record.files,
        files_truncated=record.files_truncated,
        patch=patch,
        patch_truncated=truncated,
        redacted=redacted,
        indexed=store is not None,
    )


def _full_hash(repo: Pygit2Repo, short: str) -> str:
    try:
        return repo.resolve(short)
    except RevisionNotFoundError:
        return short  # named in the message but not in this clone


def _by_summary(store: Store, summary: str, exclude: str) -> list[str]:
    """Commits whose subject matches a ``Revert "..."`` quote, newest first."""
    rows = store.db.execute(
        "SELECT hash FROM commits WHERE summary = ? AND hash != ? ORDER BY committed_at DESC",
        (summary, exclude),
    ).fetchall()
    return [str(r[0]) for r in rows]
