"""End-to-end ``sprout commit``: prints a message, never commits."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sprout import services
from sprout.cli.app import app
from sprout.core.commit.writer import CommitWriter
from tests.fakes import FakeProvider
from tests.fixtures.builder import PAYMENTS_V1, RepoBuilder

MakeRepo = Callable[[str], RepoBuilder]
runner = CliRunner()
REPLY = json.dumps(
    {
        "type": "fix",
        "scope": "payments",
        "description": "raise charge retries to five",
        "body": None,
        "question": "Why does charge() need five retries?",
    }
)


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> FakeProvider:
    fake = FakeProvider(reply=REPLY)
    monkeypatch.setattr(services, "build_commit_writer", lambda _s: (CommitWriter(fake), None))
    return fake


def _staged(make_repo: MakeRepo) -> RepoBuilder:
    repo = make_repo("payments")
    repo.write("src/payments.py", PAYMENTS_V1.replace("RETRIES = 3", "RETRIES = 5"))
    return repo.stage("src/payments.py")


def test_piped_output_is_the_bare_message(make_repo: MakeRepo, provider: FakeProvider) -> None:
    repo = _staged(make_repo)
    head = repo.head()
    result = runner.invoke(app, ["commit", "-C", str(repo.root), "--why", "Peaks drop 3%."])
    assert result.exit_code == 0, result.output
    assert result.stdout == "fix(payments): raise charge retries to five\n\nWhy: Peaks drop 3%.\n"
    assert repo.head() == head  # never commits
    assert provider.prompts


def test_ask_adds_the_answer_without_a_second_model_call(
    make_repo: MakeRepo, provider: FakeProvider, tmp_path: Path
) -> None:
    repo = _staged(make_repo)
    out = tmp_path / "msg.txt"
    args = ["commit", "-C", str(repo.root), "--ask", "-o", str(out), "--fixes", "7"]
    result = runner.invoke(app, args, input="The card network drops ~3% at peak.\n")
    assert result.exit_code == 0, result.output
    assert "Why does charge() need five retries?" in result.output
    assert out.read_text().endswith("Why: The card network drops ~3% at peak.\nFixes: #7\n")
    assert f"git commit -F {out}" in result.output
    assert len(provider.prompts) == 1


def test_skipping_the_question(make_repo: MakeRepo, provider: FakeProvider) -> None:
    repo = _staged(make_repo)
    result = runner.invoke(app, ["commit", "-C", str(repo.root), "--ask"], input="\n")
    assert result.exit_code == 0, result.output
    assert "Why:" not in result.stdout.split("?", 1)[-1]
    assert provider.prompts


def test_json_and_no_llm(make_repo: MakeRepo, provider: FakeProvider) -> None:
    repo = _staged(make_repo)
    result = runner.invoke(app, ["commit", "-C", str(repo.root), "--no-llm", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["source"] == "skeleton"
    assert data["subject"] == "perf(payments): update payments.py"
    assert not provider.prompts


@pytest.mark.usefixtures("provider")
def test_nothing_staged_is_an_error(make_repo: MakeRepo) -> None:
    repo = make_repo("payments")
    result = runner.invoke(app, ["commit", "-C", str(repo.root), "--json"])
    assert result.exit_code == 1
    assert "git add" in json.loads(result.stdout)["hint"]


@pytest.mark.usefixtures("provider")
def test_merge_in_progress_is_noted(make_repo: MakeRepo) -> None:
    repo = _staged(make_repo)
    (repo.root / ".git" / "MERGE_HEAD").write_text(repo.head() + "\n")
    result = runner.invoke(app, ["commit", "-C", str(repo.root), "--json", "--why", "x y z"])
    assert result.exit_code == 0, result.output
    assert any("merge is in progress" in n for n in json.loads(result.stdout)["notes"])
