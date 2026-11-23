"""Time ``sprout why`` per task: p50/p95 latency for lines and questions."""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from bench.whybench.evaluate import Context, line_why, question_why
from bench.whybench.report import describe_commit

Task = dict[str, object]


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile (``q`` in 0..100); 0.0 for no values."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[rank - 1]


def time_tasks(
    tasks: list[Task], ctx: Context, system: Callable[[Task, Context], list[str]]
) -> list[float]:
    """Wall-clock seconds per task. The first task warms caches and models and is not counted."""
    if not tasks:
        return []
    system(tasks[0], ctx)
    timings: list[float] = []
    for task in tasks:
        start = time.perf_counter()
        system(task, ctx)
        timings.append(time.perf_counter() - start)
    return timings


def time_repo(lines: list[Task], questions: list[Task], ctx: Context) -> dict[str, list[float]]:
    """Line and question timings for one repository."""
    return {
        "line": time_tasks(lines, ctx, line_why),
        "question": time_tasks(questions, ctx, question_why),
    }


def summarise_timings(timings: list[float]) -> dict[str, float]:
    """n, p50, p95 and max in milliseconds."""
    return {
        "n": len(timings),
        "p50_ms": round(percentile(timings, 50) * 1000, 1),
        "p95_ms": round(percentile(timings, 95) * 1000, 1),
        "max_ms": round(max(timings, default=0.0) * 1000, 1),
    }


def write_speed_report(result: dict[str, object], path: Path) -> None:
    """Markdown table of per-repo and overall latency."""
    rows = result["repos"]
    if not isinstance(rows, dict):
        raise TypeError("result must contain per-repo timings")
    out = [
        f"# WhyBench v0 speed ({result['split']} split)",
        "",
        f"Generated {result['date']} by Sprout {result['sprout_version']} "
        f"(commit {describe_commit(str(result['sprout_commit']))}) on {result['machine']}. "
        "One warm-up task per repository is not counted. Lines use no models; questions use "
        f"the embedder and reranker {result['models']}.",
        "",
        "| Repository | kind | n | p50 ms | p95 ms | max ms |",
        "|---|---|---|---|---|---|",
    ]
    for repo, kinds in [*rows.items(), ("**all**", result["all"])]:
        if not isinstance(kinds, dict):
            continue
        for kind, s in kinds.items():
            out.append(
                f"| {repo} | {kind} | {s['n']} | {s['p50_ms']} | {s['p95_ms']} | {s['max_ms']} |"
            )
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
