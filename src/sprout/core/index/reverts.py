"""Reverts found in the index, linked to the commits they undid."""

from __future__ import annotations

from sprout.core.index.store import Store
from sprout.models import Commit, RevertLink

_REVERTS = """
SELECT id, commit_json, reverts_summary FROM commits c
WHERE reverts_summary IS NOT NULL OR EXISTS (SELECT 1 FROM reverts r WHERE r.commit_id = c.id)
ORDER BY committed_at DESC
"""


def recent_reverts(store: Store, limit: int = 3) -> list[RevertLink]:
    """The newest reverts whose reverted commit is also in the index."""
    links: list[RevertLink] = []
    for commit_id, commit_json, quoted in store.db.execute(_REVERTS):
        target = _target(store, int(commit_id), quoted)
        if target is not None:
            revert = Commit.model_validate_json(commit_json)
            links.append(
                RevertLink(revert=revert, reverted_hash=target[0], reverted_summary=target[1])
            )
            if len(links) == limit:
                break
    return links


def _target(store: Store, commit_id: int, quoted: str | None) -> tuple[str, str] | None:
    """The reverted commit, by the hash in the message, else by the quoted subject."""
    for (prefix,) in store.db.execute(
        "SELECT target FROM reverts WHERE commit_id = ?", (commit_id,)
    ):
        row = store.db.execute(
            "SELECT hash, summary FROM commits WHERE hash >= ? AND hash < ? || 'g' LIMIT 1",
            (prefix, prefix),
        ).fetchone()
        if row is not None:
            return str(row[0]), str(row[1])
    if quoted:
        row = store.db.execute(
            "SELECT hash, summary FROM commits WHERE summary = ? AND id != ?"
            " ORDER BY committed_at DESC LIMIT 1",
            (quoted, commit_id),
        ).fetchone()
        if row is not None:
            return str(row[0]), str(row[1])
    return None
