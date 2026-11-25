"""Install or remove Sprout's git pre-commit hook. A hook Sprout did not write is never touched."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from sprout.errors import SproutError
from sprout.models import ConfigAction, HookChange

MARKER = "# sprout-hook: installed by sprout"
_SCRIPT = """\
#!/bin/sh
{marker}. Remove it with: sprout uninstall
# Warns when staged changes undo a past fix or re-apply a reverted change. No model is called.
# It stops a commit only when a past security fix is undone. Skip: SPROUT_SKIP=1 or --no-verify.
[ "$SPROUT_SKIP" = 1 ] && exit 0
if command -v sprout-hook >/dev/null 2>&1; then exec sprout-hook pre-commit; fi
if [ -x {python} ]; then exec {python} -m sprout.hook pre-commit; fi
exit 0
"""


def hook_path(root: Path) -> Path:
    """Where git looks for this repository's pre-commit hook (honours core.hooksPath)."""
    done = subprocess.run(  # noqa: S603 - fixed arguments, git from PATH
        ["git", "-C", str(root), "rev-parse", "--git-path", "hooks/pre-commit"],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    path = Path(done.stdout.strip())
    return path if path.is_absolute() else root / path


def install(root: Path, python: str | None = None) -> HookChange:
    """Write the hook. The interpreter is found when the hook runs; ``python`` is the fallback.

    Raises:
        SproutError: another pre-commit hook is already installed.
    """
    path = hook_path(root)
    script = _SCRIPT.format(marker=MARKER, python=_quote(python or sys.executable))
    existing = path.read_text(encoding="utf-8", errors="replace") if path.exists() else None
    if existing is not None and MARKER not in existing:
        raise SproutError(
            f"{path} already exists and was not written by Sprout, so it was left alone.",
            hint="Add this line to it: sprout-hook pre-commit   (or use the pre-commit framework"
            " entry in Sprout's .pre-commit-hooks.yaml)",
        )
    if existing == script:
        return HookChange(path=str(path), action=ConfigAction.UNCHANGED)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(script, encoding="utf-8", newline="\n")
    path.chmod(0o755)
    action = ConfigAction.ADDED if existing is None else ConfigAction.UPDATED
    return HookChange(path=str(path), action=action)


def remove(root: Path) -> HookChange:
    """Delete the hook if Sprout wrote it."""
    path = hook_path(root)
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    if MARKER not in text:
        return HookChange(path=str(path), action=ConfigAction.ABSENT)
    path.unlink()
    return HookChange(path=str(path), action=ConfigAction.DELETED_FILE)


def _quote(value: str) -> str:
    """Single-quote for sh, with forward slashes so Git for Windows' sh can run it."""
    return "'" + Path(value).as_posix().replace("'", "'\\''") + "'"
