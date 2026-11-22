"""Cross-encoder reranking of search candidates. The default runs locally with fastembed."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from sprout.core.index.embedder import quiet_model_downloads
from sprout.errors import ModelError

if TYPE_CHECKING:
    from fastembed.rerank.cross_encoder import (  # pyright: ignore[reportMissingTypeStubs]
        TextCrossEncoder,
    )

DEFAULT_RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"


class Reranker(Protocol):
    """Scores how well each document answers a query (higher is better)."""

    @property
    def name(self) -> str:
        """Model identifier."""
        ...

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        """One relevance score per document, in input order."""
        ...


class FastReranker:
    """Local ONNX cross-encoder, downloaded once into ``cache_dir``."""

    def __init__(self, model: str, cache_dir: Path) -> None:
        self._model_name = model
        self._cache_dir = cache_dir
        self._model: TextCrossEncoder | None = None

    @property
    def name(self) -> str:
        """Model identifier."""
        return self._model_name

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        """One relevance score per document, in input order."""
        if not documents:
            return []
        return [float(s) for s in self._load().rerank(query, list(documents), batch_size=32)]

    def _load(self) -> TextCrossEncoder:
        if self._model is None:
            quiet_model_downloads()
            from fastembed.rerank.cross_encoder import (  # pyright: ignore[reportMissingTypeStubs]
                TextCrossEncoder,
            )

            try:
                self._model = TextCrossEncoder(self._model_name, cache_dir=str(self._cache_dir))
            except Exception as exc:
                raise ModelError(
                    f"Could not load the reranker {self._model_name}: {exc}",
                    hint="Connect to the internet once to download it, or search with --no-rerank.",
                ) from exc
        return self._model
