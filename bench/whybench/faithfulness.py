"""Faithfulness of kept answer sentences: is each one actually supported by the commit it cites?

The citation checker only proves that a sentence's quotes and most of its words appear in the
cited commit. Here a judge reads each sampled sentence next to the full commit message and
labels it. Judgements live in ``data/whybench-v0/faithfulness-<split>.jsonl`` with who judged
them, so they can be audited and re-judged by people.
"""

from __future__ import annotations

import random
from pathlib import Path

from bench.whybench.common import git

VERDICTS = ("supported", "partly", "unsupported")

Record = dict[str, object]


def sample_sentences(records: list[Record], n: int, seed: int) -> list[Record]:
    """A reproducible random sample of kept sentences, one row per sentence."""
    rows: list[Record] = []
    for r in records:
        texts = [str(t) for t in r.get("sentences", [])]  # type: ignore[union-attr]
        cites = list(r.get("citations", []))  # type: ignore[call-overload]
        for i, (text, cited) in enumerate(zip(texts, cites, strict=False)):
            rows.append(
                {
                    "id": f"{r['id']}#{i}",
                    "repo": r["repo"],
                    "kind": r["kind"],
                    "sentence": text,
                    "commit": cited[0] if cited else None,
                }
            )
    rng = random.Random(seed)  # noqa: S311 - reproducible sampling, not crypto
    return sorted(rng.sample(rows, min(n, len(rows))), key=lambda row: str(row["id"]))


def with_messages(rows: list[Record], repo_root: dict[str, Path]) -> list[Record]:
    """Attach the full message of each cited commit, as the judge will see it."""
    out: list[Record] = []
    for row in rows:
        commit = row["commit"]
        message = (
            git(repo_root[str(row["repo"])], "show", "-s", "--format=%B", str(commit)).strip()
            if commit
            else ""
        )
        out.append({**row, "commit_message": message})
    return out


def score_judgements(rows: list[Record]) -> dict[str, float]:
    """Citation precision: the share of kept sentences their cited commit fully supports."""
    judged = [r for r in rows if r.get("verdict") in VERDICTS]
    n = len(judged)
    if not n:
        return {"n": 0}
    counts = {v: sum(r["verdict"] == v for r in judged) for v in VERDICTS}
    return {
        "n": n,
        "citation_precision": round(counts["supported"] / n, 3),
        "supported_or_partly": round((counts["supported"] + counts["partly"]) / n, 3),
        "unsupported_rate": round(counts["unsupported"] / n, 3),
    }
