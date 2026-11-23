"""Tests for structured answers: schemas, reply parsing and sentence composing."""

from __future__ import annotations

import json

from sprout.core.answer.structured import (
    MAX_PICKS,
    Pick,
    compose,
    main_schema,
    parse_picks,
    pick_schema,
)


def _item(commit: str, quote: str | None = "because it was slow") -> dict[str, object]:
    return {"commit": commit, "what": "cache the result", "reason_quote": quote}


def test_pick_schema_limits_hashes_and_closes_objects() -> None:
    schema = pick_schema(["aaaaaaa", "bbbbbbb"])
    item = schema["properties"]["picks"]["items"]  # type: ignore[index]
    assert item["properties"]["commit"]["enum"] == ["aaaaaaa", "bbbbbbb"]
    assert item["additionalProperties"] is False
    assert schema["additionalProperties"] is False


def test_main_schema_fixes_the_main_commit() -> None:
    schema = main_schema("aaaaaaa", ["aaaaaaa", "bbbbbbb"])
    props = schema["properties"]
    assert props["main"]["properties"]["commit"]["enum"] == ["aaaaaaa"]  # type: ignore[index]
    also = props["also"]["anyOf"][0]  # type: ignore[index]
    assert also["properties"]["commit"]["enum"] == ["bbbbbbb"]


def test_parse_both_shapes_and_cap_picks() -> None:
    many = json.dumps({"picks": [_item(c * 7) for c in "abc"]})
    assert [p.commit for p in parse_picks(many) or []] == ["aaaaaaa", "bbbbbbb"][:MAX_PICKS]
    fixed = json.dumps({"main": _item("aaaaaaa", None), "also": None})
    assert parse_picks(fixed) == [Pick("aaaaaaa", "cache the result", None)]


def test_bad_replies_are_rejected() -> None:
    assert parse_picks("not json") is None
    assert parse_picks("[1, 2]") is None
    assert parse_picks(json.dumps({"picks": [{"commit": 1, "what": ""}]})) == []


def test_compose_quotes_the_reason_or_says_none_is_recorded() -> None:
    messages = {
        "aaaaaaa": "perf: cache the result\n\nWe cache it because it was slow.",
        "bbbbbbb": "chore: tidy up",
    }
    sentences = compose(
        [
            Pick("aaaaaaa", "cache the result.", '"because it was slow."'),
            Pick("bbbbbbb", "x", None),
        ],
        messages,
    )
    assert sentences == [
        "Cache the result [aaaaaaa].",
        'Its message gives the reason: "because it was slow" [aaaaaaa].',
        "X [bbbbbbb].",
        "No commit message states why [bbbbbbb].",
    ]


def test_compose_says_nothing_about_reasons_it_cannot_back() -> None:
    messages = {"aaaaaaa": "feat: add x\n\n* add tests\n* update docs"}
    sentences = compose([Pick("aaaaaaa", "add x", "feat: add x")], messages)
    assert sentences == ["Add x [aaaaaaa]."]
