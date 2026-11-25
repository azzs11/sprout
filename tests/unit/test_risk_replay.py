"""Revert replay benchmark: labels, no time-travel leakage, and the metric arithmetic."""

from __future__ import annotations

from collections.abc import Callable

from bench.risk import metrics as m
from bench.risk.replay import Case, from_json, replay, reverted_targets, to_json
from sprout.core.git import open_repo
from sprout.core.index.indexer import build_index
from sprout.core.index.store import Store
from tests.fixtures.builder import RepoBuilder

MakeRepo = Callable[[str], RepoBuilder]


def repeated_mistake(repo: RepoBuilder) -> dict[str, str]:
    """A change is reverted, then made again by someone else and reverted again."""
    repo.write("cfg.py", "TIMEOUT_SECONDS = 30\n").commit("feat: add timeout")
    first = repo.write("cfg.py", "TIMEOUT_SECONDS = 5\n").commit("perf: lower the timeout")
    revert = repo.revert(first)
    repo.write("other.py", "VALUE_NAME = 1\n").commit("feat: other")
    second = repo.write("cfg.py", "TIMEOUT_SECONDS = 5\n").commit("perf: lower timeout again")
    repo.write("cfg.py", "TIMEOUT_SECONDS = 30\n").commit('Revert "perf: lower timeout again"')
    return {"first": first, "revert": revert, "second": second}


def replayed(make_repo: MakeRepo) -> tuple[dict[str, str], dict[str, Case], RepoBuilder]:
    repo = make_repo("empty")
    names = repeated_mistake(repo)
    git = open_repo(repo.root)
    with Store.open(repo.root, create=True) as store:
        build_index(git, store)
        cases = {c.hash: c for c in replay("fixture", git, store)}
    return names, cases, repo


def test_labels_reverts_by_hash_and_by_subject(make_repo: MakeRepo) -> None:
    repo = make_repo("empty")
    names = repeated_mistake(repo)
    with Store.open(repo.root, create=True) as store:
        build_index(open_repo(repo.root), store)
        targets = reverted_targets(store)
    assert set(targets) == {names["first"], names["second"]}
    assert targets[names["first"]][0] == names["revert"]


def test_the_repeat_is_caught_the_first_mistake_is_not(make_repo: MakeRepo) -> None:
    names, cases, _ = replayed(make_repo)
    first, second = cases[names["first"]], cases[names["second"]]
    assert first.positive
    assert first.level == "low"  # nothing in history warned against it yet
    assert second.positive
    assert second.level == "high"
    assert second.cited == [names["revert"]]
    assert second.kinds == ["reapplies_reverted"]


def test_no_future_leaks_into_earlier_commits(make_repo: MakeRepo) -> None:
    _, cases, repo = replayed(make_repo)
    for case in cases.values():
        for cited in case.cited:
            cited_at = int(repo.git("show", "-s", "--format=%ct", cited).strip())
            assert cited_at < case.committed_at


def test_cases_round_trip_through_json(make_repo: MakeRepo) -> None:
    _, cases, _ = replayed(make_repo)
    for case in cases.values():
        assert from_json(to_json(case)) == case


def case(
    hash_: str, *, positive: bool, level: str = "low", score: int = 0, baseline: int = 0
) -> Case:
    return Case(
        repo="r",
        hash=hash_,
        committed_at=0,
        reverted_by="v" if positive else None,
        reverted_at=86_400 * 3 if positive else None,
        level=level,
        score=score,
        kinds=[],
        cited=[],
        baseline=baseline,
    )


CASES = [
    case("a", positive=True, level="high", score=2001, baseline=1),
    case("b", positive=False, level="review", score=1001, baseline=1),
    case("c", positive=True, baseline=2),
    *[case(f"n{i}", positive=False) for i in range(17)],
]


def test_confusion() -> None:
    got = m.confusion(CASES, m.sprout_flag)
    assert (got["commits"], got["positives"], got["alerts"], got["hits"]) == (20, 2, 2, 1)
    assert (got["precision"], got["recall"], got["alert_rate"]) == (0.5, 0.5, 0.1)
    base = m.confusion(CASES, m.baseline_flag)
    assert (base["alerts"], base["hits"]) == (3, 2)


def test_budgets_take_the_highest_scores_and_never_zero_scores() -> None:
    five = m.at_budget(CASES, lambda c: c.score, 0.05)  # 1 of 20 commits
    assert (five["alerts"], five["hits"]) == (1, 1)
    half = m.at_budget(CASES, lambda c: c.score, 0.5)  # room for 10, only 2 have a score
    assert (half["alerts"], half["hits"]) == (2, 1)


def test_intervals_contain_the_point_estimate_and_are_reproducible() -> None:
    a = m.with_intervals(CASES, m.sprout_flag, m.reverted, seed=1)
    assert a == m.with_intervals(CASES, m.sprout_flag, m.reverted, seed=1)
    low, high = a["precision_ci"]  # type: ignore[misc]
    assert low <= a["precision"] <= high  # type: ignore[operator]


def test_lead_days() -> None:
    assert m.lead_days(CASES, m.sprout_flag) == 3.0
    assert m.lead_days([case("x", positive=False)], m.sprout_flag) is None
