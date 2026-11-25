"""``sprout mcp``: run Sprout as an MCP server for AI agents."""

from __future__ import annotations

from pathlib import Path

import typer

from sprout.cli.output import RepoOption, handle_errors

mcp_app = typer.Typer(
    name="mcp",
    help="Run Sprout as an MCP server for Claude Code, Cursor and other agents.",
    no_args_is_help=True,
)


@mcp_app.command()
def serve(repo: RepoOption = Path()) -> None:
    """Serve the MCP tools over stdio (agents start this; you rarely run it by hand)."""
    from sprout.mcp.server import serve as run_server  # the SDK is only imported when serving

    with handle_errors(as_json=False):
        run_server(repo)
