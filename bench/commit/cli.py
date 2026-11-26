"""``uv run python -m bench commit-replay <select|run>``."""

from __future__ import annotations

import json
import platform
from datetime import UTC, datetime
from typing import Annotated

import typer

from bench.commit import report
from bench.commit.run import BASELINE, run_tasks
from bench.commit.tasks import PER_REPO, SINCE, pick
from bench.whybench.common import (
    BENCH_DIR,
    RESULTS_DIR,
    cache_dir,
    load_lock,
    load_specs,
    read_jsonl,
    repo_path,
)
from sprout import __version__
from sprout.core.git import open_repo
from sprout.llm.ollama import OllamaProvider
from sprout.llm.prompts import load_prompt

BENCHMARK = "commit-replay-v0"
TASKS = BENCH_DIR / "data" / BENCHMARK / "tasks.jsonl"
commit_app = typer.Typer(name="commit-replay", help="Replay real commits: Sprout vs diff-only.")


@commit_app.command()
def select(force: bool = False) -> None:
    """Pick tasks from every repository at its pinned snapshot and freeze them."""
    if TASKS.exists() and not force:
        raise typer.BadParameter(f"{TASKS} exists; tasks are frozen (use --force to re-pick).")
    lock = load_lock()
    rows = [
        task
        for spec in load_specs()
        for task in pick(spec.name, spec.split, open_repo(repo_path(spec.name)), lock[spec.name])
    ]
    TASKS.parent.mkdir(parents=True, exist_ok=True)
    TASKS.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), "utf-8")
    typer.echo(f"wrote {len(rows)} tasks to {TASKS}")


@commit_app.command()
def run(
    split: Annotated[str, typer.Option(help="tune, test or holdout")] = "tune",
    model: str = "qwen2.5-coder:7b",
    limit: Annotated[int | None, typer.Option(help="Only the first N tasks (a pilot).")] = None,
) -> None:
    """Draft every task's message and write bench/results/commit-replay-v0-<split>.{json,md}."""
    from bench.__main__ import _sprout_commit  # pyright: ignore[reportPrivateUsage]

    tasks = [t for t in read_jsonl(TASKS) if t["split"] == split][:limit]
    provider = OllamaProvider(model)
    raw = cache_dir() / f"{BENCHMARK}-{split}-{model.replace(':', '_')}.jsonl"
    rows = run_tasks(tasks, provider, raw, typer.echo)
    prompts = [load_prompt("commit_message").id, f"{BASELINE.name}@{BASELINE.version}"]
    result = report.summarise(rows) | {
        "benchmark": BENCHMARK,
        "split": split,
        "model": model,
        "prompts": prompts,
        "tasks_rule": f"{PER_REPO} per repo, people's single-parent commits since {SINCE:%Y-%m-%d}",
        "date": datetime.now(UTC).isoformat(timespec="seconds"),
        "sprout_version": __version__,
        "sprout_commit": _sprout_commit(),
        "machine": f"{platform.system()} {platform.machine()}, Python {platform.python_version()}",
        "repos": {str(t["repo"]): load_lock()[str(t["repo"])] for t in tasks},
        "rows_file": raw.name,
    }
    stem = RESULTS_DIR / f"{BENCHMARK}-{split}{'-pilot' if limit else ''}"
    stem.with_suffix(".json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    header = (
        f"# {BENCHMARK}, {split} split ({result['tasks']} commits, {model})\n\n"
        f"Sprout commit {result['sprout_commit']}; prompts {', '.join(prompts)}."
    )
    stem.with_suffix(".md").write_text(report.markdown(result, header), encoding="utf-8")
    typer.echo(f"wrote {stem}.json and .md")
