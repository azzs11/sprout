"""End-to-end ``sprout risk``: advisory by default, exit 2 for security fixes or --strict."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

import pytest
from typer.testing import CliRunner

from sprout.cli.app import app
from tests.fixtures.builder import RepoBuilder

MakeRepo = Callable[[str], RepoBuilder]
runner = CliRunner()


def run(*args: str, stdin: str | None = None) -> tuple[int, str]:
    result = runner.invoke(app, list(args), input=stdin)
    return result.exit_code, result.output


@pytest.fixture
def shop(make_repo: MakeRepo) -> RepoBuilder:
    repo = make_repo("payments")
    code, output = run("index", "-C", str(repo.root), "--no-embed")
    assert code == 0, output
    return repo


def card(*args: str, stdin: str | None = None, expect: int = 0) -> Any:
    code, output = run("risk", *args, "--json", stdin=stdin)
    assert code == expect, output
    return json.loads(output)


def disable_retries(repo: RepoBuilder) -> None:
    path = repo.root / "src/payments.py"
    path.write_text(path.read_text().replace("RETRIES = 3", "RETRIES = 0"))


def test_reapplying_a_revert_warns_but_does_not_block(shop: RepoBuilder) -> None:
    disable_retries(shop)
    got = card("-C", str(shop.root))
    assert (got["level"], got["verdict"], got["method"]) == ("high", "stop", "risk@2")
    assert got["findings"][0]["kind"] == "reapplies_reverted"


def test_strict_blocks_any_warning(shop: RepoBuilder) -> None:
    disable_retries(shop)
    assert card("-C", str(shop.root), "--strict", expect=2)["level"] == "high"


def test_undoing_a_security_fix_blocks_without_strict(shop: RepoBuilder) -> None:
    undo = shop.git("show", "HEAD", "--format=", "-R")
    got = card("-C", str(shop.root), "--diff", "-", stdin=undo, expect=2)
    assert "security" in got["findings"][0]["labels"]


def test_staged_ignores_unstaged_changes(shop: RepoBuilder) -> None:
    disable_retries(shop)
    assert card("-C", str(shop.root), "--staged")["checked_lines"] == 0
    shop.stage("src/payments.py")
    assert card("-C", str(shop.root), "--staged")["level"] == "high"


def test_skip(shop: RepoBuilder, monkeypatch: pytest.MonkeyPatch) -> None:
    disable_retries(shop)
    monkeypatch.setenv("SPROUT_SKIP", "1")
    code, output = run("risk", "-C", str(shop.root), "--strict")
    assert code == 0
    assert "skipped (SPROUT_SKIP=1)" in output


def test_without_an_index(make_repo: MakeRepo) -> None:
    code, output = run("risk", "-C", str(make_repo("payments").root))
    assert code == 1
    assert "sprout index" in output


def test_human_card(shop: RepoBuilder) -> None:
    code, clean = run("risk", "-C", str(shop.root))
    assert (code, clean.strip()) == (0, "No changed lines to check.")
    disable_retries(shop)
    code, output = run("risk", "-C", str(shop.root))
    flat = re.sub(r"\s+", " ", output)
    assert code == 0, output
    assert "Risk: ▲ high (1 past commit warns against this change)" in flat
    assert "re-applies code this revert removed (2 of 2 lines)" in flat
    assert "+RETRIES = 0" in flat
    assert "it reverted " in flat


def test_unrelated_change_is_low(shop: RepoBuilder) -> None:
    (shop.root / "README.md").write_text("# shop\n\nA tiny payments demo for tests.\n")
    code, output = run("risk", "-C", str(shop.root))
    assert code == 0
    assert output.startswith("✓ low: none of the 1 changed lines match")
