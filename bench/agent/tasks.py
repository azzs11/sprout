"""Pick agent-impact tasks: known reverts an agent could be asked to repeat.

Chosen mechanically from the test and holdout repositories, without looking at whether Sprout
warns, so the tasks do not favour it. A task is a reverted commit R and its revert V where:

- R is not a merge or a revert; its subject is a real description (10+ characters);
- R changes 2 to 40 lines in 1 to 3 source files (a language Sprout parses);
- V undoes exactly R: V's added and removed lines are R's removed and added lines.

At most 2 tasks per repository (newest reverts first), 10 in total.
"""

from __future__ import annotations

from collections import Counter

from sprout.core.code.languages import spec_for_path
from sprout.core.git.pygit2_repo import Pygit2Repo
from sprout.core.index.lines import normalize
from sprout.core.index.store import Store
from sprout.models import ChangedLine

PER_REPO = 2
TOTAL = 10
_TRAILER_PREFIXES = ("signed-off-by:", "co-authored-by:", "reviewed-by:", "change-id:")


def pick(name: str, repo: Pygit2Repo, store: Store) -> list[dict[str, object]]:
    """Up to ``PER_REPO`` tasks from one repository, newest revert first."""
    rows = store.db.execute(
        "SELECT t.hash, c.hash FROM reverts r JOIN commits c ON c.id = r.commit_id"
        " JOIN commits t ON t.hash = r.target ORDER BY c.committed_at DESC"
    ).fetchall()
    tasks: list[dict[str, object]] = []
    for reverted, revert in rows:
        task = _task(name, repo, str(reverted), str(revert))
        if task is not None:
            tasks.append(task)
        if len(tasks) == PER_REPO:
            break
    return tasks


def _task(name: str, repo: Pygit2Repo, reverted: str, revert: str) -> dict[str, object] | None:
    commit = repo.commit(reverted)
    if (
        len(commit.parents) != 1
        or commit.summary.lower().startswith("revert")
        or len(commit.summary) < 10
    ):
        return None
    lines = repo.commit_lines(reverted, limit=200)
    files = {c.path for c in lines}
    if not 2 <= len(lines) <= 40 or not 1 <= len(files) <= 3:
        return None
    if any(spec_for_path(path) is None for path in files):
        return None
    if _signature(repo.commit_lines(revert, limit=200), flip=True) != _signature(lines, flip=False):
        return None
    added = sorted({n for c in lines if c.added and (n := normalize(c.text)) is not None})
    if not added:
        return None
    return {
        "repo": name,
        "reverted": reverted,
        "revert": revert,
        "prompt": prompt(commit.message),
        "added": added,
        "files": sorted(files),
    }


def prompt(message: str) -> str:
    """Ask for the reverted change in its author's own words, without mentioning history."""
    subject, _, body = message.strip().partition("\n")
    kept = [ln for ln in body.strip().splitlines() if not ln.lower().startswith(_TRAILER_PREFIXES)]
    text = "\n".join(kept).strip()
    detail = f"\n\nDetails from the request:\n{text[:800]}" if text else ""
    return (
        f"Please make this change in this repository: {subject.strip()}{detail}\n\n"
        "Edit the files directly. Do not commit. When you are done, say in a few lines what you"
        " changed, or why you did not change it."
    )


def _signature(lines: list[ChangedLine], *, flip: bool) -> Counter[tuple[bool, str, str]]:
    return Counter((c.added != flip, c.path, c.text.strip()) for c in lines)
