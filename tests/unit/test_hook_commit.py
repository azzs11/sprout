"""The opt-in prepare-commit-msg hook: drafts only for a plain ``git commit``."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from sprout import services
from sprout.core.commit.writer import CommitWriter
from sprout.core.setup import git_hook
from sprout.hook import main
from sprout.hook_commit import has_message, prepare_commit_msg
from sprout.models import ConfigAction
from tests.fakes import FakeProvider
from tests.fixtures.builder import AUTHOR, RepoBuilder

MakeRepo = Callable[[str], RepoBuilder]
GIT_TEMPLATE = "\n# Please enter the commit message for your changes.\n#\n# On branch main\n"
REPLY = json.dumps(
    {
        "type": None,
        "scope": None,
        "description": "return 3 from main",
        "body": None,
        "question": "Why should main return 3?",
    }
)


@pytest.fixture
def staged(make_repo: MakeRepo, monkeypatch: pytest.MonkeyPatch) -> RepoBuilder:
    monkeypatch.setattr(services, "build_commit_writer", lambda _s: (None, None))
    repo = make_repo("linear")
    return repo.write("app.py", "def main():\n    return 3\n").stage("app.py")


def _message_file(tmp_path: Path, text: str = GIT_TEMPLATE) -> Path:
    path = tmp_path / "COMMIT_EDITMSG"
    path.write_text(text)
    return path


def test_plain_commit_gets_a_draft_above_gits_comments(staged: RepoBuilder, tmp_path: Path) -> None:
    path = _message_file(tmp_path)
    assert prepare_commit_msg(staged.root, [str(path)]) == 0
    text = path.read_text()
    assert text.startswith("fix: update app.py\n\n# Why is this change needed?")
    assert '\n# Answer on a line "Why: <reason>" here.\n' in text
    assert text.endswith(GIT_TEMPLATE)


@pytest.mark.parametrize("source", ["message", "template", "merge", "squash", "commit"])
def test_other_sources_are_left_alone(staged: RepoBuilder, tmp_path: Path, source: str) -> None:
    path = _message_file(tmp_path, "keep me\n")
    assert prepare_commit_msg(staged.root, [str(path), source]) == 0
    assert path.read_text() == "keep me\n"


def test_pre_commit_framework_source_from_environment(
    staged: RepoBuilder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRE_COMMIT_COMMIT_MSG_SOURCE", "message")
    path = _message_file(tmp_path)
    prepare_commit_msg(staged.root, [str(path)])
    assert path.read_text() == GIT_TEMPLATE


def test_existing_message_is_kept(staged: RepoBuilder, tmp_path: Path) -> None:
    path = _message_file(tmp_path, "my own words\n" + GIT_TEMPLATE)
    prepare_commit_msg(staged.root, [str(path)])
    assert path.read_text().startswith("my own words\n")
    assert has_message("# only\n\n", "#") is False


def test_nothing_staged_writes_nothing(make_repo: MakeRepo, tmp_path: Path) -> None:
    path = _message_file(tmp_path)
    prepare_commit_msg(make_repo("linear").root, [str(path)])
    assert path.read_text() == GIT_TEMPLATE


def test_auto_comment_char_adds_no_comments(staged: RepoBuilder, tmp_path: Path) -> None:
    staged.git("config", "core.commentChar", "auto")
    path = _message_file(tmp_path, "")
    prepare_commit_msg(staged.root, [str(path)])
    assert "#" not in path.read_text()
    assert path.read_text().startswith("fix: update app.py\n")


def test_slow_model_falls_back_to_the_skeleton(
    staged: RepoBuilder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Slow(FakeProvider):
        def complete(self, **_: object) -> str:  # type: ignore[override]
            time.sleep(3)
            return REPLY

    monkeypatch.setattr(services, "build_commit_writer", lambda _s: (CommitWriter(Slow()), None))
    monkeypatch.setenv("SPROUT_COMMIT_TIMEOUT", "1")
    path = _message_file(tmp_path)
    started = time.monotonic()
    prepare_commit_msg(staged.root, [str(path)])
    assert time.monotonic() - started < 2.5
    assert "# The model took longer than 1 s, so this is a skeleton." in path.read_text()


def test_model_draft_and_dispatch(
    staged: RepoBuilder, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        services, "build_commit_writer", lambda _s: (CommitWriter(FakeProvider(REPLY)), None)
    )
    monkeypatch.chdir(staged.root)
    path = _message_file(tmp_path)
    assert main(["prepare-commit-msg", str(path)]) == 0
    text = path.read_text()
    assert text.startswith("fix: return 3 from main\n\n# Why should main return 3?")
    assert "Drafted by Sprout (fake:model)" in text


def test_install_and_remove_beside_the_pre_commit_hook(staged: RepoBuilder) -> None:
    risk = git_hook.install(staged.root)
    drafts = git_hook.install(staged.root, hook=git_hook.PREPARE_COMMIT_MSG)
    assert Path(drafts.path).name == "prepare-commit-msg"
    assert 'sprout-hook prepare-commit-msg "$@"' in Path(drafts.path).read_text()
    remove = git_hook.remove(staged.root, hook=git_hook.PREPARE_COMMIT_MSG)
    assert remove.action is ConfigAction.DELETED_FILE
    assert Path(risk.path).exists()


def _git_env(**extra: str) -> dict[str, str]:
    return {
        **os.environ,
        "PATH": os.defpath,  # no sprout-hook on PATH: the fallback interpreter runs
        "GIT_AUTHOR_NAME": AUTHOR[0],
        "GIT_AUTHOR_EMAIL": AUTHOR[1],
        "GIT_COMMITTER_NAME": AUTHOR[0],
        "GIT_COMMITTER_EMAIL": AUTHOR[1],
        "GIT_EDITOR": "true",  # accept the message as drafted
        "SPROUT_LLM_PROVIDER": "none",
        **extra,
    }


def _commit(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), "commit", *args], capture_output=True, text=True,
        env=_git_env(), check=False,
    )  # fmt: skip


@pytest.mark.skipif(os.name == "nt", reason="git runs hooks through sh; covered on Unix")
def test_real_git_commit_all_uses_the_temporary_index(make_repo: MakeRepo) -> None:
    repo = make_repo("linear")
    git_hook.install(repo.root, python=sys.executable, hook=git_hook.PREPARE_COMMIT_MSG)
    (repo.root / "app.py").write_text("def main():\n    return 3\n")  # not staged: -a stages it
    done = _commit(repo.root, "-a")
    assert done.returncode == 0, done.stderr
    message = repo.git("log", "-1", "--format=%B")
    assert message == "fix: update app.py"  # comments stripped by git; no Why: line added
    (repo.root / "app.py").write_text("def main():\n    return 4\n")
    assert _commit(repo.root, "-a", "-m", "my words").returncode == 0
    assert repo.git("log", "-1", "--format=%B") == "my words"
