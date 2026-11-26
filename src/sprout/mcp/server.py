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
stated reason, and flags reverts. Before an edit that removes or rewrites existing code, call
`check_edit` with the path, old and new text: it returns proceed, review or stop, citing past
fixes and reverts the edit would undo. Use `explain_commit` to read a cited commit and
`search_history` to find commits by topic. Before committing, call `suggest_commit_message`
with the reason the user gave (never an invented one) and write the message in its style.
Cite the commit hashes these tools return. If they say no commit states a reason, say that
instead of guessing.
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

    @server.tool(annotations=_READ_ONLY)
    def explain_commit(
        commit: Annotated[str, Field(description="A commit hash (short is fine), branch or tag.")],
    ) -> str:
        """Show one commit: its stated reason, files and functions changed, reverts, and diff."""
        return _run(lambda: fmt.commit_text(session.explain(commit)))

    @server.tool(annotations=_READ_ONLY)
    def check_edit(
        path: Annotated[
            str | None, Field(description="File to edit (relative to the repo root or absolute).")
        ] = None,
        old: Annotated[
            str | None, Field(description="Text being replaced; omit to replace the whole file.")
        ] = None,
        new: Annotated[str | None, Field(description="The new text (required with path).")] = None,
        diff: Annotated[
            str | None, Field(description="A unified diff to check instead of path/old/new.")
        ] = None,
    ) -> str:
        """Before changing code: does history warn against it? Returns proceed, review or stop.

        With no arguments, checks the uncommitted changes. Cites the fix, security or revert
        commits the change runs into. Deterministic, no model.
        """
        return _run(lambda: fmt.risk_text(session.check(path=path, old=old, new=new, diff=diff)))

    @server.tool(annotations=_READ_ONLY)
    def suggest_commit_message(
        why: Annotated[
            str | None,
            Field(
                description="The user's own reason for the change, quoted from their request."
                " Leave it out rather than guess."
            ),
        ] = None,
        fixes: Annotated[
            list[int] | None, Field(description="Issue numbers this change closes.")
        ] = None,
    ) -> str:
        """Before committing: the repo's message style, past messages and a draft with trailers.

        Covers the staged changes (else the unstaged ones). The draft carries Why, Fixes, Refs
        and Reverts trailers for the history index. Deterministic, no model; it never commits.
        """
        return _run(lambda: fmt.draft_text(session.suggest_message(why=why, fixes=fixes or [])))

    return server


def serve(path: Path, *, http: tuple[str, int] | None = None) -> None:
    """Run the server for the repository containing ``path``, over stdio or local HTTP.

    With ``http=(host, port)`` it serves streamable HTTP at ``/mcp``. On a loopback host the
    SDK also rejects requests whose Host or Origin is not local (DNS rebinding).
    """
    session = Session(path)
    server = build_server(session)
    try:
        if http is None:
            server.run("stdio")
        else:
            server.run("streamable-http", host=http[0], port=http[1])
    finally:
        session.close()


def _run(call: Callable[[], str]) -> str:
    """Turn a ``SproutError`` into a tool error the agent can act on."""
    try:
        return call()
    except SproutError as exc:
        raise ToolError(exc.message + (f" Fix: {exc.hint}" if exc.hint else "")) from exc
