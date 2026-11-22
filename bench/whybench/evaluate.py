"""Run every system on every WhyBench task and score the rankings."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from bench.whybench.metrics import score, summarise
from sprout.core.answer.blame import blame_line
from sprout.core.answer.evidence import enclosing_symbol, line_query
from sprout.core.answer.why import Models, why_line, why_question
from sprout.core.git.pygit2_repo import Pygit2Repo
from sprout.core.index.embedder import Embedder
from sprout.core.index.store import Store
from sprout.core.retrieve.hybrid import search
from sprout.core.retrieve.rerank import Reranker
from sprout.models import SearchMode

K = 10


@dataclass
class Context:
    """Everything a system needs for one repository."""

    root: Path
    repo: Pygit2Repo
    store: Store
    embedder: Embedder | None
    reranker: Reranker | None


Task = dict[str, object]
System = Callable[[Task, Context], list[str]]


def _search(ctx: Context, query: str, mode: SearchMode, rerank: bool) -> list[str]:
    if mode is not SearchMode.BM25 and ctx.embedder is None:
        return []
    results = search(
        ctx.store,
        query,
        mode=mode,
        limit=K,
        embedder=ctx.embedder,
        reranker=ctx.reranker if rerank else None,
    )
    return [h.commit.hash for h in results.hits]


def _line_query(task: Task, ctx: Context) -> str:
    path, line = str(task["path"]), int(str(task["line"]))
    symbol = enclosing_symbol(ctx.repo, str(task["snapshot"]), path, line)
    return line_query(symbol, str(task["line_text"]), path)


def _question(task: Task) -> str:
    return str(task["question"])


# ----- line systems -------------------------------------------------------------------


def line_blame(task: Task, ctx: Context) -> list[str]:
    """Plain ``git blame``: the last commit to touch the line."""
    return [
        blame_line(
            ctx.root, str(task["snapshot"]), str(task["path"]), int(str(task["line"]))
        ).commit
    ]


def line_log_order(task: Task, ctx: Context) -> list[str]:
    """``git log -L`` order, newest first (the reference history itself)."""
    del ctx
    return [str(h) for h in task["history"]][:K]  # type: ignore[union-attr]


def line_pickaxe(task: Task, ctx: Context) -> list[str]:
    """``git log -S<line>``: commits that added or removed this exact text."""
    done = subprocess.run(
        [
            "git",
            "-C",
            str(ctx.root),
            "log",
            str(task["snapshot"]),
            f"-S{task['line_text']}",
            "--format=%H",
            f"--max-count={K}",
            "--",
            str(task["path"]),
        ],
        capture_output=True,
        check=False,
    )
    return done.stdout.decode().split()


def line_why(task: Task, ctx: Context, *, rationale: bool = True) -> list[str]:
    """Sprout ``why`` for a line (no LLM); ``rationale=False`` is the ranking ablation."""
    answer = why_line(
        ctx.repo,
        ctx.store,
        str(task["path"]),
        int(str(task["line"])),
        rev=str(task["snapshot"]),
        models=Models(),
    )
    if rationale:
        return [e.commit.hash for e in answer.evidence][:K]
    ordered = [h.commit.hash for h in answer.history]
    ordered += [e.commit.hash for e in answer.evidence if e.commit.hash not in ordered]
    return ordered[:K]


LINE_SYSTEMS: dict[str, System] = {
    "git blame": line_blame,
    "git log -L order": line_log_order,
    "git log -S (pickaxe)": line_pickaxe,
    "bm25": lambda t, c: _search(c, _line_query(t, c), SearchMode.BM25, False),
    "hybrid": lambda t, c: _search(c, _line_query(t, c), SearchMode.HYBRID, False),
    "hybrid + rerank": lambda t, c: _search(c, _line_query(t, c), SearchMode.HYBRID, True),
    "sprout why": line_why,
    "sprout why, no rationale ranking": lambda t, c: line_why(t, c, rationale=False),
}

# ----- question systems ---------------------------------------------------------------


def question_why(task: Task, ctx: Context) -> list[str]:
    """Sprout ``why`` for a question (no LLM)."""
    models = Models(embedder=ctx.embedder, reranker=ctx.reranker)
    answer = why_question(
        ctx.repo, ctx.store, _question(task), rev=str(task["snapshot"]), models=models
    )
    return [e.commit.hash for e in answer.evidence][:K]


QUESTION_SYSTEMS: dict[str, System] = {
    "bm25": lambda t, c: _search(c, _question(t), SearchMode.BM25, False),
    "vector": lambda t, c: _search(c, _question(t), SearchMode.VECTOR, False),
    "hybrid": lambda t, c: _search(c, _question(t), SearchMode.HYBRID, False),
    "hybrid + rerank": lambda t, c: _search(c, _question(t), SearchMode.HYBRID, True),
    "sprout why": question_why,
}


def evaluate(
    tasks: list[Task], ctx: Context, systems: dict[str, System]
) -> dict[str, dict[str, list[dict[str, float]]]]:
    """Per-system, per-stratum scores for one repository's tasks."""
    out: dict[str, dict[str, list[dict[str, float]]]] = {}
    for name, system in systems.items():
        for task in tasks:
            gold = {str(g) for g in task["gold"]}  # type: ignore[union-attr]
            try:
                ranked = system(task, ctx)
            except Exception:  # a crash on one task scores zero instead of aborting the run
                ranked = []
            row = score(ranked, gold)
            buckets = out.setdefault(name, {})
            buckets.setdefault("all", []).append(row)
            stratum = str(task.get("stratum", "question"))
            buckets.setdefault(stratum, []).append(row)
    return out


def merge(
    total: dict[str, dict[str, list[dict[str, float]]]],
    part: dict[str, dict[str, list[dict[str, float]]]],
) -> None:
    """Add one repository's scores into the running total."""
    for system, buckets in part.items():
        for bucket, rows in buckets.items():
            total.setdefault(system, {}).setdefault(bucket, []).extend(rows)


def summary(
    total: dict[str, dict[str, list[dict[str, float]]]],
) -> dict[str, dict[str, dict[str, float]]]:
    """Mean metrics per system and stratum."""
    return {
        system: {bucket: summarise(rows) for bucket, rows in buckets.items()}
        for system, buckets in total.items()
    }
