"""Ranking metrics for one gold set against one ranked list."""

from __future__ import annotations

import math
from collections.abc import Sequence


def recall_at(ranked: Sequence[str], gold: set[str], k: int) -> float:
    """1.0 if any gold commit is in the top ``k``."""
    return 1.0 if gold.intersection(ranked[:k]) else 0.0


def reciprocal_rank(ranked: Sequence[str], gold: set[str], k: int = 10) -> float:
    """1/rank of the first gold commit within the top ``k`` (0 if absent)."""
    for rank, item in enumerate(ranked[:k], start=1):
        if item in gold:
            return 1.0 / rank
    return 0.0


def ndcg_at(ranked: Sequence[str], gold: set[str], k: int = 10) -> float:
    """Binary-relevance nDCG@k."""
    dcg = sum(1.0 / math.log2(rank + 1) for rank, item in enumerate(ranked[:k], 1) if item in gold)
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(len(gold), k) + 1))
    return dcg / ideal if ideal else 0.0


def summarise(scores: list[dict[str, float]]) -> dict[str, float]:
    """Mean of each metric, plus the number of tasks."""
    if not scores:
        return {"n": 0}
    keys = scores[0].keys()
    out = {key: round(sum(s[key] for s in scores) / len(scores), 4) for key in keys}
    out["n"] = len(scores)
    return out


def score(ranked: Sequence[str], gold: set[str]) -> dict[str, float]:
    """All metrics for one task."""
    return {
        "recall@1": recall_at(ranked, gold, 1),
        "recall@5": recall_at(ranked, gold, 5),
        "recall@10": recall_at(ranked, gold, 10),
        "mrr@10": reciprocal_rank(ranked, gold),
        "ndcg@10": ndcg_at(ranked, gold),
    }
