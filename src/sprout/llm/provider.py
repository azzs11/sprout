"""The ``Provider`` interface every language-model backend implements."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

JsonSchema = Mapping[str, object]


class Provider(Protocol):
    """A text-completion backend. Tests use a fake; nothing else calls a model directly."""

    @property
    def name(self) -> str:
        """``<backend>:<model>``, stored next to every generated summary."""
        ...

    @property
    def remote(self) -> bool:
        """True when calls leave this machine."""
        ...

    def complete(
        self, *, system: str, prompt: str, max_tokens: int, schema: JsonSchema | None = None
    ) -> str:
        """Return the model's text reply.

        With ``schema``, the reply is JSON constrained to that schema. Use only what both
        backends support: objects with ``additionalProperties: false``, ``enum``, ``anyOf``
        and ``null``; no numeric, string-length or array-length constraints.

        Raises:
            ModelError: If the model cannot be reached or declines to answer.
        """
        ...
