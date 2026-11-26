"""``sprout-hook prepare-commit-msg``: draft the message in the editor of the author's own commit.

Git runs it as ``prepare-commit-msg <file> [<source> [<sha>]]``. Sprout fills the file only for
a plain ``git commit`` (no source) whose message is still empty. ``-m``/``-F``, templates,
merges, squashes and amends already have a message and are left alone. The why question is
written as a comment, which git removes, so a message left unanswered gets no ``Why:`` line.
The model gets ``SPROUT_COMMIT_TIMEOUT`` seconds (default 30); after that the skeleton is used.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from collections.abc import Sequence
from pathlib import Path

from sprout import services
from sprout.config import load_settings
from sprout.core.commit.message import draft_message
from sprout.core.git import open_repo
from sprout.core.git.pygit2_repo import Pygit2Repo
from sprout.errors import NothingStagedError
from sprout.models import CommitDraft, DraftSource

DEFAULT_TIMEOUT = 30.0


def prepare_commit_msg(cwd: Path, args: Sequence[str]) -> int:
    """Write a draft into git's message file. Always exits 0: a hook never stops a commit."""
    # The pre-commit framework passes only the file and puts the source in its environment.
    source = args[1] if len(args) > 1 else os.environ.get("PRE_COMMIT_COMMIT_MSG_SOURCE", "")
    if not args or source:
        return 0  # a message source: -m, -F, template, merge, squash or amend
    path = Path(args[0])
    existing = path.read_text(encoding="utf-8", errors="replace")
    comment = comment_char(cwd)
    if has_message(existing, comment or "#"):
        return 0
    git = open_repo(cwd)
    try:
        draft = _draft(git)
    except NothingStagedError:
        return 0
    path.write_text(render(draft, comment) + existing, encoding="utf-8", newline="\n")
    print("sprout: drafted the message; edit it and answer the why question.", file=sys.stderr)
    return 0


def comment_char(cwd: Path) -> str | None:
    """Git's comment character: '#' unless configured; None for 'auto' (no comments added)."""
    done = subprocess.run(
        ["git", "config", "--get", "core.commentChar"],  # noqa: S607
        cwd=cwd, capture_output=True, text=True, check=False,
    )  # fmt: skip
    value = done.stdout.strip()
    if value == "auto":
        return None
    return value or "#"


def has_message(text: str, comment: str) -> bool:
    """True when any line is neither blank nor a comment."""
    return any(line.strip() and not line.startswith(comment) for line in text.splitlines())


def render(draft: CommitDraft, comment: str | None) -> str:
    """The draft, with the why question as a comment where a ``Why:`` line belongs."""
    if comment is None:
        return draft.message + "\n"
    paragraphs = draft.message.rstrip("\n").split("\n\n")
    has_trailers = bool(draft.trailers)
    head = paragraphs[:-1] if has_trailers else paragraphs
    ask = [f"{comment} {draft.question}", f'{comment} Answer on a line "Why: <reason>" here.']
    block = [*ask, paragraphs[-1]] if has_trailers else ask
    source = (
        draft.model.split("|")[0]
        if draft.source is DraftSource.MODEL and draft.model
        else ("no model, edit the subject")
    )
    notes = [f"{comment} Drafted by Sprout ({source}). SPROUT_SKIP=1 git commit skips it."]
    notes += [f"{comment} {n}" for n in draft.notes]
    return "\n\n".join([*head, "\n".join(block)]) + "\n" + "\n".join(notes) + "\n"


def _draft(git: Pygit2Repo) -> CommitDraft:
    """A model draft if it arrives within the timeout, else the skeleton."""
    diff = git.diff(staged=True)
    writer, note = services.build_commit_writer(load_settings(git.root))
    if writer is None:
        draft = draft_message(git, diff)
        return draft.model_copy(update={"notes": [*draft.notes, *([note] if note else [])]})
    result: list[CommitDraft] = []
    failed: list[str] = []

    def work() -> None:
        try:  # its own repository object: libgit2 objects are not shared across threads
            result.append(draft_message(open_repo(git.root), diff, writer=writer))
        except Exception as exc:
            failed.append(f"The model draft failed ({type(exc).__name__}), so this is a skeleton.")

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(_timeout())
    if result:
        return result[0]
    draft = draft_message(git, diff)
    late = failed or [f"The model took longer than {_timeout():g} s, so this is a skeleton."]
    return draft.model_copy(update={"notes": [*draft.notes, *late]})


def _timeout() -> float:
    try:
        return max(1.0, float(os.environ.get("SPROUT_COMMIT_TIMEOUT", DEFAULT_TIMEOUT)))
    except ValueError:
        return DEFAULT_TIMEOUT
