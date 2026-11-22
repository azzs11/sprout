"""Shared CLI plumbing: options, JSON output and error display."""

from __future__ import annotations

import json
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, TypeVar

import typer
from pydantic import BaseModel
from rich.console import Console

from sprout.core.git import GitRepo, open_repo
from sprout.errors import SproutError

JsonOption = Annotated[
    bool, typer.Option("--json", help="Print machine-readable JSON instead of text.")
]
RepoOption = Annotated[
    Path,
    typer.Option(
        "--repo",
        "-C",
        help="Run as if Sprout was started in this directory.",
        file_okay=False,
        show_default=False,
    ),
]


def console() -> Console:
    """Console for normal output. Honours NO_COLOR and terminal width."""
    return Console(highlight=False, soft_wrap=False)


def err_console() -> Console:
    """Console for errors, written to stderr."""
    return Console(stderr=True, highlight=False)


M = TypeVar("M", bound=BaseModel)


def emit(model: M, *, as_json: bool, render: Callable[[M, Console], None]) -> None:
    """Print ``model`` as JSON or render it for humans."""
    if as_json:
        typer.echo(model.model_dump_json(indent=2))
    else:
        render(model, console())


@contextmanager
def handle_errors(*, as_json: bool) -> Generator[None]:
    """Turn ``SproutError`` into a friendly message and exit code 1."""
    try:
        yield
    except SproutError as exc:
        if as_json:
            typer.echo(json.dumps({"error": exc.message, "hint": exc.hint}, indent=2))
        else:
            out = err_console()
            out.print(f"[bold red]Error:[/] {exc.message}", markup=True)
            if exc.hint:
                out.print(f"[bold]Fix:[/] {exc.hint}", markup=True)
        raise typer.Exit(code=1) from None


def load_repo(path: Path) -> GitRepo:
    """Open the repository containing ``path``."""
    return open_repo(path)
