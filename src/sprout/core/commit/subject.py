"""Write a subject line in a repository's style, and guess one when no model is available."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from pathlib import PurePosixPath

from sprout.core.git.message import parse_message
from sprout.models import ChangeKind, CommitStyle, FileDiff

DEFAULT_LIMIT = 72
STANDARD_TYPES = (
    "feat", "fix", "docs", "refactor", "test", "perf", "build", "ci", "chore", "style",
)  # fmt: skip
_PREFIX = re.compile(r"^[a-zA-Z]+(?:\([^()\n]*\))?!?:\s*")
_DOC_SUFFIXES = frozenset({".md", ".rst", ".txt", ".adoc"})
_BUILD_FILES = frozenset(
    {"pyproject.toml", "setup.py", "setup.cfg", "uv.lock", "package.json", "package-lock.json",
     "pnpm-lock.yaml", "yarn.lock", "go.mod", "go.sum", "Cargo.toml", "Cargo.lock", "Makefile"}
)  # fmt: skip


def uses_conventional(style: CommitStyle) -> bool:
    """Conventional prefixes when most past commits have one, or when there is no history."""
    return style.sample_size == 0 or style.conventional_share >= 0.5


def uses_scopes(style: CommitStyle) -> bool:
    """Scopes when at least a third of the prefixed commits seen carry one."""
    prefixed = style.conventional_share * style.sample_size
    return prefixed > 0 and sum(c.count for c in style.scopes) >= prefixed / 3


def subject_limit(style: CommitStyle) -> int:
    """The length most of this repository's subjects stay under."""
    return max(style.subject_p90, 50) if style.sample_size else DEFAULT_LIMIT


def allowed_types(style: CommitStyle) -> list[str]:
    """The repository's own types first, then the standard ones."""
    return list(dict.fromkeys([c.value for c in style.types] + list(STANDARD_TYPES)))


def format_subject(
    style: CommitStyle, description: str, *, type_: str | None, scope: str | None
) -> str:
    """One line: ``type(scope): description`` or the bare description, in the repo's style."""
    text = _PREFIX.sub("", " ".join(description.split()), count=1).rstrip(" .")
    if style.sample_size and style.capitalised_share >= 0.5:
        text = text[:1].upper() + text[1:]
    elif text[1:2].islower() or len(text) == 1:
        text = text[:1].lower() + text[1:]  # leave acronyms such as "HTTP" alone
    if style.period_share >= 0.5:
        text += "."
    if not uses_conventional(style) or not type_:
        return text
    scoped = f"({scope.strip()})" if scope and scope.strip() and uses_scopes(style) else ""
    return f"{type_.strip().lower()}{scoped}: {text}"


def guess_type(files: Sequence[FileDiff], examples: Sequence[str], style: CommitStyle) -> str:
    """A type from the paths alone (tests, docs, CI, build), else what these files usually get."""
    paths = [PurePosixPath(f.path) for f in files]
    for type_, test in _PATH_TYPES:
        if paths and all(test(p) for p in paths):
            return type_
    seen = [t for t in (parse_message(s).conventional_type for s in examples) if t]
    if seen:
        return Counter(seen).most_common(1)[0][0]
    return style.types[0].value if style.types else "feat"


def guess_scope(examples: Sequence[str]) -> str | None:
    """The scope past commits to these files used most, if any."""
    scopes = [s for s in (parse_message(e).scope for e in examples) if s]
    return Counter(scopes).most_common(1)[0][0] if scopes else None


def skeleton_description(files: Sequence[FileDiff]) -> str:
    """'add x', 'remove x' or 'update x', naming one file, a shared folder, or a count."""
    kinds = {f.kind for f in files}
    verb = (
        "add" if kinds == {ChangeKind.ADDED}
        else "remove" if kinds == {ChangeKind.DELETED}
        else "rename" if kinds == {ChangeKind.RENAMED}
        else "update"
    )  # fmt: skip
    return f"{verb} {_name(files)}"


def _name(files: Sequence[FileDiff]) -> str:
    paths = [PurePosixPath(f.path) for f in files]
    if len(paths) == 1:
        return paths[0].name
    parents = {p.parent for p in paths}
    if len(parents) == 1 and str(next(iter(parents))) != ".":
        return f"{next(iter(parents)).name}/"
    return f"{len(paths)} files"


def _is_test(path: PurePosixPath) -> bool:
    parts = {p.lower() for p in path.parts[:-1]}
    stem = path.stem.lower()
    return (
        bool(parts & {"test", "tests", "__tests__", "spec"})
        or stem.startswith("test_")
        or (stem.endswith(("_test", ".test", ".spec", "_spec")))
    )


def _is_doc(path: PurePosixPath) -> bool:
    return path.suffix.lower() in _DOC_SUFFIXES or "docs" in path.parts[:-1]


def _is_ci(path: PurePosixPath) -> bool:
    return path.parts[:1] == (".github",) or path.name in {".gitlab-ci.yml", ".travis.yml"}


def _is_build(path: PurePosixPath) -> bool:
    return path.name in _BUILD_FILES


_PATH_TYPES = (("test", _is_test), ("docs", _is_doc), ("ci", _is_ci), ("build", _is_build))
