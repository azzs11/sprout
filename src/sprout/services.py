"""Build models and providers from settings. Tests replace these factories with fakes."""

from __future__ import annotations

from sprout.config import Settings
from sprout.core.answer.compose import Answerer
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


def build_answerer(settings: Settings) -> tuple[Answerer | None, str | None]:
    """A ``why`` answerer, or None with a short note when no model is usable right now."""
    if settings.llm_provider == "none":
        return None, None
    try:
        provider = build_provider(settings)
    except ModelError as exc:
        return None, f"Facts only: {exc.message}"
    from sprout.llm.ollama import OllamaProvider

    if isinstance(provider, OllamaProvider) and not provider.available():
        return None, "Facts only. For written answers start Ollama, or set SPROUT_LLM_PROVIDER."
    return Answerer(provider), None


def build_summariser(settings: Settings) -> Summariser:
    """A summariser over the configured provider."""
    return Summariser(build_provider(settings))


def describe_answers(settings: Settings) -> str:
    """One line on where written ``why`` answers will come from, or what to do to get them."""
    model = settings.resolved_llm_model
    if settings.llm_provider == "none":
        return "Facts only, because SPROUT_LLM_PROVIDER is none."
    if settings.llm_provider == "anthropic":
        if settings.anthropic_api_key is None:
            return "Facts only: SPROUT_LLM_PROVIDER is anthropic but ANTHROPIC_API_KEY is not set."
        return f"Written by {model} with your Anthropic key. Redacted code leaves this machine."
    from sprout.llm.ollama import OllamaProvider

    ollama = OllamaProvider(model, base_url=settings.ollama_url)
    if not ollama.available():
        return "Facts only: Ollama is not running. Start it for written answers (they stay local)."
    if not ollama.has_model():
        return f"Facts only: Ollama is running but {model} is not pulled. Run: ollama pull {model}"
    return f"Written by {model} through Ollama, on this machine."
