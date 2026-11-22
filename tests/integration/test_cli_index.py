"""End-to-end ``sprout index`` and ``sprout search`` with faked models."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from sprout import services
from sprout.cli.app import app
from sprout.core.index.summarise import Summariser
from tests.fakes import FakeEmbedder, FakeProvider, FakeReranker
from tests.fixtures.builder import RepoBuilder

MakeRepo = Callable[[str], RepoBuilder]
runner = CliRunner()


@pytest.fixture(autouse=True)
def fake_provider(monkeypatch: pytest.MonkeyPatch) -> FakeProvider:
    provider = FakeProvider(reply="Summary text.")
    monkeypatch.setattr(services, "build_embedder", lambda _s: FakeEmbedder())
    monkeypatch.setattr(services, "build_reranker", lambda _s: FakeReranker())
    monkeypatch.setattr(services, "build_summariser", lambda _s: Summariser(provider))
    return provider


def run(*args: str) -> tuple[int, str]:
    result = runner.invoke(app, list(args))
    return result.exit_code, result.output


def run_json(*args: str) -> Any:
    code, output = run(*args, "--json")
    assert code == 0, output
    return json.loads(output)


def test_index_then_search(make_repo: MakeRepo) -> None:
    root = str(make_repo("payments").root)
    stats = run_json("index", "-C", root)
    assert (stats["commits"], stats["embedded"], stats["reverts"]) == (7, 7, 1)
    results = run_json("search", "-C", root, "constant time token compare", "-n", "3")
    assert results["reranked"]
    assert len(results["hits"]) == 3
    assert results["hits"][0]["commit"]["summary"].startswith("fix(auth): compare tokens")


def test_human_output(make_repo: MakeRepo) -> None:
    root = str(make_repo("payments").root)
    code, output = run("index", "-C", root)
    assert code == 0, output
    assert "commits" in output
    code, output = run("search", "-C", root, "disable charge retries", "--mode", "bm25")
    assert code == 0
    assert "reverted" in output


def test_search_without_index(make_repo: MakeRepo) -> None:
    code, output = run("search", "-C", str(make_repo("linear").root), "anything")
    assert code == 1
    assert "sprout index" in output


def test_index_empty_repo(make_repo: MakeRepo) -> None:
    code, output = run("index", "-C", str(make_repo("empty").root))
    assert code == 1
    assert "first commit" in output


def test_summarise_and_limit(make_repo: MakeRepo, fake_provider: FakeProvider) -> None:
    root = str(make_repo("payments").root)
    stats = run_json("index", "-C", root, "--summarise", "--summary-limit", "3", "--no-embed")
    assert stats["summarised"] == 3
    assert stats["embedded"] == 0
    assert len(fake_provider.prompts) == 3


@pytest.mark.parametrize(("since", "ok"), [("1y", True), ("2024-01-01", True), ("soon", False)])
def test_since_values(make_repo: MakeRepo, since: str, ok: bool) -> None:
    code, output = run("index", "-C", str(make_repo("linear").root), "--since", since)
    assert (code == 0) is ok, output


def test_rebuild(make_repo: MakeRepo) -> None:
    root = make_repo("payments").root
    run_json("index", "-C", str(root))
    stats = run_json("index", "-C", str(root), "--rebuild", "--no-embed")
    assert (stats["commits"], stats["embedded"]) == (7, 0)


def test_ctrl_c_message(make_repo: MakeRepo, monkeypatch: pytest.MonkeyPatch) -> None:
    import sprout.cli.index as cli_index

    def interrupted(*_a: object, **_k: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_index, "build_index", interrupted)
    code, output = run("index", "-C", str(make_repo("linear").root))
    assert code == 130
    assert "run sprout index again" in output


def test_bare_sprout_shows_index_line(make_repo: MakeRepo, monkeypatch: pytest.MonkeyPatch) -> None:
    root: Path = make_repo("payments").root
    monkeypatch.chdir(root)
    assert "sprout index" in run()[1]
    run_json("index")
    assert "Index: 7 commits, 7 embedded" in run()[1]
