"""WhyBench commands: ``uv run python -m bench <build|lines|candidates|run>``."""

from __future__ import annotations

import json
import subprocess
import zlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from bench.whybench.common import (
    DATA_DIR,
    LOCK_FILE,
    RESULTS_DIR,
    clone_and_pin,
    load_lock,
    load_specs,
    read_jsonl,
    repo_path,
    write_jsonl,
)
from bench.whybench.evaluate import (
    LINE_SYSTEMS,
    QUESTION_SYSTEMS,
    Context,
    evaluate,
    merge,
    summary,
)
from bench.whybench.report import write_report
from bench.whybench.select import line_tasks, question_candidates
from sprout import __version__
from sprout.core.git import open_repo
from sprout.core.index.embedder import DEFAULT_EMBED_MODEL, FastEmbedder
from sprout.core.index.indexer import build_index
from sprout.core.index.store import Store
from sprout.core.retrieve.rerank import DEFAULT_RERANK_MODEL, FastReranker

app = typer.Typer(add_completion=False, help="WhyBench: measure how well tools explain code.")
Repos = Annotated[str | None, typer.Option(help="Comma-separated repo names (default: all).")]


def _selected(repos: str | None) -> list[str]:
    names = [s.name for s in load_specs()]
    if repos is None:
        return names
    wanted = [r.strip() for r in repos.split(",")]
    return [n for n in names if n in wanted]


def _seed(name: str) -> int:
    return zlib.crc32(name.encode())


def _models_dir() -> Path:
    from platformdirs import user_cache_dir

    return Path(user_cache_dir("sprout")) / "models"


@app.command()
def build(repos: Repos = None, no_embed: bool = False) -> None:
    """Clone each repository, pin its snapshot and build its Sprout index."""
    lock = load_lock()
    embedder = None if no_embed else FastEmbedder(DEFAULT_EMBED_MODEL, _models_dir())
    for spec in load_specs():
        if spec.name not in _selected(repos):
            continue
        lock[spec.name] = clone_and_pin(spec, lock)
        root = repo_path(spec.name)
        with Store.open(root, create=True) as store:
            stats = build_index(open_repo(root), store, embedder=embedder)
        typer.echo(f"{spec.name}: {stats.commits} commits, {stats.embedded} embedded")
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@app.command()
def lines(repos: Repos = None, per_repo: int = 40) -> None:
    """Generate line tasks from ``git log -L`` histories."""
    lock = load_lock()
    tasks: list[dict[str, object]] = []
    for name in _selected(repos):
        found = line_tasks(repo_path(name), name, lock[name], target=per_repo, seed=_seed(name))
        typer.echo(f"{name}: {len(found)} line tasks")
        tasks += found
    write_jsonl(DATA_DIR / "lines.jsonl", tasks)


@app.command()
def candidates(repos: Repos = None, per_repo: int = 14, out: Path | None = None) -> None:
    """Dump rationale commits to write natural-language questions from (not committed)."""
    lock = load_lock()
    rows: list[dict[str, object]] = []
    for name in _selected(repos):
        for row in question_candidates(
            repo_path(name), lock[name], per_repo=per_repo, seed=_seed(name)
        ):
            rows.append({"repo": name, "snapshot": lock[name], **row})
    target = out or repo_path("_candidates.jsonl")
    write_jsonl(target, rows)
    typer.echo(f"{len(rows)} candidates written to {target}")


@app.command()
def run(
    split: Annotated[str, typer.Option(help="test, tune or all")] = "test",
    no_models: bool = False,
) -> None:
    """Score every system and write bench/results/whybench-v0.{json,md}."""
    specs = [s for s in load_specs() if split == "all" or s.split == split]
    line_rows = read_jsonl(DATA_DIR / "lines.jsonl")
    question_rows = read_jsonl(DATA_DIR / "questions.jsonl")
    embedder = None if no_models else FastEmbedder(DEFAULT_EMBED_MODEL, _models_dir())
    reranker = None if no_models else FastReranker(DEFAULT_RERANK_MODEL, _models_dir())
    line_total: dict[str, dict[str, list[dict[str, float]]]] = {}
    question_total: dict[str, dict[str, list[dict[str, float]]]] = {}
    for spec in specs:
        root = repo_path(spec.name)
        with Store.open(root, create=False) as store:
            ctx = Context(root, open_repo(root), store, embedder, reranker)
            merge(
                line_total,
                evaluate([t for t in line_rows if t["repo"] == spec.name], ctx, LINE_SYSTEMS),
            )
            merge(
                question_total,
                evaluate(
                    [t for t in question_rows if t["repo"] == spec.name], ctx, QUESTION_SYSTEMS
                ),
            )
        typer.echo(f"scored {spec.name}")
    result = {
        "benchmark": "whybench-v0",
        "split": split,
        "date": datetime.now(UTC).isoformat(timespec="seconds"),
        "sprout_version": __version__,
        "sprout_commit": _sprout_commit(),
        "models": None
        if no_models
        else {"embed": DEFAULT_EMBED_MODEL, "rerank": DEFAULT_RERANK_MODEL},
        "llm": None,
        "repos": {s.name: load_lock()[s.name] for s in specs},
        "line": summary(line_total),
        "question": summary(question_total),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"whybench-v0-{split}"
    (RESULTS_DIR / f"{stem}.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    write_report(result, RESULTS_DIR / f"{stem}.md")
    typer.echo(f"wrote {RESULTS_DIR / stem}.json and .md")


def _sprout_commit() -> str:
    done = subprocess.run(
        ["git", "-C", str(Path(__file__).parent), "rev-parse", "HEAD"],
        capture_output=True,
        check=False,
    )
    return done.stdout.decode().strip()


if __name__ == "__main__":
    app()
