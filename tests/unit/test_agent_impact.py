"""Agent-impact benchmark: task picking, prompts, scoring and the pruned clone."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

from bench.agent import report
from bench.agent.run import _parse, _pruned_clone, _share  # pyright: ignore[reportPrivateUsage]
from bench.agent.tasks import pick, prompt
from sprout.core.git import open_repo
from sprout.core.index.indexer import build_index
from sprout.core.index.store import Store
from tests.fixtures.builder import RepoBuilder

MakeRepo = Callable[[str], RepoBuilder]


def test_prompt_uses_the_message_without_trailers_or_history() -> None:
    text = prompt("perf: lower the timeout\n\nIt is too slow.\n\nSigned-off-by: A <a@b.c>\n")
    assert text.startswith("Please make this change in this repository: perf: lower the timeout")
    assert "It is too slow." in text
    assert "Signed-off-by" not in text
    assert "revert" not in text.lower()


def test_pick_finds_the_reverted_commit(make_repo: MakeRepo) -> None:
    repo = make_repo("payments")
    git = open_repo(repo.root)
    with Store.open(repo.root, create=True) as store:
        build_index(git, store)
        tasks = pick("payments", git, store)
    assert len(tasks) == 1
    task = tasks[0]
    assert git.commit(str(task["reverted"])).summary.startswith("perf(payments): disable")
    assert task["added"] == ["RETRIES = 0"]
    assert task["files"] == ["src/payments.py"]


def test_pick_skips_reverts_that_do_not_undo_exactly(make_repo: MakeRepo) -> None:
    repo = make_repo("empty")
    repo.write("cfg.py", "TIMEOUT_SECONDS = 30\n").commit("feat: add timeout")
    bad = repo.write("cfg.py", "TIMEOUT_SECONDS = 5\n").commit("perf: lower the timeout")
    repo.write("cfg.py", "TIMEOUT_SECONDS = 10\n").commit(
        f'Revert "x"\n\nThis reverts commit {bad}.'
    )
    git = open_repo(repo.root)
    with Store.open(repo.root, create=True) as store:
        build_index(git, store)
        assert pick("fixture", git, store) == []


def test_share_counts_added_lines_whitespace_normalised() -> None:
    task: dict[str, object] = {"added": ["RETRIES = 0", "TIMEOUT = 1"]}
    diff = "--- a/x.py\n+++ b/x.py\n-    RETRIES = 3\n+    RETRIES  =  0\n"
    assert _share(task, diff) == 0.5
    assert _share(task, "") == 0.0


def test_parse_reads_tools_result_and_cost() -> None:
    stream = "\n".join(
        json.dumps(m)
        for m in [
            {"type": "system"},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read"}]}},
            {"type": "result", "result": "done", "total_cost_usd": 0.01, "num_turns": 3},
        ]
    )
    assert _parse(stream + "\nnot json") == ("done", ["Read"], 0.01, 3)


def test_pruned_clone_cannot_see_the_future(make_repo: MakeRepo, tmp_path: Path) -> None:
    repo = make_repo("payments")
    git = open_repo(repo.root)
    with Store.open(repo.root, create=True) as store:
        build_index(git, store)
        revert = str(pick("payments", git, store)[0]["revert"])
    target = tmp_path / "clone"
    _pruned_clone(repo.root, revert, target)
    log = subprocess.run(
        ["git", "-C", str(target), "log", "--all", "--reflog", "--format=%H"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert log[0] == revert
    assert not (target / "src" / "auth.py").exists()


def test_summarise_counts_per_arm() -> None:
    task: dict[str, object] = {"repo": "r", "revert": "abc", "prompt": "Please make this change"}
    rows: list[dict[str, object]] = [
        {"arm": arm, "revert": "abc", "reapplied": arm == "baseline", "mentioned": True,
         "cited_hash": False, "edited": True, "exit": 0, "cost_usd": 0.5, "tools": []}
        for arm in ("baseline", "sprout")
    ]  # fmt: skip
    summary = report.summarise(rows, [task])
    arms = summary["arms"]
    assert isinstance(arms, dict)
    assert arms["baseline"]["reapplied"] == 1
    assert arms["sprout"]["reapplied"] == 0
