"""Tests for reading commits into index records."""

from __future__ import annotations

from collections.abc import Callable

from sprout.core.git import open_repo
from sprout.models import ChangeKind, Label
from tests.fixtures.builder import RepoBuilder

MakeRepo = Callable[[str], RepoBuilder]


def _records(built: RepoBuilder):  # newest first
    repo = open_repo(built.root)
    return [repo.read_commit(h) for h in repo.walk_hashes()]


def test_root_commit_diffs_against_empty_tree(make_repo: MakeRepo) -> None:
    root = _records(make_repo("payments"))[-1]
    (file,) = root.files
    assert (file.path, file.kind, file.deletions) == ("src/payments.py", ChangeKind.ADDED, 0)
    assert file.symbols == ["PaymentClient", "PaymentClient.charge", "PaymentClient._send"]


def test_hunk_symbols_point_at_the_changed_definition(make_repo: MakeRepo) -> None:
    records = {r.commit.summary: r for r in _records(make_repo("payments"))}
    perf = records["perf(payments): disable charge retries to cut latency"]
    assert perf.files[0].symbols == ["PaymentClient"]
    fix = records["fix(auth): reject empty tokens in verify_token (#42)"]
    assert fix.files[0].symbols == ["verify_token"]
    assert fix.message_info.refs[0].number == 42
    assert fix.message_info.refs[0].closes


def test_revert_target_is_resolved_to_full_hash(make_repo: MakeRepo) -> None:
    records = _records(make_repo("payments"))
    by_summary = {r.commit.summary: r for r in records}
    revert = by_summary['Revert "perf(payments): disable charge retries to cut latency"']
    target = by_summary["perf(payments): disable charge retries to cut latency"]
    assert revert.message_info.reverts == [target.commit.hash]
    assert Label.REVERT in revert.message_info.labels


def test_code_terms_include_changed_identifiers(make_repo: MakeRepo) -> None:
    newest = _records(make_repo("payments"))[0]
    assert "compare_digest" in newest.code_terms
    assert "hmac" in newest.code_terms


def test_merge_commits_have_no_files(make_repo: MakeRepo) -> None:
    merge = _records(make_repo("merge"))[0]
    assert Label.MERGE in merge.message_info.labels
    assert merge.files == []


def test_rename_is_recorded(make_repo: MakeRepo) -> None:
    records = {r.commit.summary: r for r in _records(make_repo("renames"))}
    (moved,) = records["refactor: move name.py to new/place.py"].files
    assert (moved.kind, moved.old_path, moved.path) == (
        ChangeKind.RENAMED,
        "old/name.py",
        "new/place.py",
    )


def test_binary_files_have_no_hunks(make_repo: MakeRepo) -> None:
    (file,) = _records(make_repo("binary"))[0].files
    assert file.binary
    assert file.hunks == []


def test_commit_patch_is_truncated(make_repo: MakeRepo) -> None:
    built = make_repo("payments")
    repo = open_repo(built.root)
    first = list(repo.walk_hashes())[-1]
    assert "class PaymentClient" in repo.commit_patch(first)
    assert repo.commit_patch(first, max_chars=40).endswith("[diff truncated]\n")


def test_walk_since_stops_at_older_commits(make_repo: MakeRepo) -> None:
    built = make_repo("linear")
    repo = open_repo(built.root)
    all_hashes = list(repo.walk_hashes())
    newest_time = repo.read_commit(all_hashes[0]).commit.committed_at.timestamp()
    assert list(repo.walk_hashes(since=int(newest_time))) == all_hashes[:1]


def test_has_commit(make_repo: MakeRepo) -> None:
    built = make_repo("linear")
    repo = open_repo(built.root)
    assert repo.has_commit(built.head())
    assert not repo.has_commit("0" * 40)
    assert not repo.has_commit("not-a-hash")
