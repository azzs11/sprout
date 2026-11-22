"""End-to-end tests of the ``sprout`` CLI on fixture repositories."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from syrupy.assertion import SnapshotAssertion
from typer.testing import CliRunner

from sprout import __version__
from sprout.cli.app import app
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


def test_version() -> None:
    code, output = run("--version")
    assert code == 0
    assert output.strip() == f"sprout {__version__}"


def test_bare_invocation_shows_help() -> None:
    code, output = run()
    assert code == 0
    for command in ("status", "diff", "history"):
        assert command in output


# ----- the Phase 1 acceptance case: status in an empty repo -------------------------


def test_status_in_empty_repo(make_repo: MakeRepo) -> None:
    root = make_repo("empty").root
    code, output = run("status", "-C", str(root))
    assert code == 0, output
    assert "no commits yet" in output
    assert "working tree clean" in output


def test_history_in_empty_repo(make_repo: MakeRepo) -> None:
    code, output = run("history", "-C", str(make_repo("empty").root))
    assert code == 0
    assert "No commits yet" in output


# ----- human output ---------------------------------------------------------------


def test_status_lists_sections(make_repo: MakeRepo) -> None:
    code, output = run("status", "-C", str(make_repo("unborn_with_changes").root))
    assert code == 0
    assert "Staged" in output
    assert "staged.txt" in output
    assert "Untracked" in output


def test_history_table(make_repo: MakeRepo) -> None:
    code, output = run("history", "-C", str(make_repo("linear").root), "-n", "2")
    assert code == 0
    assert "fix: return 2 from main" in output
    assert "feat: add app" not in output


def test_history_path_argument(make_repo: MakeRepo) -> None:
    root = make_repo("linear").root
    data = run_json("history", "-C", str(root), "README.md")
    assert data["path"] == "README.md"
    assert [c["summary"] for c in data["commits"]] == ["docs: add readme"]


def test_diff_shows_patch_and_stat(make_repo: MakeRepo) -> None:
    built = make_repo("linear")
    built.write("app.py", "def main():\n    return 9\n")
    code, output = run("diff", "-C", str(built.root))
    assert code == 0
    assert "app.py" in output
    assert "return 9" in output
    code, output = run("diff", "-C", str(built.root), "--stat")
    assert "1 file" in output
    assert "return 9" not in output


def test_diff_without_changes(make_repo: MakeRepo) -> None:
    code, output = run("diff", "-C", str(make_repo("linear").root))
    assert code == 0
    assert "No unstaged changes" in output


def test_binary_diff_is_not_printed(make_repo: MakeRepo) -> None:
    built = make_repo("binary")
    built.write("logo.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\x09")
    code, output = run("diff", "-C", str(built.root))
    assert code == 0
    assert "binary file" in output


# ----- errors ---------------------------------------------------------------------


def test_not_a_repository_shows_fix(tmp_path: Path) -> None:
    code, output = run("status", "-C", str(tmp_path))
    assert code == 1
    assert "No git repository" in output
    assert "git init" in output


def test_not_a_repository_json(tmp_path: Path) -> None:
    code, output = run("status", "-C", str(tmp_path), "--json")
    assert code == 1
    data = json.loads(output)
    assert "git init" in data["hint"]


def test_unknown_revision(make_repo: MakeRepo) -> None:
    code, output = run("history", "-C", str(make_repo("linear").root), "--rev", "nope")
    assert code == 1
    assert "not found" in output


# ----- JSON snapshots (hashes are deterministic thanks to fixed dates) --------------


def test_history_json_snapshot(make_repo: MakeRepo, snapshot: SnapshotAssertion) -> None:
    assert run_json("history", "-C", str(make_repo("merge").root)) == snapshot


def test_status_json_snapshot(make_repo: MakeRepo, snapshot: SnapshotAssertion) -> None:
    data = run_json("status", "-C", str(make_repo("unborn_with_changes").root))
    data.pop("root")
    assert data == snapshot


def test_staged_diff_json_snapshot(make_repo: MakeRepo, snapshot: SnapshotAssertion) -> None:
    built = make_repo("renames")
    built.move("new/place.py", "final/spot.py")
    assert run_json("diff", "-C", str(built.root), "--staged") == snapshot
