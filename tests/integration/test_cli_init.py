"""End-to-end ``sprout init`` and ``sprout uninstall``."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from sprout import services
from sprout.cli import setup
from sprout.cli.app import app
from sprout.core.setup.background import start_index
from tests.fakes import FakeEmbedder
from tests.fixtures.builder import RepoBuilder

MakeRepo = Callable[[str], RepoBuilder]
runner = CliRunner()


@pytest.fixture(autouse=True)
def started(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Fake models, and record background indexer starts instead of spawning them."""
    calls: list[Path] = []
    monkeypatch.setattr(services, "build_embedder", lambda _s: FakeEmbedder())
    monkeypatch.setattr(services, "describe_answers", lambda _s: "Facts only (test).")
    monkeypatch.setattr(setup, "start_index", lambda root: calls.append(root) or root / "log")
    return calls


def run(*args: str) -> tuple[int, str]:
    result = runner.invoke(app, list(args))
    return result.exit_code, result.output


def run_json(*args: str) -> Any:
    code, output = run(*args, "--json")
    assert code == 0, output
    return json.loads(output)


def test_init_indexes_configures_and_backgrounds_vectors(
    make_repo: MakeRepo, started: list[Path]
) -> None:
    repo = make_repo("payments")
    report = run_json("init", "-C", str(repo.root))
    assert report["stats"]["commits"] == 7
    assert report["stats"]["embedded"] == 0  # structure only in the foreground
    assert report["embedding"] == "background"
    assert started == [repo.root.resolve()]
    assert [c["action"] for c in report["configs"]] == ["added"]
    assert json.loads((repo.root / ".mcp.json").read_text())["mcpServers"]["sprout"]["args"][
        -2:
    ] == [
        "mcp",
        "serve",
    ]
    reverted = [r["reverted_summary"] for r in report["recent_reverts"]]
    assert reverted == ["perf(payments): disable charge retries to cut latency"]
    assert repo.git("status", "--porcelain") == "?? .mcp.json"


def test_init_wait_embeds_now_and_rerun_changes_nothing(
    make_repo: MakeRepo, started: list[Path]
) -> None:
    repo = make_repo("lineage")
    report = run_json("init", "-C", str(repo.root), "--wait", "-a", "claude", "-a", "cursor")
    assert report["embedding"] == "done"
    assert report["stats"]["embedded"] == report["stats"]["commits"]
    again = run_json("init", "-C", str(repo.root), "-a", "claude", "-a", "cursor")
    assert [c["action"] for c in again["configs"]] == ["unchanged", "unchanged"]
    assert again["embedding"] == "done"
    assert started == []


def test_init_no_embed(make_repo: MakeRepo, started: list[Path]) -> None:
    report = run_json("init", "-C", str(make_repo("linear").root), "--no-embed")
    assert report["embedding"] == "skipped"
    assert started == []


def test_init_before_the_first_commit_still_configures(make_repo: MakeRepo) -> None:
    repo = make_repo("empty")
    report = run_json("init", "-C", str(repo.root))
    assert report["stats"] is None
    assert any("No commits yet" in n for n in report["notes"])
    assert (repo.root / ".mcp.json").exists()


def test_init_human_output(make_repo: MakeRepo) -> None:
    code, output = run("init", "-C", str(make_repo("payments").root))
    assert code == 0, output
    assert "Indexed 7 commits (1 reverts) in .sprout/." in output
    assert "added Sprout to .mcp.json" in output
    assert "Recent reverts Sprout will warn about:" in output
    assert "Answers: Facts only (test)." in output


def test_init_refuses_bare_repositories(make_repo: MakeRepo, tmp_path: Path) -> None:
    repo = make_repo("linear")
    bare = tmp_path / "bare.git"
    repo.git("clone", "--bare", str(repo.root), str(bare))
    code, output = run("init", "-C", str(bare))
    assert code == 1
    assert "bare repository" in output


def test_bad_config_is_left_alone(make_repo: MakeRepo) -> None:
    repo = make_repo("linear")
    (repo.root / ".mcp.json").write_text("{ not json")
    code, output = run("init", "-C", str(repo.root))
    assert code == 1
    assert "not plain JSON" in output
    assert (repo.root / ".mcp.json").read_text() == "{ not json"


def test_uninstall_undoes_init(make_repo: MakeRepo) -> None:
    repo = make_repo("payments")
    run_json("init", "-C", str(repo.root), "-a", "claude", "-a", "vscode")
    (repo.root / ".sprout.toml").write_text('llm_provider = "none"\n')
    report = run_json("uninstall", "-C", str(repo.root))
    assert report["index_removed"]
    assert {c["path"]: c["action"] for c in report["configs"]} == {
        ".mcp.json": "deleted_file",
        ".cursor/mcp.json": "absent",
        ".vscode/mcp.json": "deleted_file",
    }
    assert any(".sprout.toml" in n for n in report["notes"])
    assert repo.git("status", "--porcelain") == "?? .sprout.toml"


def test_uninstall_keep_index(make_repo: MakeRepo) -> None:
    repo = make_repo("linear")
    run_json("init", "-C", str(repo.root))
    code, output = run("uninstall", "-C", str(repo.root), "--keep-index")
    assert code == 0, output
    assert "deleted .mcp.json" in output
    assert "kept .sprout/" in output
    assert (repo.root / ".sprout/index.db").exists()


def test_background_indexer_runs_detached(
    make_repo: MakeRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repo("linear")
    monkeypatch.setenv("SPROUT_EMBED_MODEL", "none")  # inherited by the child: no model download
    log = start_index(repo.root)
    deadline = time.monotonic() + 60
    while '"commits"' not in (log.read_text() if log.exists() else ""):
        assert time.monotonic() < deadline, log.read_text() if log.exists() else "no log"
        time.sleep(0.2)
    stats = json.loads(log.read_text()[log.read_text().index("{") :])
    assert stats["commits"] == 3
    assert log.parent.samefile(repo.root / ".sprout")
