"""Run ``sprout index`` detached, so embeddings finish after ``sprout init`` returns."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sprout.core.index.store import INDEX_DIR

LOG_FILE = "embed.log"


def start_index(root: Path) -> Path:
    """Start a detached ``sprout index`` for ``root`` and return its log file.

    The indexer is resumable, so stopping it (or rebooting) loses nothing: the next
    ``sprout index`` continues where it stopped.
    """
    log = root / INDEX_DIR / LOG_FILE
    log.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "sprout", "index", "--json", "-C", str(root)]
    with log.open("ab") as out:
        if os.name == "nt":
            flags = (
                subprocess.CREATE_NEW_PROCESS_GROUP  # pyright: ignore[reportAttributeAccessIssue]
                | subprocess.DETACHED_PROCESS  # pyright: ignore[reportAttributeAccessIssue]
                | subprocess.CREATE_NO_WINDOW  # pyright: ignore[reportAttributeAccessIssue]
            )
            subprocess.Popen(  # noqa: S603 - our own interpreter and arguments
                command, stdin=subprocess.DEVNULL, stdout=out, stderr=out, creationflags=flags
            )
        else:
            subprocess.Popen(  # noqa: S603 - our own interpreter and arguments
                command,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=out,
                start_new_session=True,
            )
    return log
