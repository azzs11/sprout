"""``GitRepo`` implementation backed by pygit2 (libgit2)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pygit2
from pygit2.enums import DeltaStatus, FileStatus, SortMode

from sprout.errors import (
    BareRepositoryError,
    NotARepositoryError,
    PathOutsideRepositoryError,
    RevisionNotFoundError,
)
from sprout.models import (
    ChangeKind,
    Commit,
    Diff,
    FileChange,
    FileDiff,
    History,
    Person,
    RepoStatus,
)

# libgit2 resolves the well-known empty tree without it existing in the object database.
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

_STAGED_FLAGS: dict[FileStatus, ChangeKind] = {
    FileStatus.INDEX_NEW: ChangeKind.ADDED,
    FileStatus.INDEX_MODIFIED: ChangeKind.MODIFIED,
    FileStatus.INDEX_DELETED: ChangeKind.DELETED,
    FileStatus.INDEX_RENAMED: ChangeKind.RENAMED,
    FileStatus.INDEX_TYPECHANGE: ChangeKind.TYPE_CHANGED,
}

_UNSTAGED_FLAGS: dict[FileStatus, ChangeKind] = {
    FileStatus.WT_MODIFIED: ChangeKind.MODIFIED,
    FileStatus.WT_DELETED: ChangeKind.DELETED,
    FileStatus.WT_RENAMED: ChangeKind.RENAMED,
    FileStatus.WT_TYPECHANGE: ChangeKind.TYPE_CHANGED,
}

_DELTA_KINDS: dict[DeltaStatus, ChangeKind] = {
    DeltaStatus.ADDED: ChangeKind.ADDED,
    DeltaStatus.DELETED: ChangeKind.DELETED,
    DeltaStatus.MODIFIED: ChangeKind.MODIFIED,
    DeltaStatus.RENAMED: ChangeKind.RENAMED,
    DeltaStatus.COPIED: ChangeKind.COPIED,
    DeltaStatus.TYPECHANGE: ChangeKind.TYPE_CHANGED,
    DeltaStatus.UNTRACKED: ChangeKind.UNTRACKED,
    DeltaStatus.CONFLICTED: ChangeKind.CONFLICTED,
}


def open_repo(path: Path | str = ".") -> Pygit2Repo:
    """Open the repository containing ``path`` (searching parent directories).

    Raises:
        NotARepositoryError: If no repository is found.
    """
    start = Path(path).resolve()
    found = pygit2.discover_repository(str(start))
    if found is None:
        raise NotARepositoryError(str(start))
    return Pygit2Repo(pygit2.Repository(found))


class Pygit2Repo:
    """Read-only view of a repository through pygit2."""

    def __init__(self, repo: pygit2.Repository) -> None:
        self._repo = repo

    @property
    def root(self) -> Path:
        """Absolute path of the working tree (or the git dir for bare repositories)."""
        workdir = self._repo.workdir
        return Path(workdir if workdir else self._repo.path).resolve()

    def relative_path(self, path: Path) -> str:
        """Convert a filesystem path to a POSIX path relative to the root."""
        absolute = path if path.is_absolute() else Path.cwd() / path
        try:
            return absolute.resolve().relative_to(self.root).as_posix()
        except ValueError:
            raise PathOutsideRepositoryError(str(path), str(self.root)) from None

    # ----- status ---------------------------------------------------------------

    def status(self) -> RepoStatus:
        """Return branch, HEAD and working-tree changes. Works before the first commit."""
        self._require_worktree()
        staged: list[FileChange] = []
        unstaged: list[FileChange] = []
        untracked: list[str] = []
        conflicted: list[str] = []
        for path, flags in sorted(self._repo.status().items()):
            if flags & FileStatus.CONFLICTED:
                conflicted.append(path)
                continue
            if flags & FileStatus.WT_NEW:
                untracked.append(path)
            staged.extend(_changes(path, flags, _STAGED_FLAGS))
            unstaged.extend(_changes(path, flags, _UNSTAGED_FLAGS))
        unborn = self._repo.head_is_unborn
        detached = not unborn and self._repo.head_is_detached
        return RepoStatus(
            root=str(self.root),
            branch=None if detached else self._branch_name(),
            head=None if unborn else str(self._repo.head.target),
            detached=detached,
            unborn=unborn,
            staged=staged,
            unstaged=unstaged,
            untracked=untracked,
            conflicted=conflicted,
        )

    def _branch_name(self) -> str:
        target = self._repo.references["HEAD"].target
        return str(target).removeprefix("refs/heads/")

    # ----- diff -----------------------------------------------------------------

    def diff(self, *, staged: bool) -> Diff:
        """Return staged changes (index vs HEAD) or unstaged ones (worktree vs index)."""
        self._require_worktree()
        index = self._repo.index
        index.read(False)  # pick up changes another process (e.g. `git add`) wrote to disk
        raw = index.diff_to_tree(self._head_tree()) if staged else index.diff_to_workdir()
        raw.find_similar()
        return Diff(staged=staged, files=[_file_diff(patch) for patch in raw if patch is not None])

    def _head_tree(self) -> pygit2.Tree:
        if not self._repo.head_is_unborn:
            return self._repo.head.peel(pygit2.Tree)
        tree = self._repo.get(EMPTY_TREE)
        if not isinstance(tree, pygit2.Tree):  # pragma: no cover - libgit2 always resolves it
            raise TypeError("libgit2 did not resolve the empty tree")
        return tree

    # ----- history --------------------------------------------------------------

    def history(
        self,
        *,
        limit: int | None = None,
        rev: str | None = None,
        path: str | None = None,
    ) -> History:
        """Return commits reachable from ``rev`` (default HEAD), newest first."""
        start = self._resolve(rev)
        if start is None:
            return History(commits=[], path=path)
        commits: list[Commit] = []
        for commit in self._walk(start, path):
            if limit is not None and len(commits) >= limit:
                break
            commits.append(_commit_model(commit))
        return History(commits=commits, path=path)

    def _resolve(self, rev: str | None) -> pygit2.Commit | None:
        if rev is None:
            if self._repo.head_is_unborn:
                return None
            return self._repo.head.peel(pygit2.Commit)
        try:
            obj = self._repo.revparse_single(rev)
            return obj.peel(pygit2.Commit)
        except (KeyError, ValueError, pygit2.InvalidSpecError, pygit2.GitError):
            raise RevisionNotFoundError(rev) from None

    def _walk(self, start: pygit2.Commit, path: str | None) -> Iterator[pygit2.Commit]:
        for commit in self._repo.walk(start.id, SortMode.TIME):
            if path is None or _touches(commit, path):
                yield commit

    def _require_worktree(self) -> None:
        if self._repo.is_bare:
            raise BareRepositoryError(str(self.root))


def _changes(path: str, flags: int, table: dict[FileStatus, ChangeKind]) -> list[FileChange]:
    return [FileChange(path=path, kind=kind) for flag, kind in table.items() if flags & flag]


def _file_diff(patch: pygit2.Patch) -> FileDiff:
    delta = patch.delta
    _, additions, deletions = patch.line_stats
    kind = _DELTA_KINDS.get(DeltaStatus(delta.status), ChangeKind.MODIFIED)
    old_path = delta.old_file.path
    moved = kind in (ChangeKind.RENAMED, ChangeKind.COPIED)
    return FileDiff(
        path=delta.new_file.path,
        old_path=old_path if moved else None,
        kind=kind,
        additions=additions,
        deletions=deletions,
        binary=bool(delta.is_binary),
        patch=patch.data.decode("utf-8", errors="replace"),
    )


def _entry_id(tree: pygit2.Tree, path: str) -> pygit2.Oid | None:
    try:
        return tree[path].id
    except KeyError:
        return None


def _touches(commit: pygit2.Commit, path: str) -> bool:
    """Match ``git log -- <path>``: keep commits whose path differs from every parent."""
    current = _entry_id(commit.tree, path)
    if not commit.parents:
        return current is not None
    return all(_entry_id(parent.tree, path) != current for parent in commit.parents)


def _decode(raw: bytes, encoding: str | None) -> str:
    try:
        return raw.decode(encoding or "utf-8")
    except (LookupError, UnicodeDecodeError):
        return raw.decode("utf-8", errors="replace")


def _person(sig: pygit2.Signature, encoding: str | None) -> Person:
    return Person(name=_decode(sig.raw_name, encoding), email=_decode(sig.raw_email, encoding))


def _when(sig: pygit2.Signature) -> datetime:
    tz = timezone(timedelta(minutes=sig.offset))
    return datetime.fromtimestamp(sig.time, tz=UTC).astimezone(tz)


def _commit_model(commit: pygit2.Commit) -> Commit:
    encoding = commit.message_encoding
    message = _decode(commit.raw_message, encoding)
    hash_ = str(commit.id)
    return Commit(
        hash=hash_,
        short_hash=hash_[:7],
        author=_person(commit.author, encoding),
        authored_at=_when(commit.author),
        committer=_person(commit.committer, encoding),
        committed_at=_when(commit.committer),
        summary=message.split("\n", 1)[0].strip(),
        message=message,
        parents=[str(p) for p in commit.parent_ids],
    )
