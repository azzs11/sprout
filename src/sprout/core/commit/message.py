"""Draft a commit message for a staged diff: the *what* from the diff, the *why* from the author.

A model (when one is configured) writes the subject and body from the redacted diff, with
past commits to the same files as examples, and asks the author one question. It is told
never to state a reason; the author's answer is kept word for word in a ``Why:``
trailer. Without a model, a skeleton subject is guessed from the paths. Sprout never runs
``git commit``.
"""

from __future__ import annotations

import textwrap
from collections.abc import Sequence

from sprout.core.commit.style import is_authored, learn_style
from sprout.core.commit.subject import (
    format_subject,
    guess_scope,
    guess_type,
    skeleton_description,
)
from sprout.core.commit.trailers import build_trailers, find_reverted, format_trailers
from sprout.core.commit.writer import CommitWriter, Written, describe_style
from sprout.core.git.repo import GitRepo
from sprout.core.redact import redact
from sprout.errors import ModelError, NothingStagedError, SproutError
from sprout.models import (
    Commit,
    CommitDraft,
    CommitStyle,
    Diff,
    DraftSource,
    FileDiff,
    Trailer,
    TrailerSource,
)

EXAMPLES = 5
HISTORY_FILES = 5  # changed files whose history is read for examples
HISTORY_PER_FILE = 10
MAX_DIFF = 12_000  # characters of redacted diff shown to the model
WRAP = 72
DEFAULT_QUESTION = "Why is this change needed? One sentence in your own words is enough."
_TRUNCATED = "\n[diff truncated]\n"


def draft_message(
    repo: GitRepo,
    diff: Diff,
    *,
    style: CommitStyle | None = None,
    writer: CommitWriter | None = None,
    why: str | None = None,
    fixes: Sequence[int] = (),
) -> CommitDraft:
    """Draft a message for ``diff`` (normally the staged diff of ``repo``).

    Args:
        repo: The repository, for its style, history and branch.
        diff: The changes to describe.
        style: The repository's style, when already learned.
        writer: The model writer; None drafts a skeleton.
        why: The author's answer to the why question, kept word for word in ``Why:``.
        fixes: Issue numbers the author says this closes (``Fixes:``).

    Raises:
        NothingStagedError: ``diff`` has no files.
    """
    if not diff.files:
        raise NothingStagedError
    style = style or learn_style(repo)
    past = file_examples(repo, diff.files)
    examples = [c.summary.strip() for c in past]
    text, redacted, truncated = diff_text(diff)
    notes: list[str] = []
    written = _ask(writer, style, render_examples(past, style), text, notes)
    subject, body, question = _parts(written, style, diff.files, examples or style.examples)
    reverted = find_reverted(repo, diff.files) if diff.staged else None
    if reverted is not None:
        subject = f'Revert "{reverted.summary.strip()}"'
        notes.append(f"The staged diff undoes {reverted.short_hash}, so Reverts: was added.")
    elif written is None:
        notes.append("Written without a model: edit the subject before committing.")
    clean_why = " ".join(why.split()) if why and why.strip() else None
    trailers = build_trailers(
        why=clean_why, fixes=fixes, branch=repo.status().branch, reverts=reverted
    )
    return CommitDraft(
        message=assemble(subject, body, format_trailers(trailers)),
        subject=subject,
        body=body,
        question=question,
        why=clean_why,
        trailers=trailers,
        source=DraftSource.MODEL if written else DraftSource.SKELETON,
        model=writer.model_id if writer and written else None,
        style=describe_style(style),
        examples=examples,
        files=[f.path for f in diff.files],
        redacted=redacted,
        diff_truncated=truncated,
        notes=notes,
    )


def with_why(draft: CommitDraft, why: str | None) -> CommitDraft:
    """The same draft with the author's answer as its ``Why:`` trailer. No model is called."""
    clean = " ".join(why.split()) if why and why.strip() else None
    rest = [t for t in draft.trailers if t.key != "Why"]
    lead = [Trailer(key="Why", value=clean, source=TrailerSource.AUTHOR)] if clean else []
    trailers = lead + rest
    message = assemble(draft.subject, draft.body, format_trailers(trailers))
    return draft.model_copy(update={"why": clean, "trailers": trailers, "message": message})


def _ask(
    writer: CommitWriter | None, style: CommitStyle, examples: str, diff: str, notes: list[str]
) -> Written | None:
    if writer is None:
        return None
    try:
        written = writer.write(style, examples, diff)
    except ModelError as exc:
        notes.append(f"Model unavailable: {exc.message}")
        return None
    if written is None:
        notes.append("The model's reply was not usable.")
    return written


def _parts(
    written: Written | None, style: CommitStyle, files: Sequence[FileDiff], examples: list[str]
) -> tuple[str, str | None, str]:
    """Subject, body and question, from the model's parts or from the skeleton."""
    if written is None:
        type_, scope = guess_type(files, examples, style), guess_scope(examples)
        subject = format_subject(style, skeleton_description(files), type_=type_, scope=scope)
        return subject, None, DEFAULT_QUESTION
    # A repository that uses prefixes always gets one, even when the model left it out.
    type_ = written.type_ or guess_type(files, examples, style)
    subject = format_subject(style, written.description, type_=type_, scope=written.scope)
    body = written.body if written.body and style_wants_body(style) else None
    return subject, body, written.question or DEFAULT_QUESTION


def style_wants_body(style: CommitStyle) -> bool:
    """Bodies when a quarter of past commits have one, or when there is no history."""
    return style.sample_size == 0 or style.body_share >= 0.25


def assemble(subject: str, body: str | None, trailers: str = "") -> str:
    """Subject, blank line, the body wrapped at 72, then the trailer block."""
    paragraphs = [p for p in (wrap(body) if body else "", trailers) if p]
    return "\n\n".join([subject, *paragraphs]) + "\n"


def wrap(text: str) -> str:
    """Wrap prose at ``WRAP``; ``- `` bullets keep their own lines with a hanging indent."""
    out: list[str] = []
    for line in text.strip().splitlines():
        bullet = line.lstrip().startswith(("- ", "* "))
        indent = "  " if bullet else ""
        out.append(textwrap.fill(line.strip(), WRAP, subsequent_indent=indent) if line else "")
    return "\n".join(out)


def file_examples(repo: GitRepo, files: Sequence[FileDiff]) -> list[Commit]:
    """Recent people's commits that touched the changed files, newest first."""
    found: dict[str, Commit] = {}
    for f in files[:HISTORY_FILES]:
        try:
            history = repo.history(limit=HISTORY_PER_FILE, path=f.old_path or f.path).commits
        except SproutError:
            return []  # no commits yet
        found.update((c.hash, c) for c in history if is_authored(c))
    ordered = sorted(found.values(), key=lambda c: c.committed_at, reverse=True)
    return ordered[:EXAMPLES]


def render_examples(past: Sequence[Commit], style: CommitStyle) -> str:
    """Past messages for the prompt: subject plus the first body paragraph, redacted."""
    if not past:
        return "\n".join(f"- {s}" for s in style.examples) or "(none)"
    blocks: list[str] = []
    for commit in past:
        subject, _, rest = commit.message.strip().partition("\n")
        first = rest.strip().split("\n\n", 1)[0].strip()[:300] if rest.strip() else ""
        blocks.append(f"{subject}\n{first}".strip())
    return redact("\n---\n".join(blocks))[0]


def diff_text(diff: Diff) -> tuple[str, int, bool]:
    """The diff as text, secrets redacted before cutting to ``MAX_DIFF``."""
    parts: list[str] = []
    for f in diff.files:
        moved = f" (from {f.old_path})" if f.old_path and f.old_path != f.path else ""
        head = f"### {f.path}{moved}: {f.kind.value}, +{f.additions} -{f.deletions}"
        parts.append(f"{head}\n(binary file)" if f.binary else f"{head}\n{f.patch.rstrip()}")
    text, redacted = redact("\n\n".join(parts))
    truncated = len(text) > MAX_DIFF
    return (text[:MAX_DIFF] + _TRUNCATED if truncated else text), redacted, truncated
