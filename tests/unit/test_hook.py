"""``sprout-hook``: agent and pre-commit checks, fail-open behaviour, and the git hook installer."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from sprout import hook, hook_checks
from sprout.core.git import open_repo
from sprout.core.index.indexer import build_index
from sprout.core.index.store import Store
from sprout.core.risk.edits import edit_lines, line_of
from sprout.core.setup import git_hook
from sprout.errors import SproutError
from sprout.models import ConfigAction
from tests.fixtures.builder import RepoBuilder

MakeRepo = Callable[[str], RepoBuilder]
UNDO_SECURITY = {
    "old_string": "import hmac\n\ndef verify_token(token):\n    return hmac.compare_digest(token[:2], 't_')",
    "new_string": "def verify_token(token):\n    return token.startswith('t_')",
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("SPROUT_SKIP", "SPROUT_RISK_LEVEL", "SPROUT_STRICT", "SPROUT_DEBUG"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def shop(make_repo: MakeRepo) -> RepoBuilder:
    repo = make_repo("payments")
    with Store.open(repo.root, create=True) as store:
        build_index(open_repo(repo.root), store)
    return repo


def run_agent(event: dict[str, Any]) -> dict[str, Any] | None:
    out = io.StringIO()
    assert hook.wants(event)
    assert hook_checks.agent(event, out) == 0
    return json.loads(out.getvalue())["hookSpecificOutput"] if out.getvalue() else None


def edit(repo: RepoBuilder, path: str, old: str, new: str, tool: str = "Edit") -> dict[str, Any]:
    return {
        "tool_name": tool,
        "cwd": str(repo.root),
        "tool_input": {"file_path": str(repo.root / path), "old_string": old, "new_string": new},
    }


# ----- edits to changed lines ---------------------------------------------------------


def test_edit_lines() -> None:
    got = edit_lines("a.py", "x = 1\nRETRIES = 3\ny = 2", "x = 1\nRETRIES = 0\ny = 2", start=10)
    assert [(c.added, c.text, c.line) for c in got] == [
        (False, "RETRIES = 3", 11),
        (True, "RETRIES = 0", 11),
    ]
    assert [c.added for c in edit_lines("a.py", "", "new line here")] == [True]


def test_line_of() -> None:
    assert line_of("a\nb\nRETRIES = 3\n", "RETRIES = 3") == 3
    assert line_of("a\nb\n", "missing") == 1


# ----- agent hook ---------------------------------------------------------------------


def test_reapplying_a_revert_asks_the_user(shop: RepoBuilder) -> None:
    out = run_agent(edit(shop, "src/payments.py", "    RETRIES = 3", "    RETRIES = 0"))
    assert out is not None
    assert out["hookEventName"] == "PreToolUse"
    assert out["permissionDecision"] == "ask"
    assert "re-applies code that this revert removed" in out["permissionDecisionReason"]
    assert out["additionalContext"] == out["permissionDecisionReason"]


def test_a_review_finding_is_a_note_not_an_interruption(shop: RepoBuilder) -> None:
    out = run_agent(edit(shop, "src/payments.py", "    RETRIES = 3", "    RETRIES = 4"))
    assert out is not None
    assert out["permissionDecision"] == "allow"
    assert "removes code that this revert restored" in out["additionalContext"]
    assert "permissionDecisionReason" not in out


def test_level_high_hides_review_findings(
    shop: RepoBuilder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SPROUT_RISK_LEVEL", "high")
    assert run_agent(edit(shop, "src/payments.py", "    RETRIES = 3", "    RETRIES = 4")) is None


def test_strict_denies_high_findings(shop: RepoBuilder, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPROUT_STRICT", "1")
    out = run_agent(
        edit(shop, "src/auth.py", UNDO_SECURITY["old_string"], UNDO_SECURITY["new_string"])
    )
    assert out is not None
    assert out["permissionDecision"] == "deny"
    assert "[security]" in out["permissionDecisionReason"]


def test_multiedit_and_write(shop: RepoBuilder) -> None:
    multi = {
        "tool_name": "MultiEdit",
        "cwd": str(shop.root),
        "tool_input": {
            "file_path": str(shop.root / "src/payments.py"),
            "edits": [{"old_string": "    RETRIES = 3", "new_string": "    RETRIES = 0"}],
        },
    }
    assert (run_agent(multi) or {})["permissionDecision"] == "ask"
    undone = "def verify_token(token):\n    return bool(token) and token.startswith('t_')\n"
    write = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(shop.root / "src/auth.py"), "content": undone},
    }
    out = run_agent(write)
    assert out is not None
    assert "-import hmac" in out["additionalContext"]


def test_unrelated_edits_are_silent(shop: RepoBuilder) -> None:
    assert run_agent(edit(shop, "README.md", "# shop", "# shop\n\nA small shop for tests.")) is None


def test_no_index_or_other_tools_skip_before_importing_git(
    make_repo: MakeRepo, tmp_path: Path
) -> None:
    plain = make_repo("payments")
    assert not hook.wants(edit(plain, "src/payments.py", "a", "b"))
    assert not hook.wants({"tool_name": "Read", "tool_input": {"file_path": str(plain.root / "x")}})
    assert not hook.wants({"tool_name": "Edit", "tool_input": "nope"})
    assert hook.indexed_root(tmp_path) is None


def test_main_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    assert hook.main(["agent"]) == 0
    assert hook.main([]) == 0
    monkeypatch.setenv("SPROUT_SKIP", "1")
    assert hook.main(["pre-commit"]) == 0


def test_errors_are_silent_unless_debugging(
    shop: RepoBuilder, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(*_args: object) -> int:
        raise RuntimeError("index unreadable")

    monkeypatch.setattr(hook_checks, "agent", boom)
    event = json.dumps(edit(shop, "src/payments.py", "    RETRIES = 3", "    RETRIES = 0"))
    monkeypatch.setattr(sys, "stdin", io.StringIO(event))
    assert hook.main(["agent"]) == 0
    assert capsys.readouterr().err == ""
    monkeypatch.setenv("SPROUT_DEBUG", "1")
    monkeypatch.setattr(sys, "stdin", io.StringIO(event))
    assert hook.main(["agent"]) == 0
    assert "RuntimeError: index unreadable" in capsys.readouterr().err


# ----- pre-commit ---------------------------------------------------------------------


def test_pre_commit_warns_without_blocking(
    shop: RepoBuilder, capsys: pytest.CaptureFixture[str]
) -> None:
    path = shop.root / "src/payments.py"
    path.write_text(path.read_text().replace("RETRIES = 3", "RETRIES = 0"))
    shop.stage("src/payments.py")
    assert hook_checks.pre_commit(shop.root) == 0
    err = capsys.readouterr().err
    assert "Sprout: history warns about this commit (advisory)." in err
    assert err.strip().endswith("Committing anyway.")


def test_pre_commit_blocks_undoing_a_security_fix(
    shop: RepoBuilder, capsys: pytest.CaptureFixture[str]
) -> None:
    (shop.root / "src/auth.py").write_text(
        "def verify_token(token):\n    return token.startswith('t_')\n"
    )
    shop.stage("src/auth.py")
    assert hook_checks.pre_commit(shop.root) == 2
    err = capsys.readouterr().err
    assert "Commit stopped: it undoes a past security fix." in err
    assert "git commit --no-verify" in err


# ----- git hook installer -------------------------------------------------------------


def test_install_is_idempotent_and_removable(shop: RepoBuilder) -> None:
    first = git_hook.install(shop.root)
    path = Path(first.path)
    assert first.action is ConfigAction.ADDED
    assert os.access(path, os.X_OK) or os.name == "nt"
    assert git_hook.MARKER in path.read_text()
    assert git_hook.install(shop.root).action is ConfigAction.UNCHANGED
    assert git_hook.remove(shop.root).action is ConfigAction.DELETED_FILE
    assert not path.exists()
    assert git_hook.remove(shop.root).action is ConfigAction.ABSENT


def test_never_overwrites_another_hook(shop: RepoBuilder) -> None:
    path = git_hook.hook_path(shop.root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\necho mine\n")
    with pytest.raises(SproutError, match="was not written by Sprout"):
        git_hook.install(shop.root)
    assert git_hook.remove(shop.root).action is ConfigAction.ABSENT
    assert path.read_text() == "#!/bin/sh\necho mine\n"


def test_honours_core_hooks_path(shop: RepoBuilder) -> None:
    shop.git("config", "core.hooksPath", ".githooks")
    assert git_hook.install(shop.root).path == str(shop.root / ".githooks" / "pre-commit")


@pytest.mark.skipif(os.name == "nt", reason="git runs hooks through sh; covered on Unix")
def test_real_git_commit_runs_the_hook(shop: RepoBuilder) -> None:
    git_hook.install(shop.root, python=sys.executable)
    (shop.root / "src/auth.py").write_text(
        "def verify_token(token):\n    return token.startswith('t_')\n"
    )
    shop.stage("src/auth.py")
    env = {
        **os.environ,
        "PATH": os.defpath,
    }  # no sprout-hook on PATH: the fallback interpreter runs
    blocked = subprocess.run(
        ["git", "-C", str(shop.root), "commit", "-m", "simplify auth"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert blocked.returncode != 0
    assert "undoes a past security fix" in blocked.stderr
    skipped = subprocess.run(
        ["git", "-C", str(shop.root), "commit", "-m", "simplify auth"],
        capture_output=True,
        text=True,
        env={**env, "SPROUT_SKIP": "1"},
    )
    assert skipped.returncode == 0, skipped.stderr
