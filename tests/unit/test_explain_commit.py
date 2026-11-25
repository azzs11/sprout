"""``explain_commit``: revert links, stated reasons and redacted, cut diffs."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from sprout.core.answer.commit import explain_commit
from sprout.core.git import open_repo
from sprout.core.index.indexer import build_index
from sprout.core.index.store import Store
from sprout.errors import RevisionNotFoundError
from tests.fixtures.builder import RepoBuilder

MakeRepo = Callable[[str], RepoBuilder]
GITHUB_TOKEN = "ghp_" + "a" * 36


def _indexed(repo: RepoBuilder) -> Store:
    store = Store.open(repo.root, create=True)
    build_index(open_repo(repo.root), store)
    return store


def test_links_a_revert_both_ways(make_repo: MakeRepo) -> None:
    repo = make_repo("revert")
    revert_hash, bad = repo.head(), repo.git("rev-parse", "HEAD~1").strip()
    git = open_repo(repo.root)
    with _indexed(repo) as store:
        reverting = explain_commit(git, store, revert_hash[:8])
        reverted = explain_commit(git, store, bad)
    assert reverting.reverts == [bad]
    assert reverted.reverted_by == [revert_hash]
    assert reverted.indexed
    assert [f.path for f in reverted.files] == ["retry.py"]
    assert "-RETRIES = 3" in reverted.patch


def test_without_an_index_reverts_still_come_from_the_message(make_repo: MakeRepo) -> None:
    repo = make_repo("revert")
    ex = explain_commit(open_repo(repo.root), None, "HEAD")
    assert ex.reverts == [repo.git("rev-parse", "HEAD~1").strip()]
    assert ex.reverted_by == []
    assert not ex.indexed


def test_quotes_the_stated_reason(make_repo: MakeRepo) -> None:
    repo = make_repo("lineage")
    ex = explain_commit(open_repo(repo.root), None, "HEAD~1")
    assert ex.reason is not None
    assert ex.reason.startswith("We raised the limit because the card network times out")
    assert ex.files[0].symbols == ["charge"]


def test_redacts_before_cutting_the_diff(make_repo: MakeRepo) -> None:
    repo = make_repo("empty")
    repo.write("config.py", "x = 1\n").commit("feat: config")
    repo.write("config.py", f"x = 1\ncall('{GITHUB_TOKEN}')\n").commit("feat: add token")
    git = open_repo(repo.root)
    full = explain_commit(git, None, "HEAD")
    assert full.redacted == 1
    assert GITHUB_TOKEN not in full.patch
    cut_at = full.patch.index("[REDACTED") + 8  # the cut lands inside the secret
    ex = explain_commit(git, None, "HEAD", max_patch=cut_at)
    assert ex.patch_truncated
    assert "ghp_" not in ex.patch


def test_unknown_revision(make_repo: MakeRepo) -> None:
    repo = make_repo("linear")
    with pytest.raises(RevisionNotFoundError):
        explain_commit(open_repo(repo.root), None, "nope123")


def test_an_issue_link_is_not_a_reason(make_repo: MakeRepo) -> None:
    repo = make_repo("payments")
    ex = explain_commit(open_repo(repo.root), None, "HEAD~1")  # body is only "Fixes #42."
    assert ex.commit.message.strip().endswith("Fixes #42.")
    assert ex.reason is None
    assert [r.number for r in ex.refs] == [42]


def test_revert_by_quoted_subject_needs_the_index(make_repo: MakeRepo) -> None:
    repo = make_repo("empty")
    repo.write("a.py", "A = 1\n").commit("feat: add a")
    original = repo.write("a.py", "A = 2\n").commit("perf: make a faster")
    repo.write("a.py", "A = 1\n").commit('Revert "perf: make a faster"')
    git = open_repo(repo.root)
    assert explain_commit(git, None, "HEAD").reverts == []
    with _indexed(repo) as store:
        assert explain_commit(git, store, "HEAD").reverts == [original]


def test_reverted_hash_missing_from_the_clone_is_kept_as_written(make_repo: MakeRepo) -> None:
    repo = make_repo("linear")
    repo.write("b.py", "B = 1\n").commit(
        "Revert a lost change\n\nThis reverts commit 0123456789abcdef."
    )
    assert explain_commit(open_repo(repo.root), None, "HEAD").reverts == ["0123456789abcdef"]
