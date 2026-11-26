"""``sprout init`` and ``sprout uninstall``: set Sprout up for agents in one step, and undo it."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.text import Text

from sprout import services
from sprout.cli.index import RichProgress
from sprout.cli.output import JsonOption, RepoOption, emit, handle_errors
from sprout.config import CONFIG_FILE, Settings, load_settings
from sprout.core.git import open_repo
from sprout.core.git.pygit2_repo import Pygit2Repo
from sprout.core.index import vectors
from sprout.core.index.embedder import Embedder
from sprout.core.index.indexer import NullProgress, Progress, build_index
from sprout.core.index.reverts import recent_reverts
from sprout.core.index.store import INDEX_DIR, Store
from sprout.core.setup import git_hook as git_hooks
from sprout.core.setup.background import start_index
from sprout.core.setup.clients import add_server, remove_server
from sprout.core.setup.launcher import server_command
from sprout.errors import BareRepositoryError, SproutError
from sprout.models import (
    Agent,
    ConfigAction,
    EmbedState,
    IndexStats,
    InitReport,
    RevertLink,
    UninstallReport,
)

AgentOption = Annotated[
    list[Agent] | None,
    typer.Option("--agent", "-a", help="Agent to configure; repeat for several. Default: claude."),
]
_ACTIONS = {
    ConfigAction.ADDED: "added Sprout to",
    ConfigAction.UPDATED: "updated Sprout in",
    ConfigAction.UNCHANGED: "already set up:",
    ConfigAction.REMOVED: "removed Sprout from",
    ConfigAction.DELETED_FILE: "deleted",
    ConfigAction.ABSENT: "nothing to remove in",
}


def init(
    repo: RepoOption = Path(),
    agents: AgentOption = None,
    no_embed: Annotated[bool, typer.Option("--no-embed", help="Skip semantic vectors.")] = False,
    wait: Annotated[
        bool, typer.Option("--wait", help="Add vectors now instead of in the background.")
    ] = False,
    git_hook: Annotated[
        bool,
        typer.Option("--git-hook", help="Also install a pre-commit hook that runs the risk check."),
    ] = False,
    commit_hook: Annotated[
        bool,
        typer.Option(
            "--commit-hook",
            help="Also install a prepare-commit-msg hook that drafts messages (may use a model).",
        ),
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Index this repository and connect it to your AI agent's MCP config."""
    with handle_errors(as_json=as_json):
        git = _worktree_repo(repo)
        root = git.root
        settings = load_settings(root)
        server = server_command()
        configs = [add_server(root, agent, server) for agent in agents or [Agent.CLAUDE]]
        hook = git_hooks.install(root) if git_hook else None
        drafts = git_hooks.install(root, hook=git_hooks.PREPARE_COMMIT_MSG) if commit_hook else None
        notes: list[str] = []
        if git.head_hash is None:
            notes.append("No commits yet. Make a first commit, then run sprout init again.")
            indexed = _Indexed(None, EmbedState.SKIPPED, None, [])
        else:
            indexed = _index(git, settings, embed=not no_embed, wait=wait, quiet=as_json)
        if not server.portable:
            notes.append(
                "The config points at this machine's Python. Before committing it, install Sprout"
                " with: uv tool install <path or package>, then run sprout init again."
            )
        report = InitReport(
            root=str(root),
            stats=indexed.stats,
            configs=configs,
            server=server,
            embedding=indexed.embedding,
            embed_log=indexed.log,
            answers=services.describe_answers(settings),
            recent_reverts=indexed.reverts,
            git_hook=hook,
            commit_hook=drafts,
            notes=notes,
        )
        emit(report, as_json=as_json, render=render_init)


def uninstall(
    repo: RepoOption = Path(),
    keep_index: Annotated[
        bool, typer.Option("--keep-index", help="Keep .sprout/ and only remove MCP configs.")
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Remove Sprout from every agent's MCP config, its git hook, and its index."""
    with handle_errors(as_json=as_json):
        git = _worktree_repo(repo)
        root = git.root
        configs = [remove_server(root, agent) for agent in Agent]
        hook = git_hooks.remove(root)
        drafts = git_hooks.remove(root, hook=git_hooks.PREPARE_COMMIT_MSG)
        remove_index = not keep_index and (root / INDEX_DIR).exists()
        if remove_index:
            _delete_folder(root / INDEX_DIR)
        notes = (
            [f"Kept your settings in {CONFIG_FILE}; delete it if unwanted."]
            if (root / CONFIG_FILE).exists()
            else []
        )
        report = UninstallReport(
            root=str(root),
            configs=configs,
            git_hook=hook,
            commit_hook=drafts,
            index_removed=remove_index,
            notes=notes,
        )
        emit(report, as_json=as_json, render=render_uninstall)


def _worktree_repo(path: Path) -> Pygit2Repo:
    git = open_repo(path)
    if git.is_bare:
        raise BareRepositoryError(str(git.root))
    return git


@dataclass(frozen=True)
class _Indexed:
    stats: IndexStats | None
    embedding: EmbedState
    log: str | None
    reverts: list[RevertLink]


def _index(
    git: Pygit2Repo, settings: Settings, *, embed: bool, wait: bool, quiet: bool
) -> _Indexed:
    """Index structure now; add vectors now, in the background, or not at all."""
    embedder = services.build_embedder(settings) if embed else None
    with Store.open(git.root, create=True) as store:
        stats = _build(git, store, quiet=quiet)
        state, log = EmbedState.SKIPPED, None
        if embedder is not None and wait:
            stats = _build(git, store, quiet=quiet, embedder=embedder)
            state = EmbedState.DONE
        elif embedder is not None:
            vectors.ensure_table(store, embedder.name, embedder.dim)
            if vectors.count_unembedded(store):
                log, state = str(start_index(git.root)), EmbedState.BACKGROUND
            else:
                state = EmbedState.DONE
        return _Indexed(stats, state, log, recent_reverts(store))


def _build(
    git: Pygit2Repo, store: Store, *, quiet: bool, embedder: Embedder | None = None
) -> IndexStats:
    if quiet:
        return build_index(git, store, embedder=embedder, progress=NullProgress())
    progress: Progress
    with RichProgress() as progress:
        return build_index(git, store, embedder=embedder, progress=progress)


def _delete_folder(folder: Path) -> None:
    try:
        shutil.rmtree(folder)
    except OSError as exc:
        raise SproutError(
            f"Could not delete {folder}: {exc.strerror or exc}.",
            hint="Stop agents using Sprout and any running sprout index, then run this again.",
        ) from None


def render_init(report: InitReport, out: Console) -> None:
    """Render an ``InitReport``."""
    if report.stats is not None:
        s = report.stats
        out.print(f"Indexed {s.commits:,} commits ({s.reverts:,} reverts) in {INDEX_DIR}/.")
    for change in report.configs:
        out.print(f"{_ACTIONS[change.action]} {change.path}")
    if report.git_hook is not None:
        verb = "already set up:" if report.git_hook.action is ConfigAction.UNCHANGED else "added"
        out.print(f"{verb} the pre-commit risk check ({report.git_hook.path})")
    if report.commit_hook is not None:
        verb = "already set up:" if report.commit_hook.action is ConfigAction.UNCHANGED else "added"
        out.print(f"{verb} commit message drafts ({report.commit_hook.path})")
    embed = {
        EmbedState.BACKGROUND: (
            f"Adding semantic vectors in the background (log: {report.embed_log})."
        ),
        EmbedState.DONE: "Semantic vectors are ready.",
        EmbedState.SKIPPED: "Semantic vectors skipped: questions use keyword search only.",
    }
    if report.stats is not None:
        out.print(embed[report.embedding])
    out.print(f"Answers: {report.answers}")
    if report.recent_reverts:
        out.print(Text("\nRecent reverts Sprout will warn about:", style="bold"))
        for link in report.recent_reverts:
            out.print(_revert_line(link))
    for note in report.notes:
        out.print(Text(note, style="dim"))
    out.print('\nTry: sprout why "<question>", or restart your agent and ask it why code exists.')


def _revert_line(link: RevertLink) -> Text:
    line = Text(f"  {link.revert.short_hash}", style="yellow")
    line.append(f" {link.revert.authored_at:%Y-%m-%d} reverted ")
    line.append(link.reverted_hash[:7], style="yellow")
    line.append(f" {link.reverted_summary}")
    return line


def render_uninstall(report: UninstallReport, out: Console) -> None:
    """Render an ``UninstallReport``."""
    for change in report.configs:
        if change.action is not ConfigAction.ABSENT:
            out.print(f"{_ACTIONS[change.action]} {change.path}")
    if report.git_hook.action is ConfigAction.DELETED_FILE:
        out.print(f"deleted the pre-commit risk check ({report.git_hook.path})")
    if report.commit_hook and report.commit_hook.action is ConfigAction.DELETED_FILE:
        out.print(f"deleted commit message drafts ({report.commit_hook.path})")
    out.print(f"deleted {INDEX_DIR}/" if report.index_removed else f"kept {INDEX_DIR}/")
    for note in report.notes:
        out.print(Text(note, style="dim"))
