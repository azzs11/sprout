"""Deterministic stand-ins for models, so tests run offline and fast."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

_WORD = re.compile(r"[a-z0-9]+")


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


class FakeEmbedder:
    """Bag-of-words feature hashing: texts sharing words get similar vectors."""

    def __init__(self, name: str = "fake-embedder", dim: int = 64) -> None:
        self._name = name
        self._dim = dim
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def dim(self) -> int:
        return self._dim

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += 1
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        for word in _words(text):
            digest = hashlib.blake2b(word.encode(), digest_size=4).digest()
            vec[int.from_bytes(digest, "big") % self._dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class FakeReranker:
    """Scores by how many query words a document contains."""

    name = "fake-reranker"

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        wanted = set(_words(query))
        return [float(len(wanted & set(_words(doc)))) for doc in documents]


@dataclass
class FakeProvider:
    """Records every prompt and returns a canned summary."""

    reply: str = "Changes behaviour of the code."
    remote: bool = False
    prompts: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return "fake:model"

    def complete(self, *, system: str, prompt: str, max_tokens: int) -> str:
        self.prompts.append(prompt)
        return f"  {self.reply}\n\n"
