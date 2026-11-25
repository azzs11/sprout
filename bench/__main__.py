"""Bench commands: ``uv run python -m bench <build|lines|candidates|run|speed|answers|faithfulness|risk|hook-speed|agent-impact>``."""

from __future__ import annotations

import json
import platform
import subprocess
import zlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from bench.whybench.answers import (
    answer_task,
    closed_book_task,
    drop_counts,
    summarise_closed_book,
    summary_by_group,
    write_answers_report,
)
from bench.whybench.common import (
    DATA_DIR,
    LOCK_FILE,
    RESULTS_DIR,
    cache_dir,
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
from bench.whybench.faithfulness import sample_sentences, score_judgements, with_messages
from bench.whybench.report import describe_commit, write_report
from bench.whybench.select import line_tasks, question_candidates
from bench.whybench.speed import summarise_timings, time_repo, write_speed_report
from sprout import __version__, services
from sprout.config import Settings
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
def build(repos: Repos = None, no_embed: bool = False, rebuild: bool = False) -> None:
    """Clone each repository, pin its snapshot and build its Sprout index."""
    lock = load_lock()
    embedder = None if no_embed else FastEmbedder(DEFAULT_EMBED_MODEL, _models_dir())
    for spec in load_specs():
        if spec.name not in _selected(repos):
            continue
        lock[spec.name] = clone_and_pin(spec, lock)
        root = repo_path(spec.name)
        if rebuild:
            for suffix in ("", "-wal", "-shm"):
                (root / ".sprout" / f"index.db{suffix}").unlink(missing_ok=True)
        with Store.open(root, create=True) as store:
            stats = build_index(open_repo(root), store, embedder=embedder)
        typer.echo(f"{spec.name}: {stats.commits} commits, {stats.embedded} embedded")
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@app.command()
def lines(repos: Repos = None, per_repo: int = 40) -> None:
    """Generate line tasks from ``git log -L`` histories (replaces only the selected repos)."""
    lock = load_lock()
    selected = _selected(repos)
    # Keep other repositories' tasks, so adding a repository never rewrites existing ones.
    tasks = [t for t in read_jsonl(DATA_DIR / "lines.jsonl") if t["repo"] not in selected]
    for name in selected:
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
    split: Annotated[str, typer.Option(help="test, tune, holdout or all")] = "test",
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


@app.command()
def speed(split: Annotated[str, typer.Option(help="test, tune, holdout or all")] = "test") -> None:
    """Time sprout why per task and write bench/results/whybench-v0-speed-<split>.{json,md}."""
    specs = [s for s in load_specs() if split == "all" or s.split == split]
    line_rows = read_jsonl(DATA_DIR / "lines.jsonl")
    question_rows = read_jsonl(DATA_DIR / "questions.jsonl")
    embedder = FastEmbedder(DEFAULT_EMBED_MODEL, _models_dir())
    reranker = FastReranker(DEFAULT_RERANK_MODEL, _models_dir())
    per_repo: dict[str, dict[str, dict[str, float]]] = {}
    pooled: dict[str, list[float]] = {"line": [], "question": []}
    for spec in specs:
        root = repo_path(spec.name)
        with Store.open(root, create=False) as store:
            ctx = Context(root, open_repo(root), store, embedder, reranker)
            timings = time_repo(
                [t for t in line_rows if t["repo"] == spec.name],
                [t for t in question_rows if t["repo"] == spec.name],
                ctx,
            )
        per_repo[spec.name] = {k: summarise_timings(v) for k, v in timings.items()}
        for kind, values in timings.items():
            pooled[kind] += values
        typer.echo(f"timed {spec.name}")
    result: dict[str, object] = {
        "benchmark": "whybench-v0-speed",
        "split": split,
        "date": datetime.now(UTC).isoformat(timespec="seconds"),
        "sprout_version": __version__,
        "sprout_commit": _sprout_commit(),
        "machine": f"{platform.system()} {platform.machine()}, Python {platform.python_version()}",
        "models": {"embed": DEFAULT_EMBED_MODEL, "rerank": DEFAULT_RERANK_MODEL},
        "repos": per_repo,
        "all": {k: summarise_timings(v) for k, v in pooled.items()},
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"whybench-v0-speed-{split}"
    (RESULTS_DIR / f"{stem}.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    write_speed_report(result, RESULTS_DIR / f"{stem}.md")
    typer.echo(f"wrote {RESULTS_DIR / stem}.json and .md")


@app.command()
def answers(
    model: Annotated[str, typer.Option(help="Ollama model, e.g. qwen2.5-coder:3b")],
    split: Annotated[str, typer.Option(help="test, tune, holdout or all")] = "tune",
    per_repo: Annotated[int, typer.Option(help="Tasks per repo and kind (0 = all)")] = 0,
    closed_book: Annotated[bool, typer.Option(help="Also run the no-history baseline")] = True,
) -> None:
    """Score model-written answers; writes bench/results/whybench-v0-answers-<split>.{json,md}."""
    settings = Settings(llm_provider="ollama", llm_model=model)
    answerer, note = services.build_answerer(settings)
    if answerer is None:
        raise typer.BadParameter(note or "no model available", param_hint="--model")
    specs = [s for s in load_specs() if split == "all" or s.split == split]
    tasks = read_jsonl(DATA_DIR / "lines.jsonl") + read_jsonl(DATA_DIR / "questions.jsonl")
    embedder = FastEmbedder(DEFAULT_EMBED_MODEL, _models_dir())
    reranker = FastReranker(DEFAULT_RERANK_MODEL, _models_dir())
    records: list[dict[str, object]] = []
    blind: list[dict[str, object]] = []
    for spec in specs:
        root = repo_path(spec.name)
        with Store.open(root, create=False) as store:
            ctx = Context(root, open_repo(root), store, embedder, reranker)
            for kind in ("line", "question"):
                mine = [t for t in tasks if t["repo"] == spec.name and t["kind"] == kind]
                for task in mine[:per_repo] if per_repo else mine:
                    records.append(answer_task(task, ctx, answerer))
                    if closed_book:
                        blind.append(closed_book_task(task, answerer.provider))
        typer.echo(f"answered {spec.name}")
    commit = _sprout_commit()
    result: dict[str, object] = {
        "benchmark": "whybench-v0-answers",
        "split": split,
        "per_repo": per_repo or None,
        "date": datetime.now(UTC).isoformat(timespec="seconds"),
        "sprout_version": __version__,
        "sprout_commit": commit,
        "sprout_commit_label": describe_commit(commit),
        "model": answerer.model_id,
        "machine": f"{platform.system()} {platform.machine()}, Python {platform.python_version()}",
        "repos": {s.name: load_lock()[s.name] for s in specs},
        "groups": summary_by_group(records),
        "drops": drop_counts(records),
        "closed_book": {
            kind: summarise_closed_book([r for r in blind if (r["kind"] == "question") == q])
            for kind, q in (("line", False), ("question", True))
        }
        if closed_book
        else None,
    }
    stem = f"whybench-v0-answers-{split}"
    detail = _answers_detail(split, model)
    write_jsonl(detail, records)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / f"{stem}.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    write_answers_report(result, RESULTS_DIR / f"{stem}.md")
    typer.echo(f"wrote {RESULTS_DIR / stem}.json and .md; per-task replies in {detail}")


@app.command()
def faithfulness(
    model: Annotated[str, typer.Option(help="Model whose answers to sample")],
    split: Annotated[str, typer.Option(help="test, tune or holdout")] = "test",
    sample: Annotated[int, typer.Option(help="Sentences to sample")] = 60,
) -> None:
    """Export a judging sample, or score data/whybench-v0/faithfulness-<split>.jsonl once judged."""
    judged_path = DATA_DIR / f"faithfulness-{split}.jsonl"
    judged = read_jsonl(judged_path)
    if judged:
        stats = score_judgements(judged)
        out = RESULTS_DIR / f"whybench-v0-faithfulness-{split}.json"
        out.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
        typer.echo(f"{stats} -> {out}")
        return
    detail = _answers_detail(split, model)
    rows = sample_sentences(read_jsonl(detail), sample, seed=_seed(f"faithfulness-{split}"))
    roots = {s.name: repo_path(s.name) for s in load_specs()}
    target = cache_dir() / f"faithfulness-{split}-to-judge.jsonl"
    write_jsonl(target, with_messages(rows, roots))
    typer.echo(f"{len(rows)} sentences to judge in {target}; save verdicts to {judged_path}")


def _answers_detail(split: str, model: str) -> Path:
    """Per-task answer records for one split and model (kept in the cache, not committed)."""
    safe = model.replace(":", "_").replace("/", "_")
    return cache_dir() / f"whybench-v0-answers-{split}-{safe}.jsonl"


@app.command()
def risk(split: Annotated[str, typer.Option(help="test, tune, holdout or all")] = "tune") -> None:
    """Revert replay: would sprout risk have warned before each revert? (bench/risk/)."""
    from bench.risk.run import run_split

    stem = run_split(split, _sprout_commit(), typer.echo)
    typer.echo(f"wrote {stem}.json and .md")


@app.command("hook-speed")
def hook_speed(
    split: Annotated[str, typer.Option(help="test, tune, holdout or all")] = "tune",
) -> None:
    """Time sprout-hook agent per edit (fresh process each) on every repository in a split."""
    from bench.risk.run import run_hook_speed

    stem = run_hook_speed(split, _sprout_commit(), typer.echo)
    typer.echo(f"wrote {stem}.json and .md")


def _register_agent_impact() -> None:
    from bench.agent.cli import agent_app

    app.add_typer(agent_app)


_register_agent_impact()


def _sprout_commit() -> str:
    done = subprocess.run(
        ["git", "-C", str(Path(__file__).parent), "rev-parse", "HEAD"],
        capture_output=True,
        check=False,
    )
    status = subprocess.run(
        [
            "git",
            "-C",
            str(Path(__file__).parent.parent),
            "status",
            "--porcelain",
            "--",
            "src",
            "bench",
        ],
        capture_output=True,
        check=False,
    )
    dirty = any(
        line and not line.endswith((".json", ".md", ".jsonl"))
        for line in status.stdout.decode().splitlines()
    )
    return done.stdout.decode().strip() + ("-dirty" if dirty else "")


if __name__ == "__main__":
    app()
