"""Tests for the reason gate: which quoted reasons may be shown."""

from __future__ import annotations

from sprout.core.answer.reasons import Reason, acceptable, has_body, vet_reason

BODY_REASON = (
    "Allow ArrayBuffer as data\n\nIn order to push binary data one needs not to stringify it."
)


def test_subject_line_is_not_a_reason() -> None:
    message = "fix(utils): replace getRandomValues with crypto module (#6788)"
    assert not acceptable("fix(utils): replace getRandomValues with crypto module (#6788)", message)
    assert not acceptable("replace getRandomValues with crypto module", message)


def test_subject_that_states_a_cause_is_a_reason() -> None:
    message = "Fixed `res.redirect()` on windows due to `join()` usage. Closes #808"
    assert acceptable("Fixed `res.redirect()` on windows due to `join()` usage", message)


def test_issue_references_and_foreign_text_are_not_reasons() -> None:
    message = "Request local objects now fail properly.\n\nThis fixes #105"
    assert not acceptable("This fixes #105", message)
    assert not acceptable("if length > cap(b) {", message)


def test_body_reason_replaces_a_bad_quote_or_a_wrong_none() -> None:
    expected = Reason("In order to push binary data one needs not to stringify it.")
    assert vet_reason(None, BODY_REASON) == expected
    assert vet_reason("Allow ArrayBuffer as data", BODY_REASON) == expected


def test_none_stated_only_without_a_body() -> None:
    assert vet_reason(None, "add json provider interface") == Reason(None, none_stated=True)
    assert vet_reason(None, "feat: x\n\n* fix tests\n* docs") == Reason(None, none_stated=False)
    assert not has_body("Add types (#7272)\n\nSigned-off-by: A <a@b.c>")


def test_weak_words_do_not_turn_a_subject_or_bullet_into_a_reason() -> None:
    message = "JSON improvements: throw if parsing failed (#3688)\n\n* fix: failing tests"
    assert not acceptable("JSON improvements: throw if parsing failed", message)
    assert not acceptable("* fix: failing tests", message)
    assert acceptable(
        "* use a stack buffer to avoid allocs", message + "\n* use a stack buffer to avoid allocs"
    )
