"""Agent MCP configs, the server command, recent reverts and the answers line."""

from __future__ import annotations

import json
import os
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from sprout import services
from sprout.config import Settings
from sprout.core.git import open_repo
from sprout.core.index.indexer import build_index
from sprout.core.index.reverts import recent_reverts
from sprout.core.index.store import Store
from sprout.core.setup.clients import add_server, remove_server
from sprout.core.setup.launcher import server_command
from sprout.errors import SproutError
from sprout.llm.ollama import OllamaProvider
from sprout.models import Agent, ConfigAction, ServerCommand
from tests.fixtures.builder import RepoBuilder

MakeRepo = Callable[[str], RepoBuilder]
SERVER = ServerCommand(command="sprout", args=["mcp", "serve"], portable=True)


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# ----- config files -------------------------------------------------------------------


def test_add_creates_each_agents_format(tmp_path: Path) -> None:
    for agent in Agent:
        assert add_server(tmp_path, agent, SERVER).action is ConfigAction.ADDED
    claude = {"command": "sprout", "args": ["mcp", "serve"]}
    assert read(tmp_path / ".mcp.json") == {"mcpServers": {"sprout": claude}}
    assert read(tmp_path / ".cursor/mcp.json") == {"mcpServers": {"sprout": claude}}
    assert read(tmp_path / ".vscode/mcp.json") == {
        "servers": {"sprout": {"type": "stdio", **claude}}
    }


def test_add_keeps_other_servers_and_is_idempotent(tmp_path: Path) -> None:
    config = tmp_path / ".mcp.json"
    config.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "extra": 1}))
    assert add_server(tmp_path, Agent.CLAUDE, SERVER).action is ConfigAction.ADDED
    assert add_server(tmp_path, Agent.CLAUDE, SERVER).action is ConfigAction.UNCHANGED
    moved = SERVER.model_copy(update={"command": "/opt/sprout"})
    assert add_server(tmp_path, Agent.CLAUDE, moved).action is ConfigAction.UPDATED
    data = read(config)
    assert data["extra"] == 1
    assert data["mcpServers"]["other"] == {"command": "x"}
    assert data["mcpServers"]["sprout"]["command"] == "/opt/sprout"


def test_never_rewrites_a_file_with_comments(tmp_path: Path) -> None:
    config = tmp_path / ".vscode/mcp.json"
    config.parent.mkdir()
    original = '// my servers\n{"servers": {}}\n'
    config.write_text(original)
    with pytest.raises(SproutError) as caught:
        add_server(tmp_path, Agent.VSCODE, SERVER)
    assert config.read_text() == original
    assert caught.value.hint is not None
    assert '"type": "stdio"' in caught.value.hint
    with pytest.raises(SproutError, match="not plain JSON"):
        remove_server(tmp_path, Agent.VSCODE)


def test_servers_must_be_an_object(tmp_path: Path) -> None:
    (tmp_path / ".mcp.json").write_text('{"mcpServers": []}')
    with pytest.raises(SproutError, match="is not an object"):
        add_server(tmp_path, Agent.CLAUDE, SERVER)


def test_remove_keeps_other_servers(tmp_path: Path) -> None:
    config = tmp_path / ".mcp.json"
    config.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))
    add_server(tmp_path, Agent.CLAUDE, SERVER)
    assert remove_server(tmp_path, Agent.CLAUDE).action is ConfigAction.REMOVED
    assert read(config) == {"mcpServers": {"other": {"command": "x"}}}
    assert remove_server(tmp_path, Agent.CLAUDE).action is ConfigAction.ABSENT


def test_remove_deletes_files_and_folders_sprout_made(tmp_path: Path) -> None:
    add_server(tmp_path, Agent.CURSOR, SERVER)
    add_server(tmp_path, Agent.VSCODE, SERVER)
    (tmp_path / ".vscode/settings.json").write_text("{}")
    assert remove_server(tmp_path, Agent.CURSOR).action is ConfigAction.DELETED_FILE
    assert remove_server(tmp_path, Agent.VSCODE).action is ConfigAction.DELETED_FILE
    assert not (tmp_path / ".cursor").exists()
    assert (tmp_path / ".vscode/settings.json").exists()  # not ours, so the folder stays
    assert remove_server(tmp_path, Agent.CLAUDE).action is ConfigAction.ABSENT


# ----- server command -----------------------------------------------------------------


def _fake_sprout(folder: Path) -> None:
    folder.mkdir()
    name = "sprout.exe" if os.name == "nt" else "sprout"
    exe = folder / name
    exe.write_text("#!/bin/sh\n")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)


def test_global_sprout_is_portable(tmp_path: Path) -> None:
    _fake_sprout(tmp_path / "bin")
    server = server_command(str(tmp_path / "bin"))
    assert server == ServerCommand(command="sprout", args=["mcp", "serve"], portable=True)


def test_sprout_only_in_this_environment_is_not_portable() -> None:
    own_bin = Path(sys.prefix) / ("Scripts" if os.name == "nt" else "bin")
    server = server_command(str(own_bin))
    assert not server.portable
    assert server.command == sys.executable
    assert server.args == ["-m", "sprout", "mcp", "serve"]


# ----- recent reverts -----------------------------------------------------------------


def _indexed(repo: RepoBuilder) -> Store:
    store = Store.open(repo.root, create=True)
    build_index(open_repo(repo.root), store)
    return store


def test_recent_reverts_links_by_hash(make_repo: MakeRepo) -> None:
    repo = make_repo("payments")
    with _indexed(repo) as store:
        links = recent_reverts(store)
    assert len(links) == 1
    assert links[0].reverted_summary == "perf(payments): disable charge retries to cut latency"
    assert links[0].revert.summary.startswith('Revert "perf(payments)')


def test_recent_reverts_by_subject_skips_unlinked_and_limits(make_repo: MakeRepo) -> None:
    repo = make_repo("empty")
    for n in range(4):
        repo.write("a.py", f"A = {n}\n").commit(f"feat: step {n}")
        repo.write("a.py", f"A = {n}0\n").commit(f'Revert "feat: step {n}"')
    repo.write("b.py", "B = 1\n").commit("Revert gone\n\nThis reverts commit 0123456789abcdef.")
    with _indexed(repo) as store:
        links = recent_reverts(store, limit=3)
    assert [link.reverted_summary for link in links] == [
        "feat: step 3",
        "feat: step 2",
        "feat: step 1",
    ]


# ----- answers line -------------------------------------------------------------------


def test_describe_answers_without_a_model() -> None:
    assert "SPROUT_LLM_PROVIDER is none" in services.describe_answers(Settings(llm_provider="none"))
    no_key = Settings(llm_provider="anthropic", anthropic_api_key=None)
    assert "ANTHROPIC_API_KEY is not set" in services.describe_answers(no_key)


@pytest.mark.parametrize(
    ("available", "has_model", "expected"),
    [
        (False, False, "Ollama is not running"),
        (True, False, "Run: ollama pull qwen2.5-coder:7b"),
        (True, True, "Written by qwen2.5-coder:7b through Ollama, on this machine."),
    ],
)
def test_describe_answers_with_ollama(
    monkeypatch: pytest.MonkeyPatch, available: bool, has_model: bool, expected: str
) -> None:
    monkeypatch.setattr(OllamaProvider, "available", lambda _self: available)
    monkeypatch.setattr(OllamaProvider, "has_model", lambda _self: has_model)
    text = services.describe_answers(Settings(llm_provider="ollama", llm_model="qwen2.5-coder:7b"))
    assert expected in text


def test_ollama_has_model() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "tiny:latest"}, {"name": "big:7b"}]})

    for model, found in [("tiny", True), ("big:7b", True), ("big", False)]:
        provider = OllamaProvider(model)
        provider._client = httpx.Client(  # pyright: ignore[reportPrivateUsage]
            base_url="http://ollama.test", transport=httpx.MockTransport(handler)
        )
        assert provider.has_model() is found
        assert provider.model == model
    down = OllamaProvider("tiny")
    down._client = httpx.Client(  # pyright: ignore[reportPrivateUsage]
        base_url="http://ollama.test", transport=httpx.MockTransport(lambda _r: httpx.Response(500))
    )
    assert not down.has_model()
