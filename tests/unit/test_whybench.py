"""Tests for WhyBench task selection and metrics."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from bench.whybench.metrics import ndcg_at, recall_at, reciprocal_rank, score, summarise
from bench.whybench.select import CommitInfo, is_rationale_commit, line_tasks, source_files
from bench.whybench.speed import percentile, summarise_timings, write_speed_report
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


def test_percentile_nearest_rank() -> None:
    values = [0.1 * i for i in range(1, 21)]
    assert percentile(values, 50) == pytest.approx(1.0)
    assert percentile(values, 95) == pytest.approx(1.9)
    assert percentile([], 50) == 0.0


def test_summarise_timings_in_milliseconds() -> None:
    assert summarise_timings([0.01, 0.02, 0.03]) == {
        "n": 3,
        "p50_ms": 20.0,
        "p95_ms": 30.0,
        "max_ms": 30.0,
    }


def test_speed_report_notes_uncommitted_changes(tmp_path: Path) -> None:
    timing = {"line": {"n": 1, "p50_ms": 1.0, "p95_ms": 1.0, "max_ms": 1.0}}
    result: dict[str, object] = {
        "split": "tune",
        "date": "2026-11-23",
        "sprout_version": "0.1.0",
        "sprout_commit": "a" * 40 + "-dirty",
        "machine": "test",
        "models": {},
        "repos": {"click": timing},
        "all": timing,
    }
    write_speed_report(result, tmp_path / "speed.md")
    text = (tmp_path / "speed.md").read_text()
    assert "plus uncommitted changes" in text
    assert "| **all** | line | 1 |" in text


def test_closed_book_scores_memorised_hash_and_unsupported_reason() -> None:
    from bench.whybench.answers import closed_book_task, summarise_closed_book
    from tests.fakes import FakeProvider

    task: dict[str, object] = {
        "id": "x-q-000",
        "kind": "question",
        "repo": "x",
        "question": "Why?",
        "gold": ["abcdef1234" + "0" * 30],
    }
    hit = closed_book_task(task, FakeProvider(reply='{"commit": "ABCDEF1", "reason": "speed"}'))
    miss = closed_book_task(task, FakeProvider(reply='{"commit": "abc", "reason": null}'))
    broken = closed_book_task(task, FakeProvider(reply="no idea"))
    assert (hit["cites_gold"], hit["asserts_reason"]) == (True, True)
    assert (miss["cites_gold"], miss["names_commit"], miss["asserts_reason"]) == (
        False,
        False,
        False,
    )
    assert broken["asserts_reason"] is False
    assert summarise_closed_book([hit, miss, broken])["cites_gold"] == 0.333


def test_faithfulness_sample_is_reproducible_and_scores_precision() -> None:
    from bench.whybench.faithfulness import sample_sentences, score_judgements

    records: list[dict[str, object]] = [
        {
            "id": f"r-{i}",
            "repo": "x",
            "kind": "line",
            "sentences": ["a", "b"],
            "citations": [["h1"], ["h2"]],
        }
        for i in range(5)
    ]
    first = sample_sentences(records, 4, seed=7)
    assert first == sample_sentences(records, 4, seed=7)
    assert len(first) == 4
    assert {r["commit"] for r in first} <= {"h1", "h2"}
    verdicts = ["supported", "supported", "partly", "unsupported", "skip"]
    stats = score_judgements([{"verdict": v} for v in verdicts])
    assert stats == {
        "n": 4,
        "citation_precision": 0.5,
        "supported_or_partly": 0.75,
        "unsupported_rate": 0.25,
    }
