"""``sprout-hook``: the fast, model-free history check for git and agent hooks.

``sprout-hook pre-commit`` checks the staged diff. ``sprout-hook agent`` reads a PreToolUse event
(Edit, MultiEdit or Write) on stdin. This module uses the standard library only: it finds the
repository and returns at once when there is no Sprout index, so hooks cost almost nothing in
repositories that do not use Sprout. The checks themselves live in ``sprout.hook_checks``.
``sprout-hook prepare-commit-msg`` (opt-in) drafts the message for a plain ``git commit``; it
may call a model and lives in ``sprout.hook_commit``.

Both fail open: no index, no repository, an unreadable event or any error means silence and exit 0.
Environment: ``SPROUT_SKIP=1`` skips, ``SPROUT_RISK_LEVEL=high`` shows only high findings,
``SPROUT_STRICT=1`` blocks on any shown finding, ``SPROUT_DEBUG=1`` prints errors.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

INDEX = Path(".sprout") / "index.db"
EDIT_TOOLS = frozenset({"Edit", "MultiEdit", "Write"})


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for ``sprout-hook <pre-commit|agent|prepare-commit-msg>``."""
    args = list(sys.argv[1:] if argv is None else argv)
    if os.environ.get("SPROUT_SKIP") == "1" or not args:
        return 0
    try:
        if args[0] == "pre-commit":
            if indexed_root(Path.cwd()) is None:
                return 0
            from sprout.hook_checks import pre_commit

            return pre_commit(Path.cwd())
        if args[0] == "prepare-commit-msg":
            from sprout.hook_commit import prepare_commit_msg

            return prepare_commit_msg(Path.cwd(), args[1:])
        if args[0] == "agent":
            event = cast("dict[str, object]", json.load(sys.stdin))
            if not wants(event):
                return 0
            from sprout.hook_checks import agent

            return agent(event, sys.stdout)
    except Exception as exc:  # a hook must never break a commit or an edit
        if os.environ.get("SPROUT_DEBUG") == "1":
            print(f"sprout-hook: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 0


def wants(event: object) -> bool:
    """True for an Edit, MultiEdit or Write of a file inside a repository with a Sprout index."""
    if not isinstance(event, dict):
        return False
    data = cast("dict[str, object]", event)
    tool_input = data.get("tool_input")
    if data.get("tool_name") not in EDIT_TOOLS or not isinstance(tool_input, dict):
        return False
    path = cast("dict[str, object]", tool_input).get("file_path")
    return isinstance(path, str) and indexed_root(Path(path).parent) is not None


def indexed_root(start: Path) -> Path | None:
    """The enclosing repository's root if it has a Sprout index, found without importing git."""
    for folder in (start.resolve(), *start.resolve().parents):
        if (folder / ".git").exists():
            return folder if (folder / INDEX).is_file() else None
    return None


if __name__ == "__main__":
    raise SystemExit(main())
