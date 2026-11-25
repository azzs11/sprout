"""End-to-end ``sprout ack`` and ``sprout supersede``, and their effect on risk checks and hooks."""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from typing import Any

import pytest
from typer.testing import CliRunner

from sprout import hook_checks
from sprout.cli.app import app
from sprout.core.risk.acks import ACK_FILE
from tests.fixtures.builder import RepoBuilder

MakeRepo = Callable[[str], RepoBuilder]
runner = CliRunner()


def run(*args: str) -> tuple[int, str]:
    result = runner.invoke(app, list(args))
    return result.exit_code, result.output


def run_json(*args: str) -> Any:
    code, output = run(*args, "--json")
    assert code == 0, output
    return json.loads(output)


@pytest.fixture
def shop(make_repo: MakeRepo) -> RepoBuilder:
    repo = make_repo("payments")
    repo.git("config", "user.name", "Ada Lovelace")  # never the machine's global git identity
    assert run("index", "-C", str(repo.root), "--no-embed")[0] == 0
    path = repo.root / "src/payments.py"
    path.write_text(path.read_text().replace("RETRIES = 3", "RETRIES = 0"))
    return repo


def revert_of(repo: RepoBuilder) -> str:
    return repo.git("log", "-1", "--format=%H", "--grep=^Revert").strip()


def test_ack_needs_a_reason(shop: RepoBuilder) -> None:
    code, output = run("ack", revert_of(shop)[:7], "-C", str(shop.root))
    assert code == 1
    assert "Say why the warning no longer applies." in output
    assert not (shop.root / ACK_FILE).exists()


def test_ack_hides_the_warning_and_remove_restores_it(shop: RepoBuilder) -> None:
    root, revert = str(shop.root), revert_of(shop)
    assert run_json("risk", "-C", root)["level"] == "high"
    listing = run_json("ack", revert[:7], "-m", "Retries live in the HTTP client now.", "-C", root)
    assert [(a["commit"], a["kind"], a["by"]) for a in listing["acks"]] == [
        (revert, "ack", "Ada Lovelace")
    ]
    card = run_json("risk", "-C", root)
    assert (card["level"], card["notes"]) == ("low", ["1 finding hidden by .sprout-acks.toml."])
    assert (
        run_json("ack", "-C", root)["acks"][0]["reason"] == "Retries live in the HTTP client now."
    )
    assert run_json("ack", revert, "--remove", "-C", root)["acks"] == []
    assert not (shop.root / ACK_FILE).exists()
    assert run_json("risk", "-C", root)["level"] == "high"


def test_supersede_records_the_replacement(shop: RepoBuilder) -> None:
    root = str(shop.root)
    got = run_json("supersede", revert_of(shop), "-m", "Redesigned", "--by", "HEAD", "-C", root)
    [entry] = got["acks"]
    assert entry["kind"] == "supersede"
    assert entry["superseded_by"] == shop.head()
    code, output = run("ack", "-C", root)
    assert code == 0
    assert "replaced by" in output


def test_refuses_commits_sprout_never_cites(shop: RepoBuilder) -> None:
    feature = shop.git("log", "--format=%H", "--grep=^feat(auth)").strip()
    code, output = run("ack", feature, "-m", "x", "-C", str(shop.root))
    assert code == 1
    assert "is not a fix, security or revert commit" in output


def test_agent_hook_respects_acks(shop: RepoBuilder) -> None:
    shop.git("checkout", "--", "src/payments.py")  # back to RETRIES = 3; the agent sets it to 0
    event = {
        "tool_name": "Edit",
        "cwd": str(shop.root),
        "tool_input": {
            "file_path": str(shop.root / "src/payments.py"),
            "old_string": "    RETRIES = 3",
            "new_string": "    RETRIES = 0",
        },
    }
    before = io.StringIO()
    hook_checks.agent(event, before)
    assert json.loads(before.getvalue())["hookSpecificOutput"]["permissionDecision"] == "ask"
    run_json("ack", revert_of(shop), "-m", "Accepted", "-C", str(shop.root))
    after = io.StringIO()
    assert hook_checks.agent(event, after) == 0
    assert after.getvalue() == ""
