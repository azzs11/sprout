"""Tests for the pygit2 ``GitRepo`` implementation, one fixture scenario at a time."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pygit2
import pytest

from sprout.core.git import open_repo
from sprout.errors import (
    BareRepositoryError,
    NotARepositoryError,
    PathOutsideRepositoryError,
    RevisionNotFoundError,
)
from sprout.models import ChangeKind
from tests.fixtures.builder import RepoBuilder

MakeRepo = Callable[[str], RepoBuilder]


# ----- opening ----------------------------------------------------------------------


def test_open_outside_a_repository_raises_with_hint(tmp_path: Path) -> None:
    with pytest.raises(NotARepositoryError) as info:
        open_repo(tmp_path)
    assert info.value.hint is not None
    assert "git init" in info.value.hint


def test_open_from_a_subdirectory_finds_the_root(make_repo: MakeRepo) -> None:
    built = make_repo("renames")
    repo = open_repo(built.root / "new")
    assert repo.root == built.root.resolve()


# ----- empty / unborn repositories (the old no-HEAD crash) --------------------------


def test_status_in_empty_repo_does_not_crash(make_repo: MakeRepo) -> None:
    status = open_repo(make_repo("empty").root).status()
    assert status.unborn
    assert status.head is None
    assert status.branch == "main"
    assert status.clean


def test_history_in_empty_repo_is_empty(make_repo: MakeRepo) -> None:
    assert open_repo(make_repo("empty").root).history().commits == []


def test_diffs_in_empty_repo_are_empty(make_repo: MakeRepo) -> None:
    repo = open_repo(make_repo("empty").root)
    assert repo.diff(staged=True).files == []
    assert repo.diff(staged=False).files == []


def test_unborn_repo_reports_staged_and_untracked_files(make_repo: MakeRepo) -> None:
    status = open_repo(make_repo("unborn_with_changes").root).status()
    assert [(c.path, c.kind) for c in status.staged] == [("staged.txt", ChangeKind.ADDED)]
    assert status.untracked == ["untracked.txt"]
    assert not status.clean


def test_staged_diff_before_first_commit_compares_to_empty_tree(make_repo: MakeRepo) -> None:
    diff = open_repo(make_repo("unborn_with_changes").root).diff(staged=True)
    assert [(f.path, f.kind, f.additions) for f in diff.files] == [
        ("staged.txt", ChangeKind.ADDED, 1)
    ]


# ----- linear history ---------------------------------------------------------------


def test_history_is_newest_first(make_repo: MakeRepo) -> None:
    history = open_repo(make_repo("linear").root).history()
    assert [c.summary for c in history.commits] == [
        "fix: return 2 from main",
        "docs: add readme",
        "feat: add app",
    ]


def test_history_limit(make_repo: MakeRepo) -> None:
    history = open_repo(make_repo("linear").root).history(limit=1)
    assert len(history.commits) == 1


def test_history_path_filter(make_repo: MakeRepo) -> None:
    history = open_repo(make_repo("linear").root).history(path="app.py")
    assert [c.summary for c in history.commits] == ["fix: return 2 from main", "feat: add app"]


def test_history_from_rev(make_repo: MakeRepo) -> None:
    history = open_repo(make_repo("linear").root).history(rev="HEAD~1")
    assert history.commits[0].summary == "docs: add readme"


def test_unknown_rev_raises(make_repo: MakeRepo) -> None:
    with pytest.raises(RevisionNotFoundError):
        open_repo(make_repo("linear").root).history(rev="no-such-branch")


def test_commit_fields(make_repo: MakeRepo) -> None:
    built = make_repo("linear")
    commit = open_repo(built.root).history(limit=1).commits[0]
    assert commit.hash == built.head()
    assert commit.short_hash == commit.hash[:7]
    assert commit.author.name == "Ada Lovelace"
    assert commit.authored_at.tzinfo is not None
    assert len(commit.parents) == 1


def test_clean_after_commit(make_repo: MakeRepo) -> None:
    status = open_repo(make_repo("linear").root).status()
    assert status.clean
    assert not status.unborn


def test_unstaged_and_staged_modifications(make_repo: MakeRepo) -> None:
    built = make_repo("linear")
    built.write("app.py", "def main():\n    return 3\n").stage("app.py")
    built.write("README.md", "# changed\n")
    repo = open_repo(built.root)
    status = repo.status()
    assert [c.path for c in status.staged] == ["app.py"]
    assert [c.path for c in status.unstaged] == ["README.md"]
    staged = repo.diff(staged=True)
    assert (staged.additions, staged.deletions) == (1, 1)
    assert "+    return 3" in staged.files[0].patch


def test_deleted_file_is_reported(make_repo: MakeRepo) -> None:
    built = make_repo("linear")
    built.remove("README.md")
    status = open_repo(built.root).status()
    assert [(c.path, c.kind) for c in status.unstaged] == [("README.md", ChangeKind.DELETED)]


def test_detached_head(make_repo: MakeRepo) -> None:
    built = make_repo("linear")
    built.git("checkout", "--quiet", "--detach", "HEAD~1")
    status = open_repo(built.root).status()
    assert status.detached
    assert status.branch is None
    assert status.head is not None


# ----- renames ----------------------------------------------------------------------


def test_staged_rename_is_detected(make_repo: MakeRepo) -> None:
    built = make_repo("renames")
    built.move("new/place.py", "final/spot.py")
    diff = open_repo(built.root).diff(staged=True)
    assert [(f.kind, f.old_path, f.path) for f in diff.files] == [
        (ChangeKind.RENAMED, "new/place.py", "final/spot.py")
    ]


def test_history_of_renamed_path_starts_at_rename(make_repo: MakeRepo) -> None:
    history = open_repo(make_repo("renames").root).history(path="new/place.py")
    assert [c.summary for c in history.commits] == [
        "fix: z is 4",
        "refactor: move name.py to new/place.py",
    ]


# ----- merges and reverts -----------------------------------------------------------


def test_merge_commit_has_two_parents(make_repo: MakeRepo) -> None:
    history = open_repo(make_repo("merge").root).history()
    merge_commit = history.commits[0]
    assert merge_commit.summary == "Merge branch 'feature'"
    assert len(merge_commit.parents) == 2
    assert len(history.commits) == 4


def test_merge_is_skipped_by_path_filter_when_treesame(make_repo: MakeRepo) -> None:
    history = open_repo(make_repo("merge").root).history(path="feature.py")
    assert [c.summary for c in history.commits] == ["feat: feature"]


def test_revert_appears_in_history(make_repo: MakeRepo) -> None:
    history = open_repo(make_repo("revert").root).history(path="retry.py")
    assert history.commits[0].summary == 'Revert "perf: disable retries"'
    assert len(history.commits) == 3


# ----- binary and encodings ---------------------------------------------------------


def test_binary_change_is_flagged(make_repo: MakeRepo) -> None:
    built = make_repo("binary")
    built.write("logo.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\x03")
    diff = open_repo(built.root).diff(staged=False)
    assert diff.files[0].binary
    assert diff.files[0].path == "logo.png"


def test_latin1_commit_message_is_decoded(make_repo: MakeRepo) -> None:
    commit = open_repo(make_repo("non_utf8").root).history().commits[0]
    assert commit.summary == "feat: add caf\xe9 menu"


def test_latin1_file_diff_does_not_crash(make_repo: MakeRepo) -> None:
    built = make_repo("non_utf8")
    built.write("menu.txt", "caf\xe9 cr\xe8me\n".encode("latin-1"))
    diff = open_repo(built.root).diff(staged=False)
    assert diff.files[0].additions == 1


# ----- bare repositories and paths --------------------------------------------------


def test_bare_repository_rejects_worktree_commands(make_repo: MakeRepo, tmp_path: Path) -> None:
    source = make_repo("linear")
    bare = tmp_path / "bare.git"
    pygit2.clone_repository(str(source.root), str(bare), bare=True)
    repo = open_repo(bare)
    with pytest.raises(BareRepositoryError):
        repo.status()
    assert len(repo.history().commits) == 3


def test_relative_path_outside_repo_raises(make_repo: MakeRepo, tmp_path: Path) -> None:
    repo = open_repo(make_repo("linear").root)
    with pytest.raises(PathOutsideRepositoryError):
        repo.relative_path(tmp_path)


def test_relative_path_is_posix(make_repo: MakeRepo) -> None:
    built = make_repo("renames")
    repo = open_repo(built.root)
    assert repo.relative_path(built.root / "new" / "place.py") == "new/place.py"
