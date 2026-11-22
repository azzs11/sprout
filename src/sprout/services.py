"""Build models and providers from settings. Tests replace these factories with fakes."""

from __future__ import annotations

from sprout.config import Settings
from sprout.core.index.embedder import Embedder, FastEmbedder
from sprout.core.index.summarise import Summariser
from sprout.core.retrieve.rerank import FastReranker, Reranker
from sprout.errors import ModelError
from sprout.llm.provider import Provider


def build_embedder(settings: Settings) -> Embedder | None:
    """The configured embedding model, or None when set to 'none'."""
    if settings.embed_model.lower() == "none":
        return None
    return FastEmbedder(settings.embed_model, settings.model_cache)


def build_reranker(settings: Settings) -> Reranker | None:
    """The configured reranker, or None when set to 'none'."""
    if settings.rerank_model.lower() == "none":
        return None
    return FastReranker(settings.rerank_model, settings.model_cache)


def build_provider(settings: Settings) -> Provider:
    """The configured language model."""
    model = settings.resolved_llm_model
    if settings.llm_provider == "anthropic":
        from sprout.llm.anthropic import AnthropicProvider

        key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
        return AnthropicProvider(model, api_key=key)
    if settings.llm_provider == "ollama":
        from sprout.llm.ollama import OllamaProvider

        return OllamaProvider(model, base_url=settings.ollama_url)
    raise ModelError(
        "Summaries need a language model, but SPROUT_LLM_PROVIDER is 'none'.",
        hint="Set SPROUT_LLM_PROVIDER=ollama (local) or anthropic, or index without --summarise.",
    )


def build_summariser(settings: Settings) -> Summariser:
    """A summariser over the configured provider."""
    return Summariser(build_provider(settings))
