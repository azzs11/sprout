"""Revert replay: would Sprout have warned about a commit before it was reverted?

Every non-merge commit is checked, in date order, against fingerprints of commits made *before*
it (``check_changes(before=...)``), so nothing from the future leaks in. Two labels:

- **reverted** (the headline): a later commit reverts it, by hash or by quoting its subject.
- **fix-inducing** (SZZ-lite): within a year, a later fix or security commit removes a line it
  added (same file, whitespace-normalised). This catches mistakes that were fixed, not reverted.

The baseline flags a commit that touches a file a fix, security or revert commit touched in the
30 days before it.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from sprout.core.git.pygit2_repo import Pygit2Repo
from sprout.core.index.lines import line_hash, normalize
from sprout.core.index.store import Store
from sprout.core.risk.check import check_changes
from sprout.models import ChangedLine, RiskLevel

BASELINE_DAYS = 30
MAX_LINES = 20_000
SZZ_DAYS = 365
SZZ_MAX_LINES = 2_000  # like the index: huge fix commits (reformats) blame nobody
_LEVEL_SCORE = {RiskLevel.LOW: 0, RiskLevel.REVIEW: 1, RiskLevel.HIGH: 2}


@dataclass(frozen=True)
class Case:
    """One replayed commit."""

    repo: str
    hash: str
    committed_at: int
    reverted_by: str | None
    reverted_at: int | None
    level: str
    score: int  # level * 1000 + matched lines: ranks alerts for the budget metrics
    kinds: list[str]
    cited: list[str]
    baseline: int  # recent fix/security/revert commits touching the same files
    findings: list[list[object]] = field(default_factory=list[list[object]])  # kind, level, n, of
    fixed_by: str | None = None
    fixed_at: int | None = None

    @property
    def positive(self) -> bool:
        """True when a later commit reverted this one."""
        return self.reverted_by is not None

    @property
    def induced(self) -> bool:
        """True when it was reverted, or a later fix removed a line it added (SZZ-lite)."""
        return self.positive or self.fixed_by is not None


def reverted_targets(store: Store) -> dict[str, tuple[str, int]]:
    """Reverted commit hash → (first revert's hash, its time)."""
    out: dict[str, tuple[str, int]] = {}
    by_hash = store.db.execute(
        "SELECT t.hash, c.hash, c.committed_at FROM reverts r"
        " JOIN commits c ON c.id = r.commit_id"
        " JOIN commits t ON t.hash >= r.target AND t.hash < r.target || 'g'"
        " ORDER BY c.committed_at"
    )
    by_subject = store.db.execute(
        "SELECT t.hash, c.hash, c.committed_at FROM commits c"
        " JOIN commits t ON t.summary = c.reverts_summary AND t.committed_at <= c.committed_at"
        " AND t.id != c.id WHERE c.reverts_summary IS NOT NULL ORDER BY c.committed_at"
    )
    for target, revert, at in [*by_hash, *by_subject]:
        if str(target) != str(revert):
            out.setdefault(str(target), (str(revert), int(at)))
    return out


def replay(name: str, repo: Pygit2Repo, store: Store) -> list[Case]:
    """Check every non-merge commit against the history before it, then attach labels."""
    targets = reverted_targets(store)
    rows = store.db.execute(
        "SELECT id, hash, committed_at, labels FROM commits"
        " WHERE labels NOT LIKE '%\"merge\"%' ORDER BY committed_at, hash"
    ).fetchall()
    cases: list[Case] = []
    szz = _Szz()
    for commit_id, hash_, at, labels in rows:
        changed = repo.commit_lines(str(hash_), limit=MAX_LINES)
        card = check_changes(store, changed, before=int(at))
        revert = targets.get(str(hash_))
        szz.step(str(hash_), int(at), changed, is_fix='"fix"' in labels or '"security"' in labels)
        cases.append(
            Case(
                repo=name,
                hash=str(hash_),
                committed_at=int(at),
                reverted_by=revert[0] if revert else None,
                reverted_at=revert[1] if revert else None,
                level=card.level.value,
                score=_LEVEL_SCORE[card.level] * 1000 + sum(f.matched for f in card.findings),
                kinds=sorted({f.kind.value for f in card.findings}),
                cited=[f.commit.hash for f in card.findings],
                baseline=_baseline(store, int(commit_id), int(at)),
                findings=[[f.kind.value, f.level.value, f.matched, f.total] for f in card.findings],
            )
        )
    return [
        replace(c, fixed_by=f[0], fixed_at=f[1]) if (f := szz.fixed.get(c.hash)) else c
        for c in cases
    ]


class _Szz:
    """SZZ-lite in one chronological pass: who last added each line, and which fix removed it."""

    def __init__(self) -> None:
        self.added: dict[tuple[str, int], tuple[str, int]] = {}  # (path, hash) → (commit, time)
        self.fixed: dict[str, tuple[str, int]] = {}  # inducing commit → (first fix, its time)

    def step(self, hash_: str, at: int, changed: Sequence[ChangedLine], *, is_fix: bool) -> None:
        if is_fix and len(changed) < SZZ_MAX_LINES:
            for c in changed:
                if not c.added and (norm := normalize(c.text)) is not None:
                    source = self.added.get((c.path, line_hash(norm)))
                    if source and source[0] != hash_ and at - source[1] <= SZZ_DAYS * 86_400:
                        self.fixed.setdefault(source[0], (hash_, at))
        for c in changed:
            if c.added and (norm := normalize(c.text)) is not None:
                self.added[(c.path, line_hash(norm))] = (hash_, at)


def _baseline(store: Store, commit_id: int, at: int) -> int:
    """Fix, security or revert commits in the last 30 days that touched this commit's files."""
    row = store.db.execute(
        "SELECT count(DISTINCT f.commit_id) FROM files f JOIN commits c ON c.id = f.commit_id"
        " WHERE f.path IN (SELECT path FROM files WHERE commit_id = ?)"
        " AND c.committed_at >= ? AND c.committed_at < ?"
        " AND (c.labels LIKE '%\"fix\"%' OR c.labels LIKE '%\"security\"%'"
        " OR c.labels LIKE '%\"revert\"%')",
        (commit_id, at - BASELINE_DAYS * 86_400, at),
    ).fetchone()
    return int(row[0])


def to_json(case: Case) -> dict[str, object]:
    """A case as a JSON-ready dict."""
    return {**case.__dict__, "positive": case.positive}


def from_json(row: dict[str, object]) -> Case:
    """Inverse of ``to_json``."""
    fields = {k: v for k, v in row.items() if k != "positive"}
    return Case(**json.loads(json.dumps(fields)))  # type: ignore[arg-type]
