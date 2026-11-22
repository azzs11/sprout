"""Short LLM summaries of commits (opt-in), with secrets redacted before any call."""

from __future__ import annotations

import re

from sprout.core.index.store import Store
from sprout.core.redact import redact
from sprout.llm.prompts import load_prompt
from sprout.llm.provider import Provider

MAX_SUMMARY_CHARS = 500
_WHITESPACE = re.compile(r"\s+")


class Summariser:
    """Turns a commit message and diff into a one-paragraph summary."""

    def __init__(self, provider: Provider, *, max_tokens: int = 1024) -> None:
        self.provider = provider
        self.prompt = load_prompt("summarise_commit")
        self._max_tokens = max_tokens

    @property
    def model_id(self) -> str:
        """Provider and prompt version, stored with each summary."""
        return f"{self.provider.name}|{self.prompt.id}"

    def summarise(self, message: str, patch: str) -> str:
        """Summarise one commit. The message and diff are redacted first."""
        clean_message, _ = redact(message)
        clean_patch, _ = redact(patch)
        reply = self.provider.complete(
            system=self.prompt.system,
            prompt=self.prompt.render(message=clean_message.strip(), diff=clean_patch),
            max_tokens=self._max_tokens,
        )
        text = _WHITESPACE.sub(" ", reply).strip()
        return text[:MAX_SUMMARY_CHARS]


def pending(store: Store, limit: int) -> list[tuple[int, str]]:
    """Up to ``limit`` non-merge commits without a summary, newest first, as ``(id, hash)``."""
    rows = store.db.execute(
        "SELECT id, hash FROM commits WHERE llm_summary IS NULL AND additions + deletions > 0"
        " ORDER BY committed_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [(int(r[0]), str(r[1])) for r in rows]


def count_pending(store: Store) -> int:
    """How many commits still need a summary."""
    return store.count(
        "SELECT count(*) FROM commits WHERE llm_summary IS NULL AND additions + deletions > 0"
    )


def save(store: Store, commit_id: int, summary: str, model_id: str) -> None:
    """Store a summary, add it to keyword search, and drop the now-stale vector."""
    db = store.db
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute(
            "UPDATE commits SET llm_summary = ?, llm_model = ? WHERE id = ?",
            (summary, model_id, commit_id),
        )
        db.execute("UPDATE fts SET llm_summary = ? WHERE rowid = ?", (summary, commit_id))
        if db.execute("SELECT 1 FROM sqlite_master WHERE name = 'vec'").fetchone():
            db.execute("DELETE FROM vec WHERE rowid = ?", (commit_id,))
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
