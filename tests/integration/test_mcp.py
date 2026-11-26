"""The MCP server, driven through the official SDK client (in-process and over stdio)."""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from mcp import Client, StdioServerParameters
from typer.testing import CliRunner

from sprout import services
from sprout.cli.app import app
from sprout.cli.mcp import _is_loopback  # pyright: ignore[reportPrivateUsage]
from sprout.config import Settings
from sprout.core.risk import acks
from sprout.mcp.format import MAX_CHARS, fit
from sprout.mcp.server import build_server
from sprout.mcp.session import Session
from sprout.models import Ack, AckKind
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
    assert set(tools) == {
        "why", "search_history", "explain_commit", "check_edit", "suggest_commit_message"
    }  # fmt: skip
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
    assert names == {
        "why",
        "search_history",
        "explain_commit",
        "check_edit",
        "suggest_commit_message",
    }
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


@pytest.mark.parametrize(
    ("host", "loopback"),
    [
        ("127.0.0.1", True),
        ("::1", True),
        ("localhost", True),
        ("0.0.0.0", False),  # noqa: S104 - a test value, not a bind
        ("example.com", False),
    ],
)
def test_loopback_hosts(host: str, loopback: bool) -> None:
    assert _is_loopback(host) is loopback


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_http_server(make_repo: MakeRepo) -> None:
    repo = make_repo("lineage")
    port = _free_port()
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "sprout",
            "mcp",
            "serve",
            "--http",
            "--port",
            str(port),
            "-C",
            str(repo.root),
        ],
        env={**os.environ, "SPROUT_LLM_PROVIDER": "none"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                assert proc.poll() is None, proc.stderr.read() if proc.stderr else ""
                assert time.monotonic() < deadline, "server did not start"
                time.sleep(0.1)

        async def run() -> str:
            async with Client(f"http://127.0.0.1:{port}/mcp") as client:
                result = await client.call_tool("why", {"target": "src/payments/core.py:2"})
                return result.content[0].text  # type: ignore[union-attr]

        assert "Basis: the top commit's message states the reason" in asyncio.run(run())
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_why_shows_unchecked_message_body_without_calling_it_a_reason(session: Session) -> None:
    # Found by asking Claude Code through this server: the body held the real context but no
    # causal word, so the agent was told nothing about it.
    error, text = call(session, "why", {"target": "src/payments.py:5"})
    assert not error, text
    assert "clearest stated reason" not in text
    assert "Basis: no commit message states a reason Sprout's check accepts." in text
    assert 'message (not checked as a reason): "The card network drops ~1% of requests."' in text


# ----- check_edit -----------------------------------------------------------------------


def test_check_edit_stops_a_reapplied_revert(session: Session) -> None:
    error, text = call(
        session,
        "check_edit",
        {"path": "src/payments.py", "old": "    RETRIES = 3", "new": "    RETRIES = 0"},
    )
    assert not error, text
    assert text.startswith("check_edit: STOP (level: high; risk@2, no model;")
    assert "1 past commit warns" in text
    assert "re-applies code that this revert removed (2 of 2 lines):" in text
    assert "    +RETRIES = 0" in text
    assert "  it reverted " in text
    assert text.splitlines()[-1].startswith("What to do: stop and ask the user")


def test_check_edit_review_suggests_reading_the_commit(session: Session) -> None:
    error, text = call(
        session,
        "check_edit",
        {"path": "src/payments.py", "old": "    RETRIES = 3", "new": "    RETRIES = 4"},
    )
    assert not error, text
    assert text.startswith("check_edit: REVIEW (level: review;")
    assert "removes code that this revert restored" in text
    assert "What to do: read the cited commit with explain_commit." in text


def test_check_edit_whole_file_diff_and_uncommitted(session: Session) -> None:
    root = session.repo.root
    undone = "def verify_token(token):\n    return token.startswith('t_')\n"
    _, whole = call(session, "check_edit", {"path": str(root / "src/auth.py"), "new": undone})
    assert whole.startswith("check_edit: STOP")
    assert "security" in whole
    diff = "--- a/src/payments.py\n+++ b/src/payments.py\n@@ -2 +2 @@\n-    RETRIES = 3\n+    RETRIES = 0\n"
    _, from_diff = call(session, "check_edit", {"diff": diff})
    assert from_diff.startswith("check_edit: STOP")
    path = root / "src/payments.py"
    path.write_text(path.read_text().replace("RETRIES = 3", "RETRIES = 0"))
    _, uncommitted = call(session, "check_edit", {})
    assert uncommitted.startswith("check_edit: STOP")


def test_check_edit_proceeds_and_honours_acks(session: Session) -> None:
    _, text = call(session, "check_edit", {"path": "README.md", "old": "# shop", "new": "# Shop"})
    assert text.startswith("check_edit: PROCEED (risk@2, no model). None of the")
    root = session.repo.root
    revert = subprocess.run(
        ["git", "-C", str(root), "log", "-1", "--format=%H", "--grep=^Revert"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    acks.save(
        root, [Ack(commit=revert, kind=AckKind.ACK, reason="ok", by="Ada", date="2026-11-25")]
    )
    _, acked = call(
        session,
        "check_edit",
        {"path": "src/payments.py", "old": "    RETRIES = 3", "new": "    RETRIES = 0"},
    )
    assert acked.startswith("check_edit: PROCEED")
    assert "Note: 1 finding hidden by .sprout-acks.toml." in acked


def test_check_edit_errors(session: Session, make_repo: MakeRepo) -> None:
    error, text = call(session, "check_edit", {"path": "src/payments.py"})
    assert error
    assert "Fix: Pass path and new" in text
    error, text = call(session, "check_edit", {"path": "/etc/hosts", "new": "x"})
    assert error
    assert "outside the repository" in text
    plain = Session(make_repo("linear").root, OFFLINE)
    error, text = call(plain, "check_edit", {})
    plain.close()
    assert error
    assert "Fix: Build it with: sprout index" in text


def test_suggest_commit_message_asks_for_the_users_reason(session: Session) -> None:
    root = session.repo.root
    text = (root / "src/payments.py").read_text()
    (root / "src/payments.py").write_text(text.replace("RETRIES = 3", "RETRIES = 5"))
    error, out = call(session, "suggest_commit_message", {})
    assert not error, out
    assert out.startswith("suggest_commit_message (no model; Sprout never commits).")
    assert "Style: Conventional Commits, types: " in out
    assert "- feat(payments): retry failed charges three times" in out
    assert "the subject is a placeholder" in out
    assert "perf(payments): update payments.py" in out
    assert "Never invent a reason." in out
    assert "Note: Nothing is staged" in out
    assert "Written without a model" not in out


def test_suggest_commit_message_with_why_and_a_hand_revert(session: Session) -> None:
    root = session.repo.root
    (root / "src/auth.py").write_text(
        "def verify_token(token):\n    return bool(token) and token.startswith('t_')\n"
    )
    subprocess.run(["git", "-C", str(root), "add", "src/auth.py"], check=True)
    why = "The hmac call rejected every valid token in production."
    error, out = call(session, "suggest_commit_message", {"why": why, "fixes": [51]})
    assert not error, out
    assert "keep the Revert subject" in out
    lines = out.splitlines()
    assert 'Revert "fix(auth): compare tokens in constant time to prevent timing attacks"' in lines
    assert f"Why: {why}" in lines
    assert "Fixes: #51" in lines
    assert any(line.startswith("Reverts: ") for line in lines)
    assert "Never invent" not in out


def test_suggest_commit_message_without_changes(session: Session) -> None:
    error, out = call(session, "suggest_commit_message", {})
    assert error
    assert "git add" in out
