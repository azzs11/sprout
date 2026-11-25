"""``sprout mcp``: run Sprout as an MCP server for AI agents."""

from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Annotated

import typer

from sprout.cli.output import RepoOption, err_console, handle_errors

mcp_app = typer.Typer(
    name="mcp",
    help="Run Sprout as an MCP server for Claude Code, Cursor and other agents.",
    no_args_is_help=True,
)


@mcp_app.command()
def serve(
    repo: RepoOption = Path(),
    http: Annotated[
        bool, typer.Option("--http", help="Serve streamable HTTP at /mcp instead of stdio.")
    ] = False,
    host: Annotated[str, typer.Option(help="Address for --http.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(min=1, max=65535, help="Port for --http.")] = 8765,
) -> None:
    """Serve the MCP tools (agents start this; you rarely run it by hand)."""
    from sprout.mcp.server import serve as run_server  # the SDK is only imported when serving

    with handle_errors(as_json=False):
        if http and not _is_loopback(host):
            err_console().print(
                f"Warning: serving on {host} lets other machines read this repository's"
                " history. There is no authentication.",
            )
        run_server(repo, http=(host, port) if http else None)


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
