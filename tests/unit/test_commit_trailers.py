"""Trailers on drafted messages, and reading them back into the history index."""

from __future__ import annotations

import subprocess
from collections.abc import Callable

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sprout.core.answer.reasons import vet_reason
from sprout.core.commit.message import draft_message
from sprout.core.commit.trailers import build_trailers, format_trailers, issue_from_branch
from sprout.core.git import open_repo
from sprout.core.git.message import parse_message, why_trailer
from sprout.models import IssueRef, Label, TrailerSource
from tests.fixtures.builder import PAYMENTS_V1, RepoBuilder

MakeRepo = Callable[[str], RepoBuilder]
WHY = "The card network drops about 1% of requests, and support tickets doubled without retries."


@pytest.mark.parametrize(
    ("branch", "number"),
    [
        ("fix/123-retry-charges", 123),
        ("gh-42", 42),
        ("issue_7", 7),
        ("ada/feature-88-dark-mode", 88),
        ("ada/dark-mode-v2", None),  # a number, but not leading a segment
        ("ada/88-dark-mode", 88),
        ("main", None),
        ("release/2026", None),
        ("2026-11-notes", None),
        ("dependabot/pip/requests-2.32", None),
    ],
)
def test_issue_from_branch(branch: str, number: int | None) -> None:
    assert issue_from_branch(branch) == number


def test_build_trailers_order_and_sources() -> None:
    trailers = build_trailers(why=WHY, fixes=[12, 12], branch="fix/12-x")
    assert [(t.key, t.value) for t in trailers] == [("Why", WHY), ("Fixes", "#12")]
    guessed = build_trailers(why=None, branch="fix/9-x")
    assert [(t.key, t.value, t.source) for t in guessed] == [("Refs", "#9", TrailerSource.BRANCH)]


def test_message_round_trips_through_git_and_the_parser(make_repo: MakeRepo) -> None:
    builder = make_repo("payments")
    builder.git("checkout", "-q", "-b", "fix/42-retries")
    builder.write("src/payments.py", PAYMENTS_V1.replace("RETRIES = 3", "RETRIES = 5"))
    repo = open_repo(builder.stage("src/payments.py").root)
    draft = draft_message(repo, repo.diff(staged=True), why=WHY, fixes=[41])
    assert [t.key for t in draft.trailers] == ["Why", "Fixes", "Refs"]
    parsed = subprocess.run(
        ["git", "interpret-trailers", "--parse"],
        input=draft.message, capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    assert parsed.splitlines() == [f"Why: {WHY}", "Fixes: #41", "Refs: #42"]
    info = parse_message(draft.message)
    assert IssueRef(number=41, closes=True) in info.refs
    assert IssueRef(number=42) in info.refs
    assert why_trailer(draft.message) == WHY
    assert vet_reason(None, draft.message).quote == WHY


def test_hand_made_revert_gets_a_reverts_trailer(make_repo: MakeRepo) -> None:
    builder = make_repo("empty")
    builder.write("pay.py", PAYMENTS_V1).commit("feat: add payments")
    bad = builder.write("pay.py", PAYMENTS_V1.replace("RETRIES = 3", "RETRIES = 0")).commit(
        "perf: disable retries"
    )
    builder.write("pay.py", PAYMENTS_V1)  # undo it by hand, without git revert
    repo = open_repo(builder.stage("pay.py").root)
    draft = draft_message(repo, repo.diff(staged=True))
    assert draft.subject == 'Revert "perf: disable retries"'
    assert draft.trailers[-1].key == "Reverts"
    assert draft.trailers[-1].value == bad
    info = parse_message(draft.message)
    assert info.reverts == [bad]
    assert Label.REVERT in info.labels


def test_partial_undo_is_not_a_revert(make_repo: MakeRepo) -> None:
    builder = make_repo("empty")
    builder.write("pay.py", PAYMENTS_V1).commit("feat: add payments")
    builder.write("pay.py", PAYMENTS_V1.replace("RETRIES = 3", "RETRIES = 0")).commit(
        "perf: disable retries"
    )
    builder.write("pay.py", PAYMENTS_V1.replace("RETRIES = 3", "RETRIES = 2"))
    repo = open_repo(builder.stage("pay.py").root)
    draft = draft_message(repo, repo.diff(staged=True))
    assert all(t.key != "Reverts" for t in draft.trailers)


def test_reverts_trailer_needs_a_hash() -> None:
    assert parse_message("Add tests\n\nReverts: #2991").reverts == []  # click uses PR numbers
    assert parse_message("Undo x\n\nReverts: 0123abc").reverts == ["0123abc"]


def test_why_only_in_the_trailer_block() -> None:
    assert why_trailer("fix: x\n\nWhy: in the body, then more text\n\nSigned-off-by: A") is None
    assert why_trailer("Why: subject only") is None
    folded = "fix: x\n\nWhy: first part\n  second part\nFixes: #3"
    assert why_trailer(folded) == "first part second part"


@given(st.text(alphabet=st.characters(blacklist_categories=("Cc", "Cs")), min_size=1, max_size=300))
def test_folded_why_reads_back(text: str) -> None:
    why = " ".join(text.split())
    if not why:
        return
    message = "fix: x\n\n" + format_trailers(build_trailers(why=why))
    assert why_trailer(message) == why
