"""End-to-end ``sprout why``."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

import pytest
from typer.testing import CliRunner

from sprout import services
from sprout.cli.app import app
from tests.fakes import FakeEmbedder, FakeReranker
from tests.fixtures.builder import RepoBuilder

MakeRepo = Callable[[str], RepoBuilder]
runner = CliRunner()


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(services, "build_answerer", lambda _s: (None, None))
    monkeypatch.setattr(services, "build_embedder", lambda _s: FakeEmbedder())
    monkeypatch.setattr(services, "build_reranker", lambda _s: FakeReranker())


def run(*args: str) -> tuple[int, str]:
    result = runner.invoke(app, list(args))
    return result.exit_code, result.output


def run_json(*args: str) -> Any:
    code, output = run(*args, "--json")
    assert code == 0, output
    return json.loads(output)


def test_why_line_json(make_repo: MakeRepo) -> None:
    root = str(make_repo("lineage").root)
    run_json("index", "-C", root)
    answer = run_json("why", "-C", root, "src/payments/core.py:2")
    assert answer["mode"] == "retrieval"
    assert answer["symbol"] == "charge"
    assert [h["introduced"] for h in answer["history"]] == [False, True]
    assert answer["evidence"][0]["role"] in {"line_origin", "line_history", "symbol_history"}


def test_why_line_human_output(make_repo: MakeRepo) -> None:
    root = str(make_repo("lineage").root)
    run_json("index", "-C", root)
    code, output = run("why", "-C", root, "src/payments/core.py:2")
    assert code == 0, output
    flat = re.sub(r"[│╭╮╰╯─\s]+", " ", output)
    assert "because the card network times out" in flat
    assert "Evidence" in output
    assert "this line" in output


def test_why_works_before_indexing(make_repo: MakeRepo) -> None:
    code, output = run("why", "-C", str(make_repo("lineage").root), "src/payments/core.py:2")
    assert code == 0, output
    assert "sprout index" in output


def test_why_question(make_repo: MakeRepo) -> None:
    root = str(make_repo("payments").root)
    run_json("index", "-C", root)
    answer = run_json("why", "-C", root, "why did we disable charge retries")
    assert answer["target"] == "why did we disable charge retries"
    assert answer["evidence"]


def test_question_needs_index(make_repo: MakeRepo) -> None:
    code, output = run("why", "-C", str(make_repo("payments").root), "why retries")
    assert code == 1
    assert "sprout index" in output


def test_unknown_file(make_repo: MakeRepo) -> None:
    code, output = run("why", "-C", str(make_repo("lineage").root), "nope.py:3")
    assert code == 1
    assert "No file named nope.py" in output


def test_line_out_of_range(make_repo: MakeRepo) -> None:
    code, output = run("why", "-C", str(make_repo("lineage").root), "src/payments/core.py:400")
    assert code == 1
    assert "Could not blame" in output
