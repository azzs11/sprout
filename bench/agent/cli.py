"""``uv run python -m bench agent-impact <select|run>``."""

from __future__ import annotations

import json
import platform
import subprocess
from datetime import UTC, datetime
from typing import Annotated

import typer

from bench.agent import report
from bench.agent.run import run_all
from bench.agent.tasks import TOTAL, pick
from bench.whybench.common import BENCH_DIR, RESULTS_DIR, load_specs, read_jsonl, repo_path
from sprout import __version__
from sprout.core.git import open_repo
from sprout.core.index.store import Store

TASKS = BENCH_DIR / "data" / "agent-impact-v0" / "tasks.jsonl"
agent_app = typer.Typer(name="agent-impact", help="Does Sprout stop an agent repeating a revert?")


@agent_app.command()
def select(force: bool = False) -> None:
    """Pick tasks from the test and holdout repositories (round-robin) and freeze them."""
    if TASKS.exists() and not force:
        raise typer.BadParameter(f"{TASKS} exists; tasks are frozen (use --force to re-pick).")
    per_repo: list[list[dict[str, object]]] = []
    for spec in load_specs():
        if spec.split in ("test", "holdout"):
            root = repo_path(spec.name)
            with Store.open(root, create=False) as store:
                per_repo.append(pick(spec.name, open_repo(root), store))
    chosen = [t for rnd in range(2) for tasks in per_repo if len(tasks) > rnd for t in [tasks[rnd]]]
    TASKS.parent.mkdir(parents=True, exist_ok=True)
    TASKS.write_text("".join(json.dumps(t, sort_keys=True) + "\n" for t in chosen[:TOTAL]))
    typer.echo(f"wrote {min(len(chosen), TOTAL)} tasks to {TASKS}")


@agent_app.command()
def run(
    agent: Annotated[str, typer.Option(help="Agent CLI to run.")] = "claude",
    model: str = "haiku",
    repeats: int = 3,
    workers: int = 3,
    limit: Annotated[int | None, typer.Option(help="Only the first N tasks (a pilot).")] = None,
) -> None:
    """Run every task in both arms and write bench/results/agent-impact-v0-<model>.{json,md}."""
    tasks = read_jsonl(TASKS)[:limit]
    runs_file = run_all(
        tasks, agent=agent, model=model, repeats=repeats, workers=workers, echo=typer.echo
    )
    rows = [r for r in read_jsonl(runs_file) if r["revert"] in {t["revert"] for t in tasks}]
    result = report.summarise(rows, tasks) | {
        "benchmark": "agent-impact-v0",
        "agent": agent,
        "agent_version": _version(agent),
        "model": model,
        "repeats": repeats,
        "date": datetime.now(UTC).isoformat(timespec="seconds"),
        "sprout_version": __version__,
        "sprout_commit": _sprout_commit(),
        "machine": f"{platform.system()} {platform.machine()}, Python {platform.python_version()}",
        "runs_file": runs_file.name,
    }
    stem = RESULTS_DIR / f"agent-impact-v0-{model}{'-pilot' if limit else ''}"
    stem.with_suffix(".json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    stem.with_suffix(".md").write_text(report.markdown(result, rows), encoding="utf-8")
    typer.echo(f"wrote {stem}.json and .md")


def _sprout_commit() -> str:
    head = subprocess.run(
        ["git", "-C", str(BENCH_DIR), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    dirty = subprocess.run(
        ["git", "-C", str(BENCH_DIR.parent), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    return head.stdout.strip() + ("-dirty" if dirty.stdout.strip() else "")


def _version(agent: str) -> str:
    done = subprocess.run([agent, "--version"], capture_output=True, text=True, check=False)
    return done.stdout.strip() or agent
