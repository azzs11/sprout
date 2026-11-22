"""Shared paths, repository specs and cloning for WhyBench."""

from __future__ import annotations

import json
import os
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_cache_dir

BENCH_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BENCH_DIR / "data" / "whybench-v0"
RESULTS_DIR = BENCH_DIR / "results"
LOCK_FILE = DATA_DIR / "repos.lock.json"


@dataclass(frozen=True)
class RepoSpec:
    """One benchmark repository."""

    name: str
    url: str
    license: str
    language: str
    split: str


def load_specs() -> list[RepoSpec]:
    """Repositories listed in ``bench/repos.toml``."""
    data = tomllib.loads((BENCH_DIR / "repos.toml").read_text(encoding="utf-8"))
    return [RepoSpec(**entry) for entry in data["repo"]]


def cache_dir() -> Path:
    """Where benchmark clones live (override with SPROUT_BENCH_CACHE)."""
    return Path(os.environ.get("SPROUT_BENCH_CACHE", user_cache_dir("sprout-bench")))


def repo_path(name: str) -> Path:
    """Local clone of a benchmark repository."""
    return cache_dir() / name


def git(root: Path, *args: str) -> str:
    """Run git in ``root`` and return stdout (raises on failure)."""
    done = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=True,
    )
    return done.stdout.decode("utf-8", errors="replace")


def load_lock() -> dict[str, str]:
    """Pinned snapshot commit per repository."""
    if not LOCK_FILE.exists():
        return {}
    data: dict[str, str] = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
    return data


def clone_and_pin(spec: RepoSpec, lock: dict[str, str]) -> str:
    """Clone (or reuse) a repository and check out its pinned snapshot. Returns the snapshot."""
    root = repo_path(spec.name)
    if not (root / ".git").exists():
        root.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--quiet", spec.url, str(root)],
            check=True,
        )
    snapshot = lock.get(spec.name) or git(root, "rev-parse", "origin/HEAD").strip()
    git(root, "checkout", "--quiet", "--detach", snapshot)
    return snapshot


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    """Write rows as JSON lines, sorted keys for stable diffs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in rows)
    path.write_text(text, encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, object]]:
    """Read JSON lines (missing file -> empty list)."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
