"""Structured answers: the model picks commits and copies reasons; Sprout writes the sentences.

Small local models write unreliable free prose (missing citations, pasted evidence, invented
clauses). Asking them only to choose from a fixed list of hashes and to copy the reason word
for word, and composing the sentences here, keeps every claim checkable. Measured on the
WhyBench tune split (``bench answers``) against free prose before it became the default.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from sprout.core.answer.reasons import vet_reason
from sprout.llm.provider import JsonSchema

MAX_PICKS = 2  # array-length constraints are not portable across backends, so cap in code
MAX_WHAT_WORDS = 40


@dataclass(frozen=True)
class Pick:
    """One commit the model chose, what it changed, and the reason quoted from its message."""

    commit: str  # 7-character prefix from the allowed list
    what: str
    reason_quote: str | None


def _item(hashes: list[str]) -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "commit": {"type": "string", "enum": hashes},
            "what": {"type": "string"},
            "reason_quote": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
        "required": ["commit", "what", "reason_quote"],
        "additionalProperties": False,
    }


def pick_schema(hashes: list[str]) -> JsonSchema:
    """The model chooses up to ``MAX_PICKS`` commits from ``hashes`` (questions)."""
    return {
        "type": "object",
        "properties": {"picks": {"type": "array", "items": _item(hashes)}},
        "required": ["picks"],
        "additionalProperties": False,
    }


def main_schema(main: str, hashes: list[str]) -> JsonSchema:
    """The main commit is fixed; the model may add one other (lines)."""
    others = [h for h in hashes if h != main] or [main]
    return {
        "type": "object",
        "properties": {
            "main": _item([main]),
            "also": {"anyOf": [_item(others), {"type": "null"}]},
        },
        "required": ["main", "also"],
        "additionalProperties": False,
    }


def parse_picks(reply: str) -> list[Pick] | None:
    """Picks from either schema's JSON, or None when the reply is not usable JSON."""
    try:
        data = _as_dict(json.loads(reply))
    except json.JSONDecodeError:
        return None
    if data is None:
        return None
    listed = data.get("picks")
    raw: list[object] = (
        list(cast("list[object]", listed))
        if isinstance(listed, list)
        else [data.get("main"), data.get("also")]
    )
    picks = [p for p in (_pick(item) for item in raw) if p is not None]
    return picks[:MAX_PICKS]


def _as_dict(value: object) -> dict[str, object] | None:
    return cast("dict[str, object]", value) if isinstance(value, dict) else None


def _pick(item: object) -> Pick | None:
    fields = _as_dict(item)
    if fields is None:
        return None
    commit, what, quote = fields.get("commit"), fields.get("what"), fields.get("reason_quote")
    if not isinstance(commit, str) or not isinstance(what, str) or not what.strip():
        return None
    clean_quote = quote.strip().strip('"“”').strip() if isinstance(quote, str) else ""
    return Pick(commit, what, clean_quote or None)


def compose(picks: list[Pick], messages: Mapping[str, str]) -> list[str]:
    """One sentence per claim, each ending with its citation, ready for ``check_sentences``.

    ``messages`` maps each allowed 7-character hash to its commit message. A reason sentence
    appears only when ``vet_reason`` accepts it; otherwise it is left out.
    """
    out: list[str] = []
    for pick in picks:
        what = " ".join(pick.what.split()[:MAX_WHAT_WORDS]).rstrip(" .;:")
        out.append(f"{what[:1].upper()}{what[1:]} [{pick.commit}].")
        reason = vet_reason(pick.reason_quote, messages.get(pick.commit, ""))
        if reason.quote:
            quote = " ".join(reason.quote.split()).strip('"“” ').rstrip(".").strip('"“” ')
            out.append(f'Its message gives the reason: "{quote}" [{pick.commit}].')
        elif reason.none_stated:
            out.append(f"No commit message states why [{pick.commit}].")
    return out
