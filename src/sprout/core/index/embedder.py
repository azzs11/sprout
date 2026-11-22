"""Text embedding behind a small protocol. The default runs locally with fastembed (ONNX)."""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from sprout.errors import ModelError

if TYPE_CHECKING:
    from fastembed import TextEmbedding

DEFAULT_EMBED_MODEL = "BAAI/bge-small-en-v1.5"


class Embedder(Protocol):
    """Turns commit documents and search queries into vectors."""

    @property
    def name(self) -> str:
        """Model identifier, stored in the index so a model change triggers re-embedding."""
        ...

    @property
    def dim(self) -> int:
        """Vector length."""
        ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed commit documents."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Embed a search query (some models use a different prefix for queries)."""
        ...


class FastEmbedder:
    """Local ONNX embedding model, downloaded once into ``cache_dir`` and then used offline."""

    def __init__(self, model: str, cache_dir: Path) -> None:
        self._model_name = model
        self._cache_dir = cache_dir
        self._model: TextEmbedding | None = None
        self._dim = _supported_dim(model)

    @property
    def name(self) -> str:
        """Model identifier."""
        return self._model_name

    @property
    def dim(self) -> int:
        """Vector length."""
        return self._dim

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed commit documents."""
        return [v.tolist() for v in self._load().passage_embed(list(texts), batch_size=64)]

    def embed_query(self, text: str) -> list[float]:
        """Embed a search query."""
        return next(iter(self._load().query_embed(text))).tolist()

    def _load(self) -> TextEmbedding:
        if self._model is None:
            quiet_model_downloads()
            from fastembed import TextEmbedding

            try:
                self._model = TextEmbedding(self._model_name, cache_dir=str(self._cache_dir))
            except Exception as exc:  # network, disk or ONNX errors all look alike to users
                raise ModelError(
                    f"Could not load the embedding model {self._model_name}: {exc}",
                    hint="Connect to the internet once to download it, or index with --no-embed.",
                ) from exc
        return self._model


def quiet_model_downloads() -> None:
    """Silence Hugging Face progress bars and token warnings during one-time downloads."""
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("HF_HUB_VERBOSITY", "error")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    logging.getLogger("huggingface_hub").setLevel(logging.ERROR)


def _supported_dim(model: str) -> int:
    from fastembed import TextEmbedding

    for info in TextEmbedding.list_supported_models():
        if str(info["model"]).lower() == model.lower():
            return int(info["dim"])
    raise ModelError(
        f"Unknown embedding model {model!r}.",
        hint="Set SPROUT_EMBED_MODEL to a fastembed model (e.g. BAAI/bge-small-en-v1.5) or 'none'.",
    )
