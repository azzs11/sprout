"""The ``Provider`` interface every language-model backend implements."""

from __future__ import annotations

from typing import Protocol


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

    def complete(self, *, system: str, prompt: str, max_tokens: int) -> str:
        """Return the model's text reply.

        Raises:
            ModelError: If the model cannot be reached or declines to answer.
        """
        ...
