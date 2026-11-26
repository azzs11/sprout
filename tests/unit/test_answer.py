"""Tests for blame, line history, rationale scoring, citation checks and ``why``."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping

import pytest

from sprout.core.answer import blame as blame_module
from sprout.core.answer import lineage as lineage_module
from sprout.core.answer.blame import LineNotFoundError, blame_line, parse_porcelain
from sprout.core.answer.citations import check, check_sentences, split_sentences
from sprout.core.answer.compose import Answerer
from sprout.core.answer.evidence import EvidenceSet
from sprout.core.answer.lineage import line_history, line_log
from sprout.core.answer.rationale import score_message
from sprout.core.answer.why import Models, why_line, why_question
from sprout.core.git import open_repo
from sprout.core.index.indexer import build_index
from sprout.core.index.store import Store
from sprout.errors import ModelError
from sprout.models import AnswerMode, EvidenceRole, Label
from tests.fakes import FakeProvider
from tests.fixtures.builder import RepoBuilder

MakeRepo = Callable[[str], RepoBuilder]
RETRIES_LINE = 2  # "    retries = 5" in src/payments/core.py


@pytest.fixture
def lineage(make_repo: MakeRepo) -> RepoBuilder:
    return make_repo("lineage")


@pytest.fixture
def indexed(lineage: RepoBuilder) -> Iterator[Store]:
    with Store.open(lineage.root, create=True) as store:
        build_index(open_repo(lineage.root), store)
        yield store


def _hash_of(built: RepoBuilder, summary_start: str) -> str:
    return built.git("log", "--format=%H", f"--grep=^{summary_start}")


# ----- blame -------------------------------------------------------------------------


def test_parse_porcelain() -> None:
    raw = (
        b"abc123 7 9 1\nauthor A\nsummary s\nprevious def456 old/name.py\n"
        b"filename new/name.py\n\t    retries = 5\n"
    )
    line = parse_porcelain(raw, fallback_path="x")
    assert (line.commit, line.line, line.path, line.text) == (
        "abc123",
        7,
        "new/name.py",
        "    retries = 5",
    )
    assert line.previous == ("def456", "old/name.py")


@pytest.mark.parametrize("use_cli", [True, False])
def test_blame_cli_and_libgit2_agree(
    lineage: RepoBuilder, monkeypatch: pytest.MonkeyPatch, use_cli: bool
) -> None:
    if not use_cli:
        monkeypatch.setattr(blame_module.shutil, "which", lambda _name: None)
    result = blame_line(lineage.root, lineage.head(), "src/payments/core.py", RETRIES_LINE)
    assert result.commit == _hash_of(lineage, "fix(payments)")
    assert result.text.strip() == "retries = 5"
    assert result.previous is not None


def test_blame_missing_line(lineage: RepoBuilder) -> None:
    with pytest.raises(LineNotFoundError):
        blame_line(lineage.root, lineage.head(), "src/payments/core.py", 999)


# ----- line history ------------------------------------------------------------------


def test_line_history_follows_rename_to_origin(lineage: RepoBuilder) -> None:
    repo = open_repo(lineage.root)
    hops = line_history(repo, "src/payments/core.py", RETRIES_LINE, rev=repo.resolve())
    assert [h.commit.summary for h in hops] == [
        "fix(payments): raise retries to 5",
        "feat: add charge with retries",
    ]
    assert [h.path for h in hops] == ["src/payments/core.py", "src/pay.py"]
    assert [h.introduced for h in hops] == [False, True]
    assert hops[1].text.strip() == "retries = 3"


def test_line_log_lists_every_commit_to_the_line(lineage: RepoBuilder) -> None:
    repo = open_repo(lineage.root)
    found = line_log(repo, "src/payments/core.py", RETRIES_LINE, rev=repo.resolve())
    assert found[0] == _hash_of(lineage, "fix(payments)")
    assert line_log(repo, "src/payments/core.py", RETRIES_LINE, rev=repo.resolve(), limit=0) == []
    assert line_log(repo, "missing.py", 1, rev=repo.resolve()) == []


def test_line_log_without_git_cli(lineage: RepoBuilder, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lineage_module.shutil, "which", lambda _name: None)
    repo = open_repo(lineage.root)
    assert line_log(repo, "src/payments/core.py", RETRIES_LINE, rev=repo.resolve()) == []


# ----- ranking -----------------------------------------------------------------------


def test_relevance_leads_and_rationale_breaks_ties(lineage: RepoBuilder) -> None:
    repo = open_repo(lineage.root)
    fix = repo.commit(_hash_of(lineage, "fix(payments)"))
    feat = repo.commit(_hash_of(lineage, "feat: add charge"))
    found = EvidenceSet(repo, None, repo.resolve())
    found.add(fix, EvidenceRole.RELATED, rank=2)
    found.add(feat, EvidenceRole.RELATED, rank=1)
    assert [e.commit.hash for e in found.ranked(5)] == [fix.hash, feat.hash]
    assert [e.commit.hash for e in found.ranked(5, by_relevance=True)] == [feat.hash, fix.hash]
    tied = EvidenceSet(repo, None, repo.resolve())
    tied.add(feat, EvidenceRole.RELATED, rank=1)
    tied.add(fix, EvidenceRole.RELATED, rank=1)
    assert tied.ranked(5, by_relevance=True)[0].commit.hash == fix.hash


# ----- rationale ---------------------------------------------------------------------


def test_strong_reasons_outrank_event_words() -> None:
    why = score_message("disable rewriting because of bugs (fixes #280)", labels=[], refs=1)
    what = score_message("fix crash on assert failure", labels=[Label.FIX], refs=0)
    assert why.score > what.score


def test_mechanical_commits_score_low() -> None:
    assert score_message("style: run black", labels=[], refs=0).score < 0
    assert score_message("fix some pep8 issues", labels=[], refs=0).score < 1


def test_excerpt_rejoins_wrapped_lines_and_skips_boilerplate() -> None:
    message = (
        'Revert "x"\n\nThis reverts commit 0123456.\n\nWe keep the timestamp path because\n'
        "hashing was assumed to be slow.\n"
    )
    result = score_message(message, labels=[], refs=0)
    assert result.excerpt == "We keep the timestamp path because hashing was assumed to be slow."
    assert not result.clipped


def test_long_excerpt_is_clipped_at_a_word() -> None:
    result = score_message(
        "feat: x\n\nWe do this because " + "very " * 80 + "long.", labels=[], refs=0
    )
    assert result.clipped
    assert result.excerpt is not None
    assert not result.excerpt.endswith("ver")


# ----- citation checker --------------------------------------------------------------

EVIDENCE = {
    "a"
    * 40: "fix(payments): raise retries to 5. We raised the limit because the card network times out under load.",
    "b" * 40: "feat: add charge with retries",
}


def _check(text: str):
    return check(text, EVIDENCE, exists=lambda h: h in EVIDENCE)


def test_supported_sentence_is_kept() -> None:
    result = _check(
        'Retries were raised to 5 "because the card network times out under load" [aaaaaaa].'
    )
    assert result.dropped == 0
    assert result.kept[0].citations == ["a" * 40]
    assert "[" not in result.kept[0].text


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("Retries exist to keep customers happy.", "no citation"),
        ("Retries were raised [ccccccc].", "not in the evidence"),
        ('It was done "to save money" [aaaaaaa].', "quote not found"),
        (
            "Engineers preferred quantum blockchain scheduling heuristics [bbbbbbb].",
            "not supported",
        ),
        ("related, 2024-01-02, Ann\nmessage:\nfeat: add charge with retries [bbbbbbb].", "copied"),
        ("The line at this commit: feat: add charge with retries [bbbbbbb].", "copied"),
        (
            "Retries [aaaaaaa] [bbbbbbb] [aaaaaab] [aaaaaac] changed.",
            "not in the evidence",
        ),
    ],
)
def test_bad_sentences_are_dropped(text: str, reason: str) -> None:
    result = _check(text)
    assert result.kept == []
    assert reason in result.reasons[0]


def test_mid_sentence_citation_stays_readable() -> None:
    result = _check("The limit was raised in [aaaaaaa] because the card network times out.")
    assert result.kept[0].text == (
        "The limit was raised in aaaaaaa because the card network times out."
    )
    assert result.kept[0].citations == ["a" * 40]


def test_leading_citation_is_removed_from_the_text() -> None:
    result = _check("[aaaaaaa] Retries were raised because the card network times out.")
    assert result.kept[0].text == "Retries were raised because the card network times out."
    assert result.kept[0].citations == ["a" * 40]


def test_too_many_citations_is_dropped() -> None:
    many = {c * 40: "feat: add charge with retries" for c in "abcd"}
    result = check(
        "Retries were added for charges [aaaaaaa, bbbbbbb, ccccccc, ddddddd].",
        many,
        exists=lambda h: h in many,
    )
    assert result.reasons == ["cites too many commits: Retries were added for charges."]


def test_composed_sentence_with_inner_full_stop_is_checked_whole() -> None:
    sentence = (
        'Its message says: "fix(payments): raise retries to 5. We raised the limit" [aaaaaaa].'
    )
    result = check_sentences([sentence], EVIDENCE, exists=lambda h: h in EVIDENCE)
    assert result.dropped == 0
    assert len(result.kept) == 1
    assert check(sentence, EVIDENCE, exists=lambda h: h in EVIDENCE).dropped == 1


def test_forged_hash_is_counted() -> None:
    assert _check("Raised retries [deadbee].").forged == 1


def test_citation_after_full_stop_is_attached() -> None:
    assert split_sentences("Retries were raised to five. [aaaaaaa] Next one.") == [
        "Retries were raised to five [aaaaaaa].",
        "Next one.",
    ]


# ----- why ---------------------------------------------------------------------------


def test_why_line_retrieval_mode(lineage: RepoBuilder, indexed: Store) -> None:
    repo = open_repo(lineage.root)
    answer = why_line(repo, indexed, "src/payments/core.py", RETRIES_LINE)
    assert answer.mode is AnswerMode.RETRIEVAL
    assert answer.symbol == "charge"
    fix = _hash_of(lineage, "fix(payments)")
    assert answer.sentences[0].citations == [fix]
    assert any("because the card network times out under load" in s.text for s in answer.sentences)
    assert any("#7" in s.text for s in answer.sentences)
    roles = {e.commit.hash: e.role for e in answer.evidence}
    assert roles[fix] is EvidenceRole.LINE_ORIGIN
    cited = {h for s in answer.sentences for h in s.citations}
    assert cited <= {e.commit.hash for e in answer.evidence}


def test_why_line_keeps_every_line_log_commit(lineage: RepoBuilder, indexed: Store) -> None:
    repo = open_repo(lineage.root)
    answer = why_line(repo, indexed, "src/payments/core.py", RETRIES_LINE)
    logged = line_log(repo, "src/payments/core.py", RETRIES_LINE, rev=repo.resolve())
    assert set(logged) <= {e.commit.hash for e in answer.evidence}


def test_why_line_without_index_notes_it(lineage: RepoBuilder) -> None:
    answer = why_line(open_repo(lineage.root), None, "src/payments/core.py", RETRIES_LINE)
    assert answer.history
    assert "sprout index" in answer.notes[0]


def test_why_at_old_revision_never_cites_the_future(lineage: RepoBuilder, indexed: Store) -> None:
    repo = open_repo(lineage.root)
    old = _hash_of(lineage, "feat: add charge")
    answer = why_line(repo, indexed, "src/pay.py", RETRIES_LINE, rev=old)
    cited = {h for s in answer.sentences for h in s.citations}
    assert cited == {old}
    assert all(repo.is_ancestor(e.commit.hash, old) for e in answer.evidence)


def test_why_with_model_keeps_checked_sentences(lineage: RepoBuilder, indexed: Store) -> None:
    fix = _hash_of(lineage, "fix(payments)")
    reply = {
        "main": {
            "commit": fix[:7],
            "what": "raised retries to 5",
            "reason_quote": "because the card network times out under load",
        },
        "also": {"commit": "deadbee", "what": "improves the interface", "reason_quote": None},
    }
    provider = FakeProvider(reply=json.dumps(reply))
    answer = why_line(
        open_repo(lineage.root),
        indexed,
        "src/payments/core.py",
        RETRIES_LINE,
        models=Models(answerer=Answerer(provider)),
    )
    assert answer.mode is AnswerMode.LLM
    assert answer.model == "fake:model|why_answer@3+why_line_answer@1+reasons@1.1"
    assert [s.text for s in answer.sentences] == [
        "Raised retries to 5.",
        'Its message gives the reason: "because the card network times out under load".',
    ]
    assert [s.citations for s in answer.sentences] == [[fix], [fix]]
    assert answer.dropped == 2
    assert any("outside the evidence" in n for n in answer.notes)
    assert "retries = 5" in provider.prompts[0]
    schema = provider.schemas[0]
    assert schema is not None
    assert schema["properties"]["main"]["properties"]["commit"]["enum"] == [fix[:7]]  # type: ignore[index]


def test_why_falls_back_when_the_reply_is_not_json(lineage: RepoBuilder, indexed: Store) -> None:
    provider = FakeProvider(reply="Because reasons.")
    answer = why_line(
        open_repo(lineage.root),
        indexed,
        "src/payments/core.py",
        RETRIES_LINE,
        models=Models(answerer=Answerer(provider)),
    )
    assert answer.mode is AnswerMode.RETRIEVAL
    assert answer.dropped == 1
    assert answer.drop_reasons == ["unreadable reply: not the requested JSON"]
    assert answer.sentences


def test_why_question_lets_the_model_pick(make_repo: MakeRepo) -> None:
    built = make_repo("payments")
    provider = FakeProvider(reply='{"picks": []}')
    with Store.open(built.root, create=True) as store:
        build_index(open_repo(built.root), store)
        why_question(
            open_repo(built.root),
            store,
            "why did we disable charge retries",
            models=Models(answerer=Answerer(provider)),
        )
    schema = provider.schemas[0]
    assert schema is not None
    assert "picks" in schema["properties"]  # type: ignore[operator]


def test_why_survives_model_errors(lineage: RepoBuilder, indexed: Store) -> None:
    class Broken(FakeProvider):
        def complete(
            self,
            *,
            system: str,
            prompt: str,
            max_tokens: int,
            schema: Mapping[str, object] | None = None,
        ) -> str:
            raise ModelError("model is down")

    answer = why_line(
        open_repo(lineage.root),
        indexed,
        "src/payments/core.py",
        RETRIES_LINE,
        models=Models(answerer=Answerer(Broken())),
    )
    assert answer.mode is AnswerMode.RETRIEVAL
    assert any("model is down" in n for n in answer.notes)


def test_why_question(make_repo: MakeRepo) -> None:
    built = make_repo("payments")
    with Store.open(built.root, create=True) as store:
        build_index(open_repo(built.root), store)
        answer = why_question(open_repo(built.root), store, "why did we disable charge retries")
    assert answer.evidence
    text = " ".join(s.text for s in answer.sentences)
    assert "reverted" in text


def test_facts_never_call_a_subject_line_the_reason(
    make_repo: Callable[[str], RepoBuilder],
) -> None:
    # Body "The card network drops ~1% of requests." states no cause reasons@1 accepts, so
    # quoting the subject as "the clearest stated reason" would contradict the reason gate.
    repo = make_repo("payments")
    git = open_repo(repo.root)
    answer = why_line(git, None, "src/payments.py", 5)
    texts = [s.text for s in answer.sentences]
    assert not any("clearest stated reason" in t for t in texts), texts
    lineage = make_repo("lineage")
    kept = why_line(open_repo(lineage.root), None, "src/payments/core.py", 2)
    assert any(
        t.text.startswith("The clearest stated reason is in")
        and "because the card network" in t.text
        for t in kept.sentences
    )
