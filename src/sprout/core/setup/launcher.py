"""Work out the command an agent should run to start Sprout's MCP server."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from sprout.models import ServerCommand

SERVE_ARGS = ["mcp", "serve"]


def server_command(path_env: str | None = None) -> ServerCommand:
    """``sprout mcp serve`` if a global ``sprout`` is on PATH, else this interpreter's path.

    The running environment's own ``bin`` folder is ignored: under ``uv run`` or ``uvx`` it
    is on PATH only for this process, and agents would not find it later.
    """
    own_bin = Path(sys.prefix) / ("Scripts" if os.name == "nt" else "bin")
    entries = (path_env if path_env is not None else os.environ.get("PATH", "")).split(os.pathsep)
    others = os.pathsep.join(p for p in entries if p and _differs(Path(p), own_bin))
    if shutil.which("sprout", path=others):
        return ServerCommand(command="sprout", args=SERVE_ARGS, portable=True)
    return ServerCommand(command=sys.executable, args=["-m", "sprout", *SERVE_ARGS], portable=False)


def _differs(a: Path, b: Path) -> bool:
    try:
        return a.resolve() != b.resolve()
    except OSError:
        return True
