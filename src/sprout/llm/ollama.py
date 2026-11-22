"""Local models through Ollama's HTTP API. Nothing leaves the machine."""

from __future__ import annotations

import httpx

from sprout.errors import ModelError

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "qwen2.5-coder:7b"


class OllamaProvider:
    """Calls ``POST /api/chat`` on a local Ollama server."""

    def __init__(
        self, model: str, base_url: str = DEFAULT_OLLAMA_URL, timeout: float = 120
    ) -> None:
        self._model = model
        self._client = httpx.Client(base_url=base_url, timeout=timeout)

    @property
    def name(self) -> str:
        """``ollama:<model>``."""
        return f"ollama:{self._model}"

    @property
    def remote(self) -> bool:
        """Ollama runs locally."""
        return False

    def available(self) -> bool:
        """True if the server answers within half a second."""
        try:
            return self._client.get("/api/tags", timeout=0.5).is_success
        except httpx.HTTPError:
            return False

    def complete(self, *, system: str, prompt: str, max_tokens: int) -> str:
        """Return the model's reply."""
        body = {
            "model": self._model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "options": {"num_predict": max_tokens, "temperature": 0},
        }
        try:
            response = self._client.post("/api/chat", json=body)
        except httpx.TransportError as exc:
            raise ModelError(
                f"Could not reach Ollama at {self._client.base_url}: {exc}",
                hint=f"Start it with: ollama serve, then run: ollama pull {self._model}",
            ) from exc
        if response.status_code == 404:
            raise ModelError(
                f"Ollama does not have the model {self._model}.",
                hint=f"Download it with: ollama pull {self._model}",
            )
        if response.is_error:
            raise ModelError(f"Ollama returned HTTP {response.status_code}: {response.text[:200]}")
        data: object = response.json()
        content = _content(data)
        if content is None:
            raise ModelError("Ollama returned a reply without message content.")
        return content

    def close(self) -> None:
        """Close the HTTP connection pool."""
        self._client.close()


def _content(data: object) -> str | None:
    if not isinstance(data, dict):
        return None
    message = data.get("message")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    if not isinstance(message, dict):
        return None
    content = message.get("content")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    return content if isinstance(content, str) else None
