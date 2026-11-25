"""Route a ``why`` target (``path:line`` or a question) the same way on every surface."""

from __future__ import annotations

import re
from pathlib import Path

from sprout.core.answer.why import Models, WhyOptions, why_line, why_question
from sprout.core.git.pygit2_repo import Pygit2Repo
from sprout.core.index.store import Store
from sprout.errors import IndexNotFoundError, SproutError
from sprout.models import WhyAnswer

_LINE_TARGET = re.compile(r"^(?P<path>[^\s]+):(?P<line>\d+)$")


def parse_line_target(repo: Pygit2Repo, cwd: Path, target: str) -> tuple[str, int] | None:
    """``(path, line)`` relative to the repository root, or None if ``target`` is a question.

    The path may be absolute, relative to ``cwd`` or relative to the repository root.

    Raises:
        SproutError: ``target`` looks like ``path:line`` but no such file exists.
    """
    match = _LINE_TARGET.match(target.strip())
    if match is None:
        return None
    raw, line = match["path"], int(match["line"])
    for candidate in (cwd / raw, repo.root / raw):
        if candidate.is_file():
            return repo.relative_path(candidate), line
    raise SproutError(
        f"No file named {raw} in this repository.",
        hint="Use a path relative to this folder or the repository root, e.g. src/app.py:42",
    )


def why_target(
    repo: Pygit2Repo,
    store: Store | None,
    target: str,
    *,
    cwd: Path,
    rev: str | None = None,
    models: Models | None = None,
    options: WhyOptions | None = None,
) -> WhyAnswer:
    """Answer ``why`` for a ``path:line`` or a free-text question.

    Lines use the answerer only: the embedder and reranker are for questions, which is how
    WhyBench measured both.

    Raises:
        IndexNotFoundError: a question was asked but there is no index to search.
    """
    models = models or Models()
    line_target = parse_line_target(repo, cwd, target)
    if line_target is not None:
        path, line = line_target
        line_models = Models(answerer=models.answerer)
        return why_line(repo, store, path, line, rev=rev, models=line_models, options=options)
    if store is None:
        raise IndexNotFoundError(str(repo.root))
    return why_question(repo, store, target, rev=rev, models=models, options=options)
