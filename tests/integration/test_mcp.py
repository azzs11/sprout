"""The MCP server, driven through the official SDK client (in-process and over stdio)."""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from mcp import Client, StdioServerParameters
from typer.testing import CliRunner

from sprout import services
from sprout.cli.app import app
from sprout.config import Settings
from sprout.mcp.format import MAX_CHARS, fit
from sprout.mcp.server import build_server
from sprout.mcp.session import Session
from tests.fakes import FakeEmbedder, FakeReranker
from tests.fixtures.builder import RepoBuilder

MakeRepo = Callable[[str], RepoBuilder]
OFFLINE = Settings(llm_provider="none")


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(services, "build_answerer", lambda _s: (None, None))
    monkeypatch.setattr(services, "build_embedder", lambda _s: FakeEmbedder())
    monkeypatch.setattr(services, "build_reranker", lambda _s: FakeReranker())


def index(root: Path) -> None:
    result = CliRunner().invoke(app, ["index", "-C", str(root)])
    assert result.exit_code == 0, result.output


@pytest.fixture
def session(make_repo: MakeRepo) -> Iterator[Session]:
    repo = make_repo("payments")
    index(repo.root)
    s = Session(repo.root, OFFLINE)
    yield s
    s.close()


def call(session: Session, tool: str, args: dict[str, Any]) -> tuple[bool, str]:
    async def run() -> tuple[bool, str]:
        async with Client(build_server(session)) as client:
            result = await client.call_tool(tool, args)
            return result.is_error, result.content[0].text  # type: ignore[union-attr]

    return asyncio.run(run())


def test_lists_read_only_tools(session: Session) -> None:
    async def run() -> list[Any]:
        async with Client(build_server(session)) as client:
            assert "path:line" in (client.instructions or "")
            return (await client.list_tools()).tools

    tools = {t.name: t for t in asyncio.run(run())}
    assert set(tools) == {"why", "search_history", "explain_commit"}
    assert all(t.annotations and t.annotations.read_only_hint for t in tools.values())
    assert tools["why"].input_schema["required"] == ["target"]


def test_why_line_cites_commits_and_quotes_the_reason(make_repo: MakeRepo) -> None:
    repo = make_repo("lineage")
    index(repo.root)
    s = Session(repo.root, OFFLINE)
    error, text = call(s, "why", {"target": "src/payments/core.py:2"})
    s.close()
    assert not error, text
    assert text.startswith("why src/payments/core.py:2 (in charge)")
    assert "facts from git history, no model" in text
    assert "Basis: the top commit's message states the reason" in text
    assert 'reason: "We raised the limit because the card network times out' in text
    fix = repo.git("rev-parse", "HEAD~1").strip()
    assert f"{fix[:12]} " in text
    assert "(last changed this line; fix; #7)" in text


def test_why_absolute_path_works(make_repo: MakeRepo) -> None:
    repo = make_repo("lineage")
    s = Session(repo.root, OFFLINE)  # no index: line answers still work from git alone
    error, text = call(s, "why", {"target": f"{repo.root / 'src/payments/core.py'}:2"})
    s.close()
    assert not error, text
    assert "Note: No index yet" in text


def test_why_flags_reverted_commits(session: Session) -> None:
    error, text = call(session, "why", {"target": "why do we retry failed charges?"})
    assert not error, text
    assert "REVERTED by " in text


def test_errors_carry_the_fix(session: Session) -> None:
    error, text = call(session, "why", {"target": "src/missing.py:3"})
    assert error
    assert "No file named src/missing.py" in text
    assert "Fix: " in text


def test_question_without_index_says_how_to_build_it(make_repo: MakeRepo) -> None:
    repo = make_repo("payments")
    s = Session(repo.root, OFFLINE)
    error, text = call(s, "search_history", {"query": "retries"})
    s.close()
    assert error
    assert "Fix: Build it with: sprout index" in text


def test_search_history(session: Session) -> None:
    error, text = call(session, "search_history", {"query": "timing attacks", "limit": 3})
    assert not error, text
    assert text.splitlines()[0] == 'search "timing attacks" (hybrid, reranked): 3 commits'
    assert "constant time" in text.splitlines()[1]


def test_sees_new_commits_after_reindex(make_repo: MakeRepo) -> None:
    repo = make_repo("payments")
    index(repo.root)
    s = Session(repo.root, OFFLINE)
    call(s, "search_history", {"query": "retries"})  # loads and caches the vector matrix
    repo.write("src/rates.py", "RATES = {}\n").commit("perf: cache exchange rates")
    index(repo.root)
    error, text = call(s, "search_history", {"query": "exchange rates"})
    store = s._open_store()  # pyright: ignore[reportPrivateUsage]
    assert store is not None
    ids, _ = store.cache["vectors"]  # type: ignore[misc]
    s.close()
    assert not error, text
    assert "perf: cache exchange rates" in text
    assert len(ids) == 8  # the new commit's vector is in the refreshed matrix


def test_fit_cuts_whole_lines() -> None:
    text = fit([f"line {i} " + "x" * 90 for i in range(200)])
    assert len(text) <= MAX_CHARS
    assert text.endswith("more lines cut to keep this short]")


def test_stdio_server_starts(make_repo: MakeRepo) -> None:
    repo = make_repo("lineage")
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "sprout", "mcp", "serve", "-C", str(repo.root)],
        env={**os.environ, "SPROUT_LLM_PROVIDER": "none"},
    )

    async def run() -> tuple[set[str], str]:
        async with Client(params) as client:
            names = {t.name for t in (await client.list_tools()).tools}
            result = await client.call_tool("why", {"target": "src/payments/core.py:2"})
            return names, result.content[0].text  # type: ignore[union-attr]

    names, text = asyncio.run(run())
    assert names == {"why", "search_history", "explain_commit"}
    assert "Basis: the top commit's message states the reason" in text


def test_explain_commit_shows_reason_reverts_and_files(make_repo: MakeRepo) -> None:
    repo = make_repo("revert")
    index(repo.root)
    s = Session(repo.root, OFFLINE)
    bad = repo.git("rev-parse", "HEAD~1").strip()
    error, bad_text = call(s, "explain_commit", {"commit": bad[:7]})
    _, revert_text = call(s, "explain_commit", {"commit": "HEAD"})
    s.close()
    assert not error, bad_text
    assert bad_text.startswith(f"commit {bad[:12]} ")
    assert f"REVERTED by {repo.head()[:12]}" in bad_text
    assert "Reason: the message does not state one; don't guess." in bad_text
    assert "  modified retry.py +1 -1" in bad_text
    assert "-RETRIES = 3" in bad_text
    assert f"This commit REVERTS {bad[:12]}." in revert_text


def test_explain_commit_reason_and_symbols(session: Session) -> None:
    error, text = call(session, "explain_commit", {"commit": "HEAD"})
    assert not error, text
    assert 'Reason, quoted from the message: "' in text
    assert "in verify_token" in text


def test_explain_unknown_commit(session: Session) -> None:
    error, text = call(session, "explain_commit", {"commit": "deadbeef"})
    assert error
    assert "Revision 'deadbeef' was not found. Fix: " in text
