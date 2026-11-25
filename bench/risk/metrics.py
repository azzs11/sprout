"""Precision, recall and alert rate for revert replay, with bootstrap confidence intervals."""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Callable, Sequence

from bench.risk.replay import Case

BUDGETS = (0.05, 0.10, 0.50)
BOOTSTRAP = 1_000
Flag = Callable[[Case], bool]
Score = Callable[[Case], int]
Truth = Callable[[Case], bool]


def reverted(case: Case) -> bool:
    """Headline label: a later commit reverted it."""
    return case.positive


def induced(case: Case) -> bool:
    """Wider label: reverted, or a later fix removed a line it added (SZZ-lite)."""
    return case.induced


def sprout_flag(case: Case) -> bool:
    """What users see by default: any finding at review or above."""
    return case.level != "low"


def sprout_high_flag(case: Case) -> bool:
    """What the agent hook interrupts for: a high finding."""
    return case.level == "high"


def baseline_flag(case: Case) -> bool:
    """A recent fix, security or revert commit touched one of the same files."""
    return case.baseline > 0


def confusion(cases: Sequence[Case], flag: Flag, truth: Truth = reverted) -> dict[str, float]:
    """Alerts, hits, precision, recall and alert rate for one way of flagging commits."""
    alerts = [c for c in cases if flag(c)]
    hits = sum(truth(c) for c in alerts)
    positives = sum(truth(c) for c in cases)
    return {
        "commits": len(cases),
        "positives": positives,
        "alerts": len(alerts),
        "hits": hits,
        "precision": hits / len(alerts) if alerts else 0.0,
        "recall": hits / positives if positives else 0.0,
        "alert_rate": len(alerts) / len(cases) if cases else 0.0,
    }


def with_intervals(
    cases: Sequence[Case], flag: Flag, truth: Truth = reverted, seed: int = 0
) -> dict[str, object]:
    """``confusion`` plus 95% bootstrap intervals for precision and recall (resampling commits)."""
    point = confusion(cases, flag, truth)
    rng = random.Random(seed)  # noqa: S311 - reproducible resampling, not security
    precisions: list[float] = []
    recalls: list[float] = []
    for _ in range(BOOTSTRAP):
        sample = rng.choices(cases, k=len(cases))
        m = confusion(sample, flag, truth)
        precisions.append(m["precision"])
        recalls.append(m["recall"])
    return {**point, "precision_ci": _interval(precisions), "recall_ci": _interval(recalls)}


def at_budget(
    cases: Sequence[Case], score: Score, budget: float, truth: Truth = reverted
) -> dict[str, float]:
    """Flag at most ``budget`` of all commits, highest score first; zero scores are never flagged."""
    limit = math.ceil(budget * len(cases))
    ranked = sorted((c for c in cases if score(c) > 0), key=lambda c: (-score(c), c.hash))
    chosen = {c.hash for c in ranked[:limit]}
    return {"budget": budget, **confusion(cases, lambda c: c.hash in chosen, truth)}


def lead_days(cases: Sequence[Case], flag: Flag) -> float | None:
    """Median days between a correct warning and the revert it anticipated."""
    days = [
        (c.reverted_at - c.committed_at) / 86_400
        for c in cases
        if flag(c) and c.positive and c.reverted_at is not None
    ]
    return round(statistics.median(days), 1) if days else None


def _interval(values: list[float]) -> list[float]:
    ordered = sorted(values)
    low = ordered[int(0.025 * (len(ordered) - 1))]
    high = ordered[int(0.975 * (len(ordered) - 1))]
    return [round(low, 4), round(high, 4)]
