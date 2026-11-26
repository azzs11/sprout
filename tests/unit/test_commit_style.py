"""Learning a repository's commit style from its history."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from sprout.core.commit.style import is_imperative, learn_style, trailer_keys
from sprout.core.git import open_repo
from tests.fixtures.builder import RepoBuilder

MakeRepo = Callable[[str], RepoBuilder]


def test_conventional_history(make_repo: MakeRepo) -> None:
    style = learn_style(open_repo(make_repo("payments").root))
    # 7 commits; the revert is skipped.
    assert style.sample_size == 6
    assert style.conventional_share == 1.0
    assert {c.value: c.count for c in style.types} == {"feat": 2, "fix": 2, "perf": 1, "docs": 1}
    assert style.scopes[0].value == "auth"
    assert style.capitalised_share == 0.0
    assert style.period_share == 0.0
    assert style.imperative_share == 1.0
    assert (
        style.examples[0] == "fix(auth): compare tokens in constant time to prevent timing attacks"
    )


def test_plain_history_with_bodies_and_trailers(make_repo: MakeRepo) -> None:
    repo = make_repo("empty")
    repo.write("a.py", "a = 1\n").commit("Added the first module.")
    repo.write("a.py", "a = 2\n").commit(
        "Bump a to 2 (#12)\n\nThe old value broke imports.\n\nSigned-off-by: Ada <a@b.c>"
    )
    repo.write("a.py", "a = 3\n").commit("Fixes a again\n\nSigned-off-by: Ada <a@b.c>")
    style = learn_style(open_repo(repo.root))
    assert style.sample_size == 3
    assert style.conventional_share == 0.0
    assert style.types == []
    assert style.capitalised_share == 1.0
    assert style.period_share == pytest.approx(0.333)
    assert style.imperative_share == pytest.approx(0.333)
    assert style.body_share == pytest.approx(0.333)  # a trailer alone is not a body
    assert style.pr_suffix_share == pytest.approx(0.333)
    assert [(c.value, c.count) for c in style.trailers] == [("Signed-off-by", 2)]


def test_bots_are_skipped_and_trailer_case_is_merged(make_repo: MakeRepo) -> None:
    repo = make_repo("empty")
    repo.write("a.py", "a = 1\n").commit("feat: a\n\nCo-authored-by: B <b@c.d>")
    repo.write("a.py", "a = 2\n").commit("fix: a\n\nCo-Authored-By: C <c@d.e>")
    repo.write("a.py", "a = 3\n").commit("fix: a again\n\nCo-authored-by: D <d@e.f>")
    repo.write("b.txt", "1\n").commit("[automated] Update plugin list")
    bot = "dependabot[bot] <bot@example.com>"
    repo.git("commit", "--allow-empty", f"--author={bot}", "-m", "build(deps): bump x")
    style = learn_style(open_repo(repo.root))
    assert style.sample_size == 3
    assert [(c.value, c.count) for c in style.trailers] == [("Co-authored-by", 3)]


def test_merges_are_skipped_and_empty_repos_are_fine(make_repo: MakeRepo) -> None:
    merged = learn_style(open_repo(make_repo("merge").root))
    assert merged.sample_size > 0
    assert all(not e.startswith("Merge") for e in merged.examples)
    empty = learn_style(open_repo(make_repo("empty").root))
    assert empty.sample_size == 0
    assert empty.subject_p50 == 0
    assert empty.conventional_share == 0.0


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("add retries", True),
        ("Add retries", True),
        ("added retries", False),
        ("adds retries", False),
        ("fixes the bug", False),
        ("process events", True),
        ("focus the input", True),
        ("embed the docs", True),
        ("updates README", False),
        ("v2 support", True),
        ("", True),
    ],
)
def test_is_imperative(description: str, expected: bool) -> None:
    assert is_imperative(description) is expected


def test_trailer_keys_need_a_whole_trailer_paragraph() -> None:
    assert trailer_keys("fix: x\n\nWhy: it broke\nFixes: #4") == ["Why", "Fixes"]
    assert trailer_keys("fix: x\n\nIt broke. See: the log") == []
    assert trailer_keys("Signed-off-by: only a subject") == []


def test_crlf_messages_and_squash_commit_lists(make_repo: MakeRepo) -> None:
    repo = make_repo("empty")
    repo.write("a.py", "a = 1\n").commit(
        "Add a (#1)\n\n* Add a\r\n\r\n* Update a.py\r\n\r\n---------"
    )
    repo.write("a.py", "a = 2\n").commit("Bump a (#2)\n\nCo-authored-by: B <b@c.d>\r\n")
    repo.write("a.py", "a = 3\n").commit("Fix a (#3)\n\nThe old value broke imports.\r\nSee #2.")
    style = learn_style(open_repo(repo.root))
    assert style.body_share == round(1 / 3, 3)  # only the hand-written body counts
    assert [c.value for c in style.trailers] == ["Co-authored-by"]
    assert trailer_keys("x\r\n\r\nSigned-off-by: A <a@b.c>\r\n") == ["Signed-off-by"]
