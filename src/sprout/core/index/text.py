"""Text preparation shared by keyword indexing and querying."""

from __future__ import annotations

import re

_WORD = re.compile(r"[A-Za-z0-9]+")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")


def split_identifier(name: str) -> list[str]:
    """``retryPayment_v2`` -> ``["retry", "payment", "v", "2"]`` (lower-cased)."""
    return [part.lower() for chunk in name.split("_") for part in _CAMEL.findall(chunk)]


def expand_identifiers(text: str) -> str:
    """Append the word parts of camelCase / snake_case identifiers so FTS can match them."""
    extra: dict[str, None] = {}
    for ident in _IDENT.findall(text):
        parts = split_identifier(ident)
        if len(parts) > 1:
            extra.update(dict.fromkeys(parts))
    return f"{text} {' '.join(extra)}" if extra else text


def fts_query(query: str) -> str | None:
    """Turn free text into a safe FTS5 query: every word quoted, joined with OR."""
    words = dict.fromkeys(w.lower() for w in _WORD.findall(expand_identifiers(query)))
    return " OR ".join(f'"{w}"' for w in words) or None
