"""Tests for commit-message parsing."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sprout.core.git.message import parse_message, parse_refs
from sprout.models import IssueRef, Label


@pytest.mark.parametrize(
    ("subject", "ctype", "scope"),
    [
        ("feat: add login", "feat", None),
        ("fix(auth): handle expired tokens", "fix", "auth"),
        ("refactor!: drop python 3.8", "refactor", None),
        ("Fix the bug", None, None),
        ("feat:missing space", None, None),
        ("Merge pull request #12 from a/b", None, None),
    ],
)
def test_conventional_type(subject: str, ctype: str | None, scope: str | None) -> None:
    info = parse_message(subject)
    assert (info.conventional_type, info.scope) == (ctype, scope)


def test_breaking_from_bang_and_footer() -> None:
    assert Label.BREAKING in parse_message("feat!: new api").labels
    assert Label.BREAKING in parse_message("feat: x\n\nBREAKING CHANGE: removed y").labels
    assert Label.BREAKING not in parse_message("feat: x").labels


def test_git_revert_message() -> None:
    message = (
        'Revert "perf: disable retries"\n\n'
        "This reverts commit 0123456789abcdef0123456789abcdef01234567.\n"
    )
    info = parse_message(message)
    assert info.reverts == ["0123456789abcdef0123456789abcdef01234567"]
    assert info.reverts_summary == "perf: disable retries"
    assert Label.REVERT in info.labels


def test_revert_subject_without_hash() -> None:
    info = parse_message('Revert "feat: shiny thing" (#88)')
    assert info.reverts == []
    assert Label.REVERT in info.labels


def test_conventional_revert_type() -> None:
    assert Label.REVERT in parse_message("revert: undo shiny thing").labels


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("fix: crash (#12)", [IssueRef(number=12)]),
        ("Fixes #7 and refs #8", [IssueRef(number=7, closes=True), IssueRef(number=8)]),
        ("closes: #3", [IssueRef(number=3, closes=True)]),
        ("see GH-42", [IssueRef(number=42)]),
        ("resolves octo/repo#9", [IssueRef(number=9, repo="octo/repo", closes=True)]),
        ("#5 then fixes #5", [IssueRef(number=5, closes=True)]),
        ("C# support, color &#35; and a#1", []),
        ("https://example.com/page#12", []),
    ],
)
def test_refs(message: str, expected: list[IssueRef]) -> None:
    assert parse_refs(message) == expected


@pytest.mark.parametrize(
    ("message", "label", "present"),
    [
        ("fix: off by one", Label.FIX, True),
        ("Fix crash on empty input", Label.FIX, True),
        ("feat: add fixture loader", Label.FIX, False),
        ("chore: bump dep for CVE-2024-1234", Label.SECURITY, True),
        ("fix: escape html to prevent XSS", Label.SECURITY, True),
        ("docs: security policy", Label.SECURITY, True),
        ("feat: dark mode", Label.SECURITY, False),
    ],
)
def test_labels(message: str, label: Label, present: bool) -> None:
    assert (label in parse_message(message).labels) is present


def test_merge_label() -> None:
    assert Label.MERGE in parse_message("Merge branch 'x'", is_merge=True).labels


@given(st.text(max_size=500))
def test_parse_message_never_crashes(message: str) -> None:
    info = parse_message(message)
    assert all(ref.number >= 0 for ref in info.refs)
