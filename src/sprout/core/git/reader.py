"""Read one commit into a ``CommitRecord``: files, hunks, symbols and message signals."""

from __future__ import annotations

import re
from dataclasses import dataclass

import pygit2

from sprout.core.code.languages import spec_for_path
from sprout.core.code.symbols import Definition, blank_rows, definitions, symbols_for_lines
from sprout.core.git.convert import DELTA_KINDS, EMPTY_TREE, commit_model
from sprout.core.git.message import parse_message
from sprout.models import ChangedFile, ChangedLine, ChangeKind, CommitRecord, Hunk, MessageInfo

MAX_FILES = 300  # vendored imports and mass renames are cut here
MAX_TERMS = 400
_IDENTIFIER = re.compile(rb"[A-Za-z_][A-Za-z0-9_]{2,63}")


def read_commit(repo: pygit2.Repository, commit: pygit2.Commit) -> CommitRecord:
    """Diff ``commit`` against its first parent (merges are recorded without a diff)."""
    model = commit_model(commit)
    is_merge = len(commit.parent_ids) > 1
    info = _resolve_reverts(repo, parse_message(model.message, is_merge=is_merge))
    if is_merge:
        return CommitRecord(
            commit=model, message_info=info, files=[], files_truncated=False, code_terms=[]
        )
    diff = _base_tree(repo, commit).diff_to_tree(commit.tree, context_lines=0, interhunk_lines=0)
    diff.find_similar()
    patches = [p for p in diff if p is not None]
    terms: dict[str, None] = {}
    files = [_changed_file(repo, patch, terms) for patch in patches[:MAX_FILES]]
    return CommitRecord(
        commit=model,
        message_info=info,
        files=files,
        files_truncated=len(patches) > MAX_FILES,
        code_terms=list(terms)[:MAX_TERMS],
    )


def commit_lines(repo: pygit2.Repository, commit: pygit2.Commit, limit: int) -> list[ChangedLine]:
    """Added and removed lines of ``commit`` against its first parent (none for merges)."""
    if len(commit.parent_ids) > 1:
        return []
    diff = _base_tree(repo, commit).diff_to_tree(commit.tree, context_lines=0, interhunk_lines=0)
    return diff_lines(diff, limit)


def diff_lines(diff: pygit2.Diff, limit: int) -> list[ChangedLine]:
    """Added and removed lines of ``diff``, skipping binary files, at most ``limit`` of them."""
    diff.find_similar()
    out: list[ChangedLine] = []
    for patch in diff:
        if patch is None or patch.delta.is_binary:
            continue
        new_path, old_path = patch.delta.new_file.path, patch.delta.old_file.path
        for hunk in patch.hunks:
            for line in hunk.lines:
                if line.origin not in "+-":
                    continue
                added = line.origin == "+"
                out.append(
                    ChangedLine(
                        path=new_path if added else old_path,
                        added=added,
                        text=line.content.rstrip("\r\n"),
                        line=max(line.new_lineno if added else line.old_lineno, 0),
                    )
                )
                if len(out) >= limit:
                    return out
    return out


def commit_patch(repo: pygit2.Repository, commit: pygit2.Commit, max_chars: int) -> str:
    """The commit's unified diff (3 lines of context), cut to ``max_chars``."""
    if len(commit.parent_ids) > 1:
        return ""
    diff = _base_tree(repo, commit).diff_to_tree(commit.tree)
    diff.find_similar()
    text = diff.patch or ""
    return text if len(text) <= max_chars else text[:max_chars] + "\n[diff truncated]\n"


def file_patch(repo: pygit2.Repository, commit: pygit2.Commit, path: str, max_chars: int) -> str:
    """The part of ``commit``'s diff that touches ``path`` (new or old name)."""
    if len(commit.parent_ids) > 1:
        return ""
    diff = _base_tree(repo, commit).diff_to_tree(commit.tree)
    diff.find_similar()
    for patch in diff:
        if patch is None:
            continue
        if path in (patch.delta.new_file.path, patch.delta.old_file.path):
            text = patch.data.decode("utf-8", errors="replace")
            return text if len(text) <= max_chars else text[:max_chars] + "\n[diff truncated]\n"
    return ""


def _base_tree(repo: pygit2.Repository, commit: pygit2.Commit) -> pygit2.Tree:
    """First parent's tree, or the empty tree for a root commit."""
    if commit.parents:
        return commit.parents[0].tree
    tree = repo.get(EMPTY_TREE)
    if not isinstance(tree, pygit2.Tree):  # pragma: no cover - libgit2 always resolves it
        raise TypeError("libgit2 did not resolve the empty tree")
    return tree


def _resolve_reverts(repo: pygit2.Repository, info: MessageInfo) -> MessageInfo:
    """Expand abbreviated reverted hashes to full ones when the object exists."""
    full: list[str] = []
    for short in info.reverts:
        try:
            full.append(str(repo.revparse_single(short).id))
        except (KeyError, ValueError, pygit2.GitError):
            full.append(short)
    return info.model_copy(update={"reverts": full})


def _changed_file(
    repo: pygit2.Repository, patch: pygit2.Patch, terms: dict[str, None]
) -> ChangedFile:
    delta = patch.delta
    kind = DELTA_KINDS.get(delta.status, ChangeKind.MODIFIED)
    binary = bool(delta.is_binary)
    _, additions, deletions = patch.line_stats
    old = _Side.load(repo, delta.old_file, binary)
    new = _Side.load(repo, delta.new_file, binary)
    hunks: list[Hunk] = []
    for hunk in patch.hunks:
        symbols = new.symbols(hunk.new_start, hunk.new_lines) if hunk.new_lines else []
        if hunk.old_lines:
            symbols += old.symbols(hunk.old_start, hunk.old_lines)
        hunks.append(
            Hunk(
                old_start=hunk.old_start,
                old_lines=hunk.old_lines,
                new_start=hunk.new_start,
                new_lines=hunk.new_lines,
                symbols=list(dict.fromkeys(symbols)),
            )
        )
        if len(terms) < MAX_TERMS:
            for line in hunk.lines:
                for match in _IDENTIFIER.findall(line.raw_content):
                    terms.setdefault(match.decode("ascii"), None)
    moved = kind in (ChangeKind.RENAMED, ChangeKind.COPIED)
    return ChangedFile(
        path=delta.new_file.path,
        old_path=delta.old_file.path if moved else None,
        kind=kind,
        additions=additions,
        deletions=deletions,
        binary=binary,
        hunks=hunks,
    )


@dataclass(frozen=True)
class _Side:
    """Definitions and blank rows of one side (old or new) of a file diff."""

    defs: list[Definition]
    blank: frozenset[int]

    @classmethod
    def load(cls, repo: pygit2.Repository, file: pygit2.DiffFile, binary: bool) -> _Side:
        if binary or spec_for_path(file.path) is None:
            return cls([], frozenset())
        source = _blob(repo, file.id)
        return cls(definitions(file.path, source), blank_rows(source))

    def symbols(self, start: int, count: int) -> list[str]:
        return symbols_for_lines(self.defs, start, count, self.blank) if self.defs else []


def _blob(repo: pygit2.Repository, oid: pygit2.Oid) -> bytes:
    """Blob contents, or ``b""`` for the all-zero id of an added or deleted side."""
    try:
        obj = repo[oid]
    except (KeyError, ValueError):
        return b""
    return obj.data if isinstance(obj, pygit2.Blob) else b""
