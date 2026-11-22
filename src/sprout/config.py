"""Settings from (highest priority first) arguments, ``SPROUT_*`` env vars and ``.sprout.toml``."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from platformdirs import user_cache_dir
from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from sprout.core.index.embedder import DEFAULT_EMBED_MODEL
from sprout.core.retrieve.rerank import DEFAULT_RERANK_MODEL
from sprout.llm.anthropic import DEFAULT_ANTHROPIC_MODEL
from sprout.llm.ollama import DEFAULT_OLLAMA_MODEL, DEFAULT_OLLAMA_URL

CONFIG_FILE = ".sprout.toml"
LLMProvider = Literal["ollama", "anthropic", "none"]


class Settings(BaseSettings):
    """Every user-tunable option. Remote models are never chosen implicitly."""

    model_config = SettingsConfigDict(env_prefix="SPROUT_", extra="ignore")

    embed_model: str = Field(
        default=DEFAULT_EMBED_MODEL, description="fastembed model for vectors, or 'none'."
    )
    rerank_model: str = Field(
        default=DEFAULT_RERANK_MODEL, description="fastembed cross-encoder, or 'none'."
    )
    llm_provider: LLMProvider = Field(
        default="ollama",
        description="Where summaries come from. 'anthropic' sends diffs off-machine.",
    )
    llm_model: str | None = Field(default=None, description="Model name for the chosen provider.")
    ollama_url: str = DEFAULT_OLLAMA_URL
    anthropic_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("SPROUT_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
    )
    model_cache: Path = Field(default_factory=lambda: Path(user_cache_dir("sprout")) / "models")

    @property
    def resolved_llm_model(self) -> str:
        """The model for ``llm_provider``, with a sensible default per provider."""
        if self.llm_model:
            return self.llm_model
        return DEFAULT_ANTHROPIC_MODEL if self.llm_provider == "anthropic" else DEFAULT_OLLAMA_MODEL


def load_settings(root: Path | None = None) -> Settings:
    """Load settings, reading ``<root>/.sprout.toml`` when it exists."""
    toml_file = root / CONFIG_FILE if root is not None else None

    class _Settings(Settings):
        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,  # noqa: ARG003
            file_secret_settings: PydanticBaseSettingsSource,  # noqa: ARG003
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            sources: list[PydanticBaseSettingsSource] = [init_settings, env_settings]
            if toml_file is not None and toml_file.is_file():
                sources.append(TomlConfigSettingsSource(settings_cls, toml_file=toml_file))
            return tuple(sources)

    return _Settings()
