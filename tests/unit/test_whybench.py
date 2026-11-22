"""Tests for WhyBench task selection and metrics."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from bench.whybench.metrics import ndcg_at, recall_at, reciprocal_rank, score, summarise
from bench.whybench.select import CommitInfo, is_rationale_commit, line_tasks, source_files
from tests.fixtures.builder import RepoBuilder

MakeRepo = Callable[[str], RepoBuilder]


def test_metrics() -> None:
    ranked = ["a", "b", "c"]
    assert recall_at(ranked, {"b"}, 1) == 0.0
    assert recall_at(ranked, {"b"}, 5) == 1.0
    assert reciprocal_rank(ranked, {"c"}) == pytest.approx(1 / 3)
    assert reciprocal_rank(ranked, {"z"}) == 0.0
    assert ndcg_at(["g"], {"g"}) == 1.0
    assert summarise([score(ranked, {"a"}), score(ranked, {"z"})])["recall@1"] == 0.5


@pytest.mark.parametrize(
    ("message", "parents", "author", "expected"),
    [
        ("fix: retry twice because the network drops packets", 1, "Ada", True),
        ("feat: add retries", 1, "Ada", False),
        ("Merge branch x because reasons", 2, "Ada", False),
        ('Revert "x"\n\nThis reverts commit abc because it broke CI.', 1, "Ada", False),
        ("chore(deps): bump to avoid CVE", 1, "dependabot[bot]", False),
        ("refactor: inline helper so that callers stay simple", 1, "Ada", True),
    ],
)
def test_gold_rule(message: str, parents: int, author: str, expected: bool) -> None:
    assert is_rationale_commit(CommitInfo("h", author, parents, message)) is expected


def test_line_tasks_use_git_log_reference(make_repo: MakeRepo) -> None:
    built = make_repo("lineage")
    tasks = line_tasks(built.root, "lineage", built.head(), target=5, seed=1)
    fix = built.git("log", "--format=%H", "--grep=^fix(payments)")
    retries = [t for t in tasks if "retries = 5" in str(t["line_text"])]
    assert retries
    assert retries[0]["gold"] == [fix]
    assert retries[0]["stratum"] == "direct"


def test_source_files_skip_tests(make_repo: MakeRepo) -> None:
    built = make_repo("lineage")
    built.write("tests/test_core.py", "def test_x():\n    assert True\n").commit("test: add")
    assert source_files(built.root, built.head()) == ["src/payments/core.py"]
