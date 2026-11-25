"""``GitRepo`` implementation backed by pygit2 (libgit2)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pygit2
from pygit2.enums import DeltaStatus, FileStatus, ObjectType, SortMode

from sprout.core.git.convert import DELTA_KINDS, EMPTY_TREE, commit_model
from sprout.core.git.reader import commit_lines, commit_patch, diff_lines, file_patch, read_commit
from sprout.errors import (
    BareRepositoryError,
    NoCommitsError,
    NotARepositoryError,
    PathOutsideRepositoryError,
    RevisionNotFoundError,
)
from sprout.models import (
    ChangedLine,
    ChangeKind,
    Commit,
    CommitRecord,
    Diff,
    FileChange,
    FileDiff,
    History,
    RepoStatus,
)

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

    @property
    def is_bare(self) -> bool:
        """True for a repository with no working tree."""
        return bool(self._repo.is_bare)

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

    def uncommitted_lines(self, *, staged_only: bool, limit: int = 20_000) -> list[ChangedLine]:
        """Lines changed since HEAD: staged ones only, or everything in the working tree.

        Untracked files are not included (``git add -N`` makes them count).
        """
        self._require_worktree()
        if staged_only:
            index = self._repo.index
            index.read(False)
            raw = index.diff_to_tree(self._head_tree(), context_lines=0)
        else:
            raw = self._head_tree().diff_to_workdir(context_lines=0)
        return diff_lines(raw, limit)

    def commit_lines(self, hash_: str, *, limit: int = 2_000) -> list[ChangedLine]:
        """Added and removed lines of one commit, at most ``limit`` of them."""
        return commit_lines(self._repo, self._commit(hash_), limit)

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
            commits.append(commit_model(commit))
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

    # ----- indexing --------------------------------------------------------------

    @property
    def git_dir(self) -> Path:
        """Absolute path of the ``.git`` directory."""
        return Path(self._repo.path).resolve()

    @property
    def head_hash(self) -> str | None:
        """Full hash of HEAD, or None before the first commit."""
        return None if self._repo.head_is_unborn else str(self._repo.head.target)

    def walk_hashes(self, *, rev: str | None = None, since: int | None = None) -> Iterator[str]:
        """Hashes reachable from ``rev``, newest first, stopping at commit time ``since``."""
        start = self._resolve(rev)
        if start is None:
            return
        for commit in self._repo.walk(start.id, SortMode.TIME):
            if since is not None and commit.commit_time < since:
                return
            yield str(commit.id)

    def has_commit(self, hash_: str) -> bool:
        """True if the object database still contains this commit."""
        try:
            obj = self._repo.get(hash_)
        except ValueError:
            return False
        return obj is not None and obj.type == ObjectType.COMMIT

    def read_commit(self, hash_: str) -> CommitRecord:
        """Everything the history index stores about one commit."""
        return read_commit(self._repo, self._commit(hash_))

    def commit_patch(self, hash_: str, *, max_chars: int = 12_000) -> str:
        """Unified diff of one commit against its first parent, cut to ``max_chars``."""
        return commit_patch(self._repo, self._commit(hash_), max_chars)

    def resolve(self, rev: str | None = None) -> str:
        """Full hash of ``rev`` (default HEAD).

        Raises:
            NoCommitsError: If ``rev`` is None and the branch has no commits.
            RevisionNotFoundError: If ``rev`` does not exist.
        """
        commit = self._resolve(rev)
        if commit is None:
            raise NoCommitsError
        return str(commit.id)

    def commit(self, hash_: str) -> Commit:
        """One commit as a model."""
        return commit_model(self._commit(hash_))

    def read_file(self, rev: str, path: str) -> bytes | None:
        """File contents at ``rev``, or None if the path does not exist there."""
        tree = self._commit(rev).tree
        try:
            obj = tree[path]
        except KeyError:
            return None
        blob = self._repo.get(obj.id)
        return blob.data if isinstance(blob, pygit2.Blob) else None

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        """True if ``ancestor`` is ``descendant`` or reachable from it."""
        if ancestor == descendant:
            return True
        try:
            return self._repo.descendant_of(descendant, ancestor)
        except (KeyError, ValueError, pygit2.GitError):
            return False

    def file_patch(self, hash_: str, path: str, *, max_chars: int = 2_000) -> str:
        """The part of a commit's diff that touches ``path``, cut to ``max_chars``."""
        return file_patch(self._repo, self._commit(hash_), path, max_chars)

    def _commit(self, hash_: str) -> pygit2.Commit:
        try:
            return self._repo[hash_].peel(pygit2.Commit)
        except (KeyError, ValueError):
            raise RevisionNotFoundError(hash_) from None

    def _require_worktree(self) -> None:
        if self._repo.is_bare:
            raise BareRepositoryError(str(self.root))


def _changes(path: str, flags: int, table: dict[FileStatus, ChangeKind]) -> list[FileChange]:
    return [FileChange(path=path, kind=kind) for flag, kind in table.items() if flags & flag]


def _file_diff(patch: pygit2.Patch) -> FileDiff:
    delta = patch.delta
    _, additions, deletions = patch.line_stats
    kind = DELTA_KINDS.get(DeltaStatus(delta.status), ChangeKind.MODIFIED)
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
