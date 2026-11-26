"""Pick the commits whose messages are replayed. The rule is fixed before any results are seen.

Per repository: people's single-parent commits (no merges, reverts or bots) made on or after
``SINCE`` at the pinned snapshot, shuffled with a seed from the repository name, keeping the
first ``PER_REPO`` that change 1 to ``MAX_FILES`` files with some text. ``SINCE`` is after
qwen2.5-coder's release (September 2024), so the model is less likely to have seen the messages.
"""

from __future__ import annotations

import random
import zlib
from datetime import UTC, datetime

from sprout.core.commit.style import is_authored
from sprout.core.git.pygit2_repo import Pygit2Repo

PER_REPO = 20
MAX_FILES = 30
SINCE = datetime(2024, 10, 1, tzinfo=UTC)
WALK = 5_000  # newest commits read per repository


def pick(name: str, split: str, repo: Pygit2Repo, snapshot: str) -> list[dict[str, object]]:
    """Up to ``PER_REPO`` tasks for one repository."""
    pool = [
        c
        for c in repo.history(limit=WALK, rev=snapshot).commits
        if is_authored(c) and len(c.parents) == 1 and c.committed_at >= SINCE
    ]
    pool.sort(key=lambda c: c.hash)  # shuffle from a fixed order, not walk order
    random.Random(zlib.crc32(name.encode())).shuffle(pool)  # noqa: S311 - seeded sample
    tasks: list[dict[str, object]] = []
    for commit in pool:
        files = repo.commit_diff(commit.hash).files
        if not 1 <= len(files) <= MAX_FILES or all(f.binary for f in files):
            continue
        tasks.append(
            {
                "repo": name,
                "split": split,
                "hash": commit.hash,
                "date": commit.committed_at.isoformat(),
                "files": len(files),
                "message": commit.message,
            }
        )
        if len(tasks) == PER_REPO:
            break
    return tasks
