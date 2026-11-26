"""Drafting commit messages: the model writes the what, the author gives the why."""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest

from sprout.core.commit.message import assemble, diff_text, draft_message, wrap
from sprout.core.commit.style import learn_style
from sprout.core.commit.subject import format_subject, guess_type
from sprout.core.commit.writer import CommitWriter, parse_written
from sprout.core.git import open_repo
from sprout.errors import ModelError, NothingStagedError
from sprout.models import ChangeKind, CommitStyle, DraftSource, FileDiff
from tests.fakes import FakeProvider
from tests.fixtures.builder import RepoBuilder

MakeRepo = Callable[[str], RepoBuilder]
SECRET = "ghp_" + "a" * 36


def _reply(**fields: object) -> str:
    base: dict[str, object] = {
        "type": "fix",
        "scope": "payments",
        "description": "Restore three charge retries.",
        "body": "Set RETRIES back to 3 in PaymentClient.",
        "question": "Why must charge() retry three times?",
    }
    return json.dumps(base | fields)


def _staged_payments(make_repo: MakeRepo) -> RepoBuilder:
    repo = make_repo("payments")
    text = (repo.root / "src/payments.py").read_text()
    repo.write("src/payments.py", text.replace("RETRIES = 3", "RETRIES = 5"))
    return repo.stage("src/payments.py")


def test_model_draft_follows_repo_style(make_repo: MakeRepo) -> None:
    repo = open_repo(_staged_payments(make_repo).root)
    provider = FakeProvider(reply=_reply())
    draft = draft_message(repo, repo.diff(staged=True), writer=CommitWriter(provider))
    # Lower-case after the prefix and no full stop, like every past commit in the fixture.
    assert draft.subject == "fix(payments): restore three charge retries"
    assert draft.source is DraftSource.MODEL
    assert draft.question == "Why must charge() retry three times?"
    assert draft.model == "fake:model|commit_message@1"
    prompt = provider.prompts[0]
    assert "feat(payments): retry failed charges three times" in prompt
    assert "RETRIES = 5" in prompt
    schema = provider.schemas[0]
    assert schema is not None
    assert "question" in json.dumps(schema)


def test_examples_skip_reverts_and_other_files(make_repo: MakeRepo) -> None:
    repo = open_repo(_staged_payments(make_repo).root)
    draft = draft_message(repo, repo.diff(staged=True))
    assert draft.examples == [
        "perf(payments): disable charge retries to cut latency",
        "feat(payments): retry failed charges three times",
    ]


def test_why_is_kept_word_for_word(make_repo: MakeRepo) -> None:
    repo = open_repo(_staged_payments(make_repo).root)
    why = "The  card network drops ~1% of requests;\nthree retries were not enough."
    draft = draft_message(
        repo, repo.diff(staged=True), writer=CommitWriter(FakeProvider(reply=_reply())), why=why
    )
    assert draft.why == "The card network drops ~1% of requests; three retries were not enough."
    assert draft.trailers[0].key == "Why"
    assert draft.message.endswith(
        "\n\nWhy: The card network drops ~1% of requests; three retries were not\n  enough.\n"
    )
    assert draft.message.startswith(draft.subject + "\n\nSet RETRIES back to 3")


def test_skeleton_without_model(make_repo: MakeRepo) -> None:
    repo = open_repo(_staged_payments(make_repo).root)
    draft = draft_message(repo, repo.diff(staged=True))
    assert draft.source is DraftSource.SKELETON
    # Type and scope from past commits to the same file; the newest is perf(payments).
    assert draft.subject == "perf(payments): update payments.py"
    assert draft.model is None
    assert draft.body is None
    assert draft.question.startswith("Why is this change needed?")
    assert any("without a model" in n for n in draft.notes)


@pytest.mark.parametrize("reply", ["not json", "[]", json.dumps({"description": "  "})])
def test_unusable_reply_falls_back(make_repo: MakeRepo, reply: str) -> None:
    repo = open_repo(_staged_payments(make_repo).root)
    draft = draft_message(repo, repo.diff(staged=True), writer=CommitWriter(FakeProvider(reply)))
    assert draft.source is DraftSource.SKELETON
    assert "The model's reply was not usable." in draft.notes


def test_model_error_falls_back(make_repo: MakeRepo) -> None:
    class Down(FakeProvider):
        def complete(self, **_: object) -> str:  # type: ignore[override]
            raise ModelError("Ollama is not running.")

    repo = open_repo(_staged_payments(make_repo).root)
    draft = draft_message(repo, repo.diff(staged=True), writer=CommitWriter(Down()))
    assert draft.source is DraftSource.SKELETON
    assert "Model unavailable: Ollama is not running." in draft.notes


def test_nothing_staged(make_repo: MakeRepo) -> None:
    repo = open_repo(make_repo("payments").root)
    with pytest.raises(NothingStagedError) as err:
        draft_message(repo, repo.diff(staged=True))
    assert err.value.hint
    assert "git add" in err.value.hint


def test_first_commit_uses_defaults(make_repo: MakeRepo) -> None:
    builder = make_repo("empty").write("app.py", "x = 1\n").stage("app.py")
    repo = open_repo(builder.root)
    draft = draft_message(repo, repo.diff(staged=True))
    assert draft.subject == "feat: add app.py"
    assert draft.examples == []


def test_secrets_are_redacted_before_the_model(make_repo: MakeRepo) -> None:
    builder = make_repo("payments").write("src/conf.py", f"TOKEN = '{SECRET}'\n")
    repo = open_repo(builder.stage("src/conf.py").root)
    provider = FakeProvider(reply=_reply())
    draft = draft_message(repo, repo.diff(staged=True), writer=CommitWriter(provider))
    assert SECRET not in provider.prompts[0]
    assert draft.redacted >= 1


def test_diff_text_is_capped() -> None:
    from sprout.models import Diff

    big = FileDiff(
        path="a.py", old_path=None, kind=ChangeKind.MODIFIED, additions=1, deletions=0,
        binary=False, patch="+" + "x" * 20_000,
    )  # fmt: skip
    text, _, truncated = diff_text(Diff(staged=True, files=[big]))
    assert truncated
    assert text.endswith("[diff truncated]\n")
    assert len(text) < 13_000


def test_parse_written_cleans_the_reply() -> None:
    reply = _reply(
        type="Nonsense",
        description="Restore retries\nsecond line",
        body="Set RETRIES to 3.\nSigned-off-by: Bot <b@c.d>\nFixes: #12",
        question="why",
    )
    written = parse_written(reply, ["fix", "feat"])
    assert written is not None
    assert written.type_ is None
    assert written.description == "Restore retries"
    assert written.body == "Set RETRIES to 3."
    assert written.question is None


def _style(**fields: object) -> CommitStyle:
    base: dict[str, object] = {
        "sample_size": 10, "conventional_share": 0.0, "types": [], "scopes": [],
        "subject_p50": 40, "subject_p90": 60, "capitalised_share": 1.0, "period_share": 1.0,
        "imperative_share": 1.0, "body_share": 0.0, "pr_suffix_share": 0.0, "trailers": [],
        "examples": [],
    }  # fmt: skip
    return CommitStyle.model_validate(base | fields)


def test_format_subject_plain_style() -> None:
    style = _style()
    assert format_subject(style, "fix: restore retries", type_="fix", scope="x") == (
        "Restore retries."
    )
    lower = _style(capitalised_share=0.0, period_share=0.0)
    assert format_subject(lower, "HTTP client timeout", type_=None, scope=None) == (
        "HTTP client timeout"
    )


def test_guess_type_from_paths() -> None:
    def changed(path: str) -> FileDiff:
        return FileDiff(
            path=path, old_path=None, kind=ChangeKind.MODIFIED, additions=1, deletions=1,
            binary=False, patch="",
        )  # fmt: skip

    style = _style()
    assert guess_type([changed("tests/unit/test_a.py")], [], style) == "test"
    assert guess_type([changed("docs/mcp.md"), changed("README.md")], [], style) == "docs"
    assert guess_type([changed(".github/workflows/ci.yml")], [], style) == "ci"
    assert guess_type([changed("uv.lock")], [], style) == "build"
    assert guess_type([changed("src/a.py")], ["fix(a): b"], style) == "fix"


def test_wrap_and_assemble() -> None:
    long = "word " * 30
    assert all(len(line) <= 72 for line in wrap(long).splitlines())
    bullets = wrap("- " + long + "\n- short")
    assert bullets.splitlines()[1].startswith("  ")
    assert bullets.endswith("- short")
    assert assemble("feat: x", None) == "feat: x\n"


def test_style_learned_once_is_reused(make_repo: MakeRepo) -> None:
    repo = open_repo(_staged_payments(make_repo).root)
    style = learn_style(repo)
    draft = draft_message(repo, repo.diff(staged=True), style=style)
    assert draft.files == ["src/payments.py"]
