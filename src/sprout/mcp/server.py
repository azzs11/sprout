"""Sprout's MCP server: cited answers from git history for AI agents."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from sprout import __version__
from sprout.errors import SproutError
from sprout.mcp import format as fmt
from sprout.mcp.session import Session

INSTRUCTIONS = """\
Sprout answers "why is this code like this?" from this repository's git history.
Call `why` with path:line before changing code you did not write, especially before removing
a check, retry, timeout or workaround: it shows the commits behind the line, quotes the
stated reason, and flags reverts. Cite the commit hashes it returns. If it says no commit
states a reason, say that instead of guessing.
"""
_READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)


def build_server(session: Session) -> MCPServer:
    """An MCP server whose tools answer from ``session``'s repository."""
    server = MCPServer(
        name="sprout", version=__version__, instructions=INSTRUCTIONS, log_level="WARNING"
    )

    @server.tool(annotations=_READ_ONLY)
    def why(
        target: Annotated[
            str,
            Field(description="A line as path:line (e.g. src/auth.py:42), or a question."),
        ],
        at: Annotated[
            str | None, Field(description="Commit, branch or tag to ask about; default HEAD.")
        ] = None,
        facts_only: Annotated[
            bool, Field(description="Skip the local language model and list facts only.")
        ] = False,
        limit: Annotated[int, Field(ge=1, le=12, description="Commits to cite.")] = 6,
    ) -> str:
        """Explain why a line of code exists, or answer a why-question, citing commits."""
        return _run(
            lambda: fmt.why_text(session.why(target, at=at, facts_only=facts_only, limit=limit))
        )

    @server.tool(annotations=_READ_ONLY)
    def search_history(
        query: Annotated[str, Field(description='What to look for, e.g. "retry payments".')],
        limit: Annotated[int, Field(ge=1, le=20, description="Commits to return.")] = 8,
    ) -> str:
        """Search this repository's commit history (messages, files, functions, reverts)."""
        return _run(lambda: fmt.search_text(session.search(query, limit=limit)))

    return server


def serve(path: Path) -> None:
    """Run the server over stdio for the repository containing ``path``."""
    session = Session(path)
    try:
        build_server(session).run("stdio")
    finally:
        session.close()


def _run(call: Callable[[], str]) -> str:
    """Turn a ``SproutError`` into a tool error the agent can act on."""
    try:
        return call()
    except SproutError as exc:
        raise ToolError(exc.message + (f" Fix: {exc.hint}" if exc.hint else "")) from exc
