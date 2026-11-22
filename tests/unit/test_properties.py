"""Property-based tests: random working trees never confuse status or diff."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pygit2
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from sprout.core.git import open_repo
from sprout.models import ChangeKind

# Lowercase only, so names never collide on case-insensitive filesystems (macOS, Windows).
names = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-", min_size=1, max_size=12)
texts = st.text(
    alphabet=st.characters(codec="utf-8", exclude_categories=("Cs", "Cc")) | st.just("\n"),
    max_size=200,
)
trees = st.dictionaries(names.filter(lambda n: n not in {".git", "-"}), texts, max_size=8)


def _line_count(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(files=trees)
def test_status_and_staged_diff_match_written_files(files: dict[str, str]) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pygit2.init_repository(tmp, initial_head="main")
        for name, text in files.items():
            (root / name).write_bytes(text.encode("utf-8"))

        repo = open_repo(root)
        assert sorted(repo.status().untracked) == sorted(files)

        index = pygit2.Repository(tmp).index
        index.add_all()
        index.write()

        diff = repo.diff(staged=True)
        assert {f.path for f in diff.files} == set(files)
        for file in diff.files:
            assert file.kind is ChangeKind.ADDED
            assert file.additions == _line_count(files[file.path])
            assert file.deletions == 0
