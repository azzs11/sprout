"""The model's part of a commit draft: subject parts, a short body and one why-question.

The reply is JSON constrained by a schema; Sprout validates it and applies the repository's
style itself, so a small local model only has to describe the diff.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from sprout.core.commit.subject import allowed_types, subject_limit, uses_conventional, uses_scopes
from sprout.llm.prompts import load_prompt
from sprout.llm.provider import JsonSchema, Provider
from sprout.models import CommitStyle

_TRAILER_KEYS = frozenset({"why", "fixes", "closes", "refs", "reverts", "resolves"})


@dataclass(frozen=True)
class Written:
    """The model's parts of a message, before Sprout applies the repository's style."""

    type_: str | None
    scope: str | None
    description: str
    body: str | None
    question: str | None


class CommitWriter:
    """Asks a model for the subject, body and why-question. Replaceable by a fake in tests."""

    def __init__(self, provider: Provider, *, max_tokens: int = 400) -> None:
        self.provider = provider
        self.prompt = load_prompt("commit_message")
        self.max_tokens = max_tokens

    @property
    def model_id(self) -> str:
        """``<provider>|<prompt id>``, recorded on every draft the model writes."""
        return f"{self.provider.name}|{self.prompt.id}"

    def write(self, style: CommitStyle, examples: str, diff: str) -> Written | None:
        """The model's parts, or None when its reply is not usable JSON.

        Raises:
            ModelError: If the model cannot be reached.
        """
        types = allowed_types(style)
        system = self.prompt.system.replace("$limit", str(subject_limit(style)))
        prompt = self.prompt.render(style=describe_style(style), examples=examples, diff=diff)
        reply = self.provider.complete(
            system=system, prompt=prompt, max_tokens=self.max_tokens, schema=_schema(types)
        )
        return parse_written(reply, types)


def describe_style(style: CommitStyle) -> str:
    """One line the model can follow, e.g. 'Conventional Commits; types: feat, fix; ...'."""
    if style.sample_size == 0:
        return "no history yet; use Conventional Commits."
    bits: list[str] = []
    if uses_conventional(style):
        bits.append("Conventional Commits, types: " + ", ".join(c.value for c in style.types[:6]))
        if uses_scopes(style):
            bits.append("scopes: " + ", ".join(c.value for c in style.scopes[:6]))
    else:
        bits.append("no type prefix")
    case = "capitalised" if style.capitalised_share >= 0.5 else "lower-case"
    bits.append(f"{case} subjects of about {style.subject_p50} characters")
    bits.append("ending with a full stop" if style.period_share >= 0.5 else "no full stop")
    bits.append(f"a body in {round(style.body_share * 100)}% of commits")
    return "; ".join(bits) + "."


def _schema(types: list[str]) -> JsonSchema:
    nullable: dict[str, object] = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    return {
        "type": "object",
        "properties": {
            "type": {"anyOf": [{"type": "string", "enum": types}, {"type": "null"}]},
            "scope": nullable,
            "description": {"type": "string"},
            "body": nullable,
            "question": {"type": "string"},
        },
        "required": ["type", "scope", "description", "body", "question"],
        "additionalProperties": False,
    }


def parse_written(reply: str, types: Sequence[str]) -> Written | None:
    """The model's parts from its JSON reply, or None when it is unusable."""
    try:
        raw: object = json.loads(reply)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    data = cast("dict[str, object]", raw)
    description = _text(data.get("description"))
    if not description:
        return None
    type_ = _text(data.get("type"))
    return Written(
        type_=type_.lower() if type_ and type_.lower() in types else None,
        scope=_text(data.get("scope")),
        description=description.splitlines()[0],
        body=_clean_body(_text(data.get("body"))),
        question=_clean_question(_text(data.get("question"))),
    )


def _text(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _clean_body(body: str | None) -> str | None:
    """Drop trailer-like lines (``Signed-off-by:``, ``Fixes:``): trailers are Sprout's job."""
    if body is None:
        return None
    kept = [line for line in body.splitlines() if not _is_trailer(line)]
    return "\n".join(kept).strip() or None


def _is_trailer(line: str) -> bool:
    key, sep, value = line.strip().partition(": ")
    if not sep or not value or " " in key or not key.replace("-", "").isalpha():
        return False
    return "-" in key or key.lower() in _TRAILER_KEYS


def _clean_question(question: str | None) -> str | None:
    """One line ending in '?', or None (the default question is used)."""
    if question is None:
        return None
    line = " ".join(question.split())
    return line if line.endswith("?") and 8 <= len(line) <= 240 else None
