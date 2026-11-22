"""Convert pygit2 objects into Sprout models."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pygit2
from pygit2.enums import DeltaStatus

from sprout.models import ChangeKind, Commit, Person

# libgit2 resolves the well-known empty tree without it existing in the object database.
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

DELTA_KINDS: dict[DeltaStatus, ChangeKind] = {
    DeltaStatus.ADDED: ChangeKind.ADDED,
    DeltaStatus.DELETED: ChangeKind.DELETED,
    DeltaStatus.MODIFIED: ChangeKind.MODIFIED,
    DeltaStatus.RENAMED: ChangeKind.RENAMED,
    DeltaStatus.COPIED: ChangeKind.COPIED,
    DeltaStatus.TYPECHANGE: ChangeKind.TYPE_CHANGED,
    DeltaStatus.UNTRACKED: ChangeKind.UNTRACKED,
    DeltaStatus.CONFLICTED: ChangeKind.CONFLICTED,
}


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


def commit_model(commit: pygit2.Commit) -> Commit:
    """Build a ``Commit`` model, decoding text with the commit's declared encoding."""
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
