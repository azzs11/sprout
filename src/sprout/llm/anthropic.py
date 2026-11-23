"""Claude through the official Anthropic SDK (optional extra: ``sprout[anthropic]``).

Only used when the user explicitly selects it, because code then leaves the machine.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sprout.errors import ModelError
from sprout.llm.provider import JsonSchema

if TYPE_CHECKING:
    import anthropic

DEFAULT_ANTHROPIC_MODEL = "claude-opus-5-5"
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider:
    """Calls the Messages API. Low effort: summaries are short and many."""

    def __init__(self, model: str, api_key: str | None = None) -> None:
        try:
            import anthropic
        except ImportError as exc:
            raise ModelError(
                "The Anthropic provider needs the optional 'anthropic' package.",
                hint="Install it with: uv tool install 'sprout[anthropic]'",
            ) from exc
        self._model = model
        self._client: anthropic.Anthropic = anthropic.Anthropic(api_key=api_key)

    @property
    def name(self) -> str:
        """``anthropic:<model>``."""
        return f"anthropic:{self._model}"

    @property
    def remote(self) -> bool:
        """Calls go to Anthropic's API."""
        return True

    def complete(
        self, *, system: str, prompt: str, max_tokens: int, schema: JsonSchema | None = None
    ) -> str:
        """Return Claude's reply, falling back server-side if a request is declined.

        With ``schema``, the reply is JSON constrained by structured outputs.
        """
        import anthropic

        output_config: dict[str, object] = {"effort": "low"}
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": dict(schema)}

        try:
            response = self._client.beta.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_config=output_config,  # type: ignore[arg-type]
                betas=[_FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.AuthenticationError as exc:
            raise ModelError(
                "Anthropic rejected the API key.",
                hint="Check ANTHROPIC_API_KEY, or switch back with SPROUT_LLM_PROVIDER=ollama",
            ) from exc
        except anthropic.RateLimitError as exc:
            raise ModelError(
                "Anthropic rate limit reached.", hint="Wait and run the command again."
            ) from exc
        except anthropic.APIStatusError as exc:
            raise ModelError(f"Anthropic API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise ModelError(
                "Could not reach the Anthropic API.", hint="Check your connection."
            ) from exc
        if response.stop_reason == "refusal":
            raise ModelError("The model declined to summarise this commit.")
        return "".join(block.text for block in response.content if block.type == "text")
