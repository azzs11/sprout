"""The commit-replay benchmark: metrics and the as-of-parent repository view."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from bench.commit import metrics as m
from bench.commit.report import summarise
from bench.commit.run import _real_body  # pyright: ignore[reportPrivateUsage]
from bench.commit.view import AtCommit
from sprout.core.commit.message import draft_message
from sprout.core.commit.style import learn_style
from sprout.core.git import open_repo
from sprout.models import CommitStyle
from tests.fixtures.builder import RepoBuilder

MakeRepo = Callable[[str], RepoBuilder]


def _style(**fields: object) -> CommitStyle:
    base: dict[str, object] = {
        "sample_size": 10, "conventional_share": 1.0, "types": [], "scopes": [],
        "subject_p50": 40, "subject_p90": 60, "capitalised_share": 0.0, "period_share": 0.0,
        "imperative_share": 1.0, "body_share": 0.0, "pr_suffix_share": 0.0, "trailers": [],
        "examples": [],
    }  # fmt: skip
    return CommitStyle.model_validate(base | fields)


def test_rouge_l() -> None:
    assert m.rouge_l("fix the retry loop", "fix the retry loop") == 1.0
    assert m.rouge_l("", "x") == 0.0
    assert m.rouge_l("retry loop fix", "fix retry loop") == pytest.approx(2 / 3)


def test_style_checks_compare_with_the_author() -> None:
    style = _style()
    assert m.style_checks("fix(api): drop retries", "fix: retry less", style) == {
        "prefix": True, "capital": True, "period": True, "length": True,
    }  # fmt: skip
    assert m.style_score("Drop retries.", "fix: retry less", style) == 0.25  # length only
    assert m.style_score("Drop retries", "Retry less", style) == 1.0


def test_message_shape_metrics() -> None:
    assert m.restates_subject("fix: drop retry loop", "Drop the retry loop.")
    assert not m.restates_subject("fix: drop retry loop", "Charges now fail fast.")
    assert m.gives_reason("fix: x", "Retries are removed because they double-charged.")
    assert not m.gives_reason("fix: handle failing test", None)
    assert m.asks_why("Why does charge() no longer retry?")
    assert not m.asks_why("What changes were made to charge(), and why?")
    assert m.type_match("fix: a", "fix(x): b") is True
    assert m.type_match("feat: a", "Plain subject") is None


def test_real_body_drops_trailers() -> None:
    assert _real_body("Body text.\n\nSigned-off-by: A <a@b.c>") == "Body text."
    assert _real_body("Signed-off-by: A <a@b.c>") is None
    assert _real_body("") is None


def test_view_hides_the_commit_and_everything_after(make_repo: MakeRepo) -> None:
    builder = make_repo("payments")
    repo = open_repo(builder.root)
    commits = repo.history().commits  # newest first
    target = commits[2]  # an older commit with later history above it
    view = AtCommit(repo, target.hash)
    seen = {c.hash for c in view.history().commits}
    assert target.hash not in seen
    assert not seen & {c.hash for c in commits[:2]}
    assert [f.path for f in view.diff(staged=True).files] == [
        f.path for f in repo.commit_diff(target.hash).files
    ]
    assert view.status().branch is None
    draft = draft_message(view, view.diff(staged=True), style=learn_style(view))
    assert target.summary not in draft.examples


def test_summarise_pairs_arms() -> None:
    arms = {
        "sprout": {"subject": "fix: drop retries", "body": None, "question": "Why drop them?",
                   "model_ok": True, "seconds": 1.0},
        "diff_only": {"subject": "Drop retries.", "body": "Drop retries.", "model_ok": True,
                      "seconds": 2.0},
        "skeleton": {"subject": "fix: update a.py", "body": None},
        "real": {"subject": "fix: drop retries", "body": None},
    }  # fmt: skip
    row: dict[str, object] = {
        "repo": "r",
        "hash": "h",
        "style": _style().model_dump(),
        "arms": arms,
    }
    result = summarise([row])
    sprout = result["arms"]["sprout"]  # type: ignore[index]
    assert sprout["style"] == 1.0  # type: ignore[index]
    assert sprout["rouge_l"] == 1.0  # type: ignore[index]
    assert result["arms"]["diff_only"]["restates"] == 1.0  # type: ignore[index]
    assert result["paired"]["style"]["mean"] == 0.75  # type: ignore[index]
