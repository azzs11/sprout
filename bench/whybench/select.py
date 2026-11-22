"""Choose WhyBench tasks from real history.

Gold commits must *state* a reason. The rule below is fixed, simple and documented in the
benchmark card. It is deliberately independent of Sprout's rationale scorer, but it shares the
idea that explicit causal words mark rationale, so systems that prefer such messages are
favoured by construction (a known bias, reported with the results).

Line tasks use ``git log -L`` (git's own line history) as the reference, not Sprout's blame walk.
"""

from __future__ import annotations

import random
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from bench.whybench.common import git

STATES_REASON = re.compile(
    r"\b(because|so that|in order to|to avoid|to prevent|otherwise|due to|caused by"
    r"|as a result|the reason|without this|this (?:fixes|prevents|avoids|ensures))\b",
    re.IGNORECASE,
)
BOT_AUTHORS = re.compile(r"(dependabot|renovate|pre-commit-ci|github-actions|\[bot\])", re.I)
SOURCE_EXT = frozenset({".py", ".js", ".mjs", ".ts", ".go", ".rs"})
SKIP_PARTS = frozenset(
    {"test", "tests", "testing", "docs", "doc", "examples", "vendor", "benchmarks"}
)
MEANINGFUL = re.compile(r"\w+")
COMMENT_OR_IMPORT = re.compile(r"^\s*(#|//|/\*|\*|import\b|from\s+\S+\s+import\b|use\s|package\s)")


@dataclass(frozen=True)
class CommitInfo:
    """What the selector needs to know about one commit."""

    hash: str
    author: str
    parents: int
    message: str


def commit_info(root: Path, hashes: list[str]) -> dict[str, CommitInfo]:
    """Author, parent count and message for each hash (one git call)."""
    if not hashes:
        return {}
    out = git(root, "show", "-s", "--format=%H%x00%an%x00%P%x00%B%x1e", *hashes)
    infos: dict[str, CommitInfo] = {}
    for record in out.split("\x1e"):
        fields = record.strip("\n").split("\x00")
        if len(fields) < 4:
            continue
        h, author, parents, message = fields[0].strip(), fields[1], fields[2], fields[3]
        infos[h] = CommitInfo(h, author, len(parents.split()), message.strip())
    return infos


def is_rationale_commit(info: CommitInfo) -> bool:
    """The gold rule: a non-merge, non-revert, human commit whose message states a reason."""
    if info.parents > 1 or BOT_AUTHORS.search(info.author):
        return False
    if info.message.startswith("Revert ") or "This reverts commit" in info.message:
        return False
    return STATES_REASON.search(info.message) is not None


def source_files(root: Path, snapshot: str) -> list[str]:
    """Tracked, non-test source files at the snapshot."""
    paths = git(root, "ls-tree", "-r", "--name-only", snapshot).splitlines()
    keep: list[str] = []
    for path in paths:
        parts = path.lower().split("/")
        is_test = any(p.startswith("test_") or p.endswith("_test.go") for p in parts)
        if Path(path).suffix in SOURCE_EXT and not SKIP_PARTS.intersection(parts) and not is_test:
            keep.append(path)
    return keep


def meaningful_lines(root: Path, snapshot: str, path: str) -> list[tuple[int, str]]:
    """Lines worth asking about: real code, not blank, comment, import or bracket-only."""
    text = git(root, "show", f"{snapshot}:{path}")
    lines: list[tuple[int, str]] = []
    for number, line in enumerate(text.split("\n"), start=1):
        stripped = line.strip()
        if len(stripped) < 10 or COMMENT_OR_IMPORT.match(line):
            continue
        if len(MEANINGFUL.findall(stripped)) < 2:
            continue
        lines.append((number, line))
    return lines


def line_log(root: Path, snapshot: str, path: str, line: int, max_count: int = 40) -> list[str]:
    """``git log -L`` for one line: commits that shaped it, newest first."""
    done = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "log",
            snapshot,
            f"-L{line},{line}:{path}",
            "--format=%H",
            "-s",
            f"--max-count={max_count}",
        ],
        capture_output=True,
        check=False,
    )
    if done.returncode != 0:
        return []
    return [h for h in done.stdout.decode().split() if len(h) == 40]


def line_tasks(
    root: Path, repo: str, snapshot: str, *, target: int, seed: int
) -> list[dict[str, object]]:
    """Sample lines and keep those with a rationale commit in their history."""
    rng = random.Random(seed)  # noqa: S311 - reproducible sampling, not crypto
    files = source_files(root, snapshot)
    rng.shuffle(files)
    tasks: list[dict[str, object]] = []
    for path in files:
        if len(tasks) >= target:
            break
        candidates = meaningful_lines(root, snapshot, path)
        for number, text in rng.sample(candidates, min(3, len(candidates))):
            history = line_log(root, snapshot, path, number)
            infos = commit_info(root, history)
            gold = next((h for h in history if h in infos and is_rationale_commit(infos[h])), None)
            if gold is None:
                continue
            tasks.append(
                {
                    "id": f"{repo}-line-{len(tasks):03d}",
                    "repo": repo,
                    "snapshot": snapshot,
                    "kind": "line",
                    "path": path,
                    "line": number,
                    "line_text": text.strip(),
                    "gold": [gold],
                    "history": history,
                    "stratum": "direct" if history[0] == gold else "buried",
                }
            )
            if len(tasks) >= target:
                break
    return tasks


def question_candidates(
    root: Path, snapshot: str, *, per_repo: int, seed: int
) -> list[dict[str, object]]:
    """Rationale commits touching source code, for writing natural-language questions."""
    hashes = git(root, "log", snapshot, "--no-merges", "--format=%H", "--", ".").split()
    infos = commit_info(root, hashes[:4000])
    eligible = [i for i in infos.values() if is_rationale_commit(i) and len(i.message) < 2000]
    rng = random.Random(seed)  # noqa: S311
    rng.shuffle(eligible)
    picked: list[dict[str, object]] = []
    for info in eligible:
        files = git(root, "show", "--name-only", "--format=", info.hash).split()
        if not any(Path(f).suffix in SOURCE_EXT for f in files):
            continue
        picked.append({"hash": info.hash, "message": info.message, "files": files[:8]})
        if len(picked) >= per_repo:
            break
    return picked
