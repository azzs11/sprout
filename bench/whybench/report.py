"""Render WhyBench results as a Markdown table."""

from __future__ import annotations

from pathlib import Path

METRICS = ("recall@1", "recall@5", "mrr@10", "ndcg@10")


def _table(title: str, block: dict[str, dict[str, dict[str, float]]], bucket: str) -> list[str]:
    rows = [(name, buckets[bucket]) for name, buckets in block.items() if bucket in buckets]
    if not rows:
        return []
    n = int(rows[0][1].get("n", 0))
    lines = [f"### {title} (n = {n})", "", "| System | " + " | ".join(METRICS) + " |"]
    lines.append("|---|" + "---|" * len(METRICS))
    best = {m: max(r[1].get(m, 0.0) for r in rows) for m in METRICS}
    for name, stats in rows:
        cells = []
        for m in METRICS:
            value = stats.get(m, 0.0)
            cell = f"{value:.3f}"
            cells.append(f"**{cell}**" if value == best[m] and value > 0 else cell)
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return [*lines, ""]


def _commit(sha: str) -> str:
    dirty = sha.endswith("-dirty")
    short = sha.removesuffix("-dirty")[:12]
    return f"{short}, plus uncommitted changes" if dirty else short


def write_report(result: dict[str, object], path: Path) -> None:
    """Write the results tables, with the run's provenance, to ``path``."""
    line = result["line"]
    question = result["question"]
    if not isinstance(line, dict) or not isinstance(question, dict):
        raise TypeError("result must contain 'line' and 'question' summaries")
    out = [
        f"# WhyBench v0 results ({result['split']} split)",
        "",
        f"Generated {result['date']} by Sprout {result['sprout_version']} "
        f"(commit {_commit(str(result['sprout_commit']))}). Models: {result['models']}. "
        "No LLM was used (retrieval and ranking only).",
        "",
        "Repositories and snapshots: "
        + ", ".join(f"{k} `{str(v)[:10]}`" for k, v in dict(result["repos"]).items())  # type: ignore[arg-type]
        + ".",
        "",
        "## Line questions: which commit explains `path:line`?",
        "",
        *_table("All line tasks", line, "all"),  # type: ignore[arg-type]
        *_table("Direct: blame already points at the gold commit", line, "direct"),  # type: ignore[arg-type]
        *_table("Buried: the gold commit is further back in the line's history", line, "buried"),  # type: ignore[arg-type]
        "## Natural-language questions",
        "",
        *_table("All questions", question, "all"),  # type: ignore[arg-type]
    ]
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
