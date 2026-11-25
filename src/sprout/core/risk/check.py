"""Regression Memory: does history warn against this change?

Every fix, security or revert commit marks the lines it removed as *bad* (the bug, or the change
being reverted) and the lines it added as *guards* (the fix, or the restored code). A change
that re-adds a bad line or removes a guard runs into that commit. When several commits touched
the same line, the newest decides, so a change that was reverted and later re-landed stops
warning. Removing a fix's lines counts only when the change undoes most of that fix (risk@2,
chosen on the tune split of the revert replay: editing near a fix is ordinary code churn).
Deterministic and model-free: this is the path git and agent hooks call.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import cast

from sprout.core.answer.reasons import vet_reason
from sprout.core.index.lines import line_hash, normalize
from sprout.core.index.store import Store
from sprout.models import (
    ChangedLine,
    Commit,
    Label,
    RiskCard,
    RiskFinding,
    RiskKind,
    RiskLevel,
    Verdict,
)

METHOD = "risk@2"  # bump when the rules below change; recorded in every card and eval result
DF_MAX = 8  # a line found in more signal commits than this is too common to mean anything
DISTINCTIVE = 24  # normalised length from which a line may match in another file (renames)
MIN_SHARE = 0.5  # or match at least this share of the commit's lines on that side
MAX_FINDINGS = 10
_CHUNK = 500
_LEVELS = [RiskLevel.LOW, RiskLevel.REVIEW, RiskLevel.HIGH]
_VERDICTS = {
    RiskLevel.LOW: Verdict.PROCEED,
    RiskLevel.REVIEW: Verdict.REVIEW,
    RiskLevel.HIGH: Verdict.STOP,
}


@dataclass(frozen=True)
class _Row:
    commit_id: int
    guard: bool  # the commit added this line
    path: str
    committed_at: int


@dataclass
class _Hit:
    hashes: set[int] = field(default_factory=set[int])
    examples: list[str] = field(default_factory=list[str])
    paths: set[str] = field(default_factory=set[str])
    distinctive: bool = False


def check_changes(
    store: Store, changed: Sequence[ChangedLine], *, before: int | None = None
) -> RiskCard:
    """Compare a change's added and removed lines with the history index.

    With ``before`` (a Unix time), only commits made before it count: used to replay history
    without letting later commits leak into the answer.
    """
    added, removed = _side(changed, added=True), _side(changed, added=False)
    for moved in added.keys() & removed.keys():  # moved or re-indented within this change
        del added[moved], removed[moved]
    rows = _lookup(store, added.keys() | removed.keys(), before)
    hits: dict[tuple[int, bool], _Hit] = {}
    for wanted_guard, side in ((False, added), (True, removed)):
        for h, (norm, lines) in side.items():
            owner = _owner(rows.get(h, []), {c.path for c in lines}, norm)
            if owner is not None and owner.guard is wanted_guard:
                hit = hits.setdefault((owner.commit_id, wanted_guard), _Hit())
                hit.hashes.add(h)
                hit.paths.update(c.path for c in lines)
                hit.distinctive |= len(norm) >= DISTINCTIVE
                if len(hit.examples) < 3:
                    hit.examples.append(("-" if wanted_guard else "+") + lines[0].text.strip())
    found: list[RiskFinding] = []
    for (commit_id, guard), hit in hits.items():
        finding = _finding(store, commit_id, guard, hit)
        if finding is not None:
            found.append(finding)
    findings = sorted(_per_commit(found), key=_rank)[:MAX_FINDINGS]
    level = max((f.level for f in findings), key=_LEVELS.index, default=RiskLevel.LOW)
    notes = [] if store.count("SELECT count(*) FROM line_commits") else [_NO_LINES]
    return RiskCard(
        level=level,
        verdict=_VERDICTS[level],
        findings=findings,
        checked_lines=len(added) + len(removed),
        method=METHOD,
        notes=notes,
    )


def _per_commit(found: list[RiskFinding]) -> list[RiskFinding]:
    """One finding per commit: the stronger side leads, the other side's lines are added."""
    merged: dict[str, RiskFinding] = {}
    for f in sorted(found, key=_rank):
        first = merged.get(f.commit.hash)
        if first is None:
            merged[f.commit.hash] = f
            continue
        merged[f.commit.hash] = first.model_copy(
            update={
                "matched": first.matched + f.matched,
                "total": first.total + f.total,
                "examples": (first.examples + f.examples)[:3],
                "paths": sorted({*first.paths, *f.paths}),
            }
        )
    return list(merged.values())


def _rank(f: RiskFinding) -> tuple[int, int, float]:
    return (-_LEVELS.index(f.level), -f.matched, -f.commit.committed_at.timestamp())


_NO_LINES = "The index has no fix, security or revert lines yet: run sprout index."


def _side(
    changed: Sequence[ChangedLine], *, added: bool
) -> dict[int, tuple[str, list[ChangedLine]]]:
    out: dict[int, tuple[str, list[ChangedLine]]] = {}
    for c in changed:
        if c.added is added and (norm := normalize(c.text)) is not None:
            out.setdefault(line_hash(norm), (norm, []))[1].append(c)
    return out


def _lookup(store: Store, hashes: Iterable[int], before: int | None) -> dict[int, list[_Row]]:
    wanted = list(hashes)
    out: dict[int, list[_Row]] = {}
    for start in range(0, len(wanted), _CHUNK):
        chunk = wanted[start : start + _CHUNK]
        marks = ",".join("?" * len(chunk))
        query = (
            "SELECT l.hash, l.commit_id, l.added, l.path, c.committed_at"  # noqa: S608 - only "?"
            f" FROM lines l JOIN commits c ON c.id = l.commit_id WHERE l.hash IN ({marks})"
            " AND c.committed_at < ?"
        )
        cutoff = before if before is not None else 2**62
        for h, commit_id, guard, path, at in store.db.execute(query, [*chunk, cutoff]):
            out.setdefault(int(h), []).append(_Row(int(commit_id), bool(guard), str(path), int(at)))
    return out


def _owner(rows: list[_Row], paths: set[str], norm: str) -> _Row | None:
    """The newest commit that decides what this line means here, or None."""
    if len({r.commit_id for r in rows}) > DF_MAX:
        return None
    same_file = [r for r in rows if r.path in paths]
    candidates = same_file or (rows if len(norm) >= DISTINCTIVE else [])
    return max(candidates, key=lambda r: (r.committed_at, r.guard), default=None)


def _finding(store: Store, commit_id: int, guard: bool, hit: _Hit) -> RiskFinding | None:
    total = int(
        store.db.execute(
            "SELECT count(DISTINCT hash) FROM lines WHERE commit_id = ? AND added = ?",
            (commit_id, int(guard)),
        ).fetchone()[0]
    )
    matched = len(hit.hashes)
    if not (matched >= 2 or matched >= MIN_SHARE * max(total, 1) or hit.distinctive):
        return None
    row = store.db.execute(
        "SELECT commit_json, labels FROM commits WHERE id = ?", (commit_id,)
    ).fetchone()
    commit = Commit.model_validate_json(row[0])
    labels = [Label(v) for v in _json_list(row[1])]
    revert = Label.REVERT in labels
    if guard:
        kind = RiskKind.REMOVES_RESTORED if revert else RiskKind.REMOVES_FIX
    else:
        kind = RiskKind.REAPPLIES_REVERTED if revert else RiskKind.REINTRODUCES_FIXED
    if kind is RiskKind.REMOVES_FIX and not _undoes(matched, total):
        return None  # an edit near a fix, not an undo of it (risk@2)
    high = Label.SECURITY in labels or (
        kind is RiskKind.REAPPLIES_REVERTED and matched >= MIN_SHARE * max(total, 1)
    )
    targets = store.db.execute("SELECT target FROM reverts WHERE commit_id = ?", (commit_id,))
    return RiskFinding(
        commit=commit,
        kind=kind,
        level=RiskLevel.HIGH if high else RiskLevel.REVIEW,
        labels=[label for label in labels if label is not Label.MERGE],
        matched=matched,
        total=total,
        examples=hit.examples,
        paths=sorted(hit.paths),
        reverts=[str(t[0]) for t in targets] if revert else [],
        reason=vet_reason(None, commit.message).quote,
    )


def _undoes(matched: int, total: int) -> bool:
    """Most of a fix's added lines are removed: half or more, and 2+ unless it added just one."""
    return matched >= MIN_SHARE * max(total, 1) and (matched >= 2 or total == 1)


def _json_list(raw: str) -> list[str]:
    value: object = json.loads(raw)
    return [str(v) for v in cast("list[object]", value)] if isinstance(value, list) else []
