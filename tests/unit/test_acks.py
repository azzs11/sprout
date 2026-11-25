"""``.sprout-acks.toml``: reading, writing, and hiding acknowledged findings."""

from __future__ import annotations

import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sprout.core.git import open_repo
from sprout.core.index.indexer import build_index
from sprout.core.index.store import Store
from sprout.core.risk import acks
from sprout.core.risk.check import check_changes
from sprout.errors import SproutError
from sprout.models import Ack, AckKind
from tests.fixtures.builder import RepoBuilder

MakeRepo = Callable[[str], RepoBuilder]


def entry(commit: str, date: str = "2026-11-25", reason: str = "no longer applies") -> Ack:
    return Ack(commit=commit, kind=AckKind.ACK, reason=reason, by="Ada", date=date)


@given(st.text(alphabet=st.characters(exclude_categories=("Cs",))))
def test_any_text_survives_a_toml_round_trip(text: str) -> None:
    assert tomllib.loads("k = " + acks.toml_string(text))["k"] == text


def test_save_and_load(tmp_path: Path) -> None:
    saved = [entry("b" * 40, "2026-02-01", 'says "why" 😀\x7f'), entry("a" * 40, "2026-01-01")]
    acks.save(tmp_path, saved)
    text = (tmp_path / acks.ACK_FILE).read_text()
    assert text.startswith("# Commits whose Sprout warnings no longer apply.")
    loaded = acks.load(tmp_path)
    assert [a.commit for a in loaded] == ["a" * 40, "b" * 40]  # sorted by date
    assert loaded[1].reason == 'says "why" 😀\x7f'
    acks.save(tmp_path, [])
    assert not (tmp_path / acks.ACK_FILE).exists()


def test_upsert_replaces_the_same_commit() -> None:
    first, again = entry("a" * 40, reason="one"), entry("a" * 40, reason="two")
    assert [a.reason for a in acks.upsert([first], again)] == ["two"]


def test_a_broken_file_is_an_error_but_hides_nothing(tmp_path: Path) -> None:
    (tmp_path / acks.ACK_FILE).write_text("[[ack]]\ncommit = \n")
    with pytest.raises(SproutError, match="could not be read"):
        acks.load(tmp_path)
    assert acks.ignored(tmp_path) == frozenset()
    (tmp_path / acks.ACK_FILE).write_text('[[ack]]\ncommit = "x"\n')  # missing fields
    with pytest.raises(SproutError):
        acks.load(tmp_path)


def test_check_changes_hides_ignored_commits(make_repo: MakeRepo) -> None:
    repo = make_repo("payments")
    path = repo.root / "src/payments.py"
    path.write_text(path.read_text().replace("RETRIES = 3", "RETRIES = 0"))
    changed = open_repo(repo.root).uncommitted_lines(staged_only=False)
    with Store.open(repo.root, create=True) as store:
        build_index(open_repo(repo.root), store)
        [finding] = check_changes(store, changed).findings
        card = check_changes(store, changed, ignore=frozenset({finding.commit.hash}))
    assert card.findings == []
    assert card.notes == ["1 finding hidden by .sprout-acks.toml."]
