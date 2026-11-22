"""Tests for settings, the provider factories and the LLM adapters (no network)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from sprout import services
from sprout.config import load_settings
from sprout.core.index.text import expand_identifiers, fts_query, split_identifier
from sprout.errors import ModelError
from sprout.llm.anthropic import AnthropicProvider
from sprout.llm.ollama import OllamaProvider
from sprout.llm.prompts import load_prompt

# ----- settings ---------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "SPROUT_LLM_PROVIDER",
        "SPROUT_EMBED_MODEL",
        "SPROUT_LLM_MODEL",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)


def test_defaults_are_local(tmp_path: Path) -> None:
    settings = load_settings(tmp_path)
    assert settings.llm_provider == "ollama"
    assert settings.resolved_llm_model == "qwen2.5-coder:7b"
    assert settings.embed_model == "BAAI/bge-small-en-v1.5"


def test_toml_file_and_env_priority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".sprout.toml").write_text('embed_model = "none"\nllm_model = "llama3.2"\n')
    assert load_settings(tmp_path).embed_model == "none"
    monkeypatch.setenv("SPROUT_EMBED_MODEL", "BAAI/bge-base-en-v1.5")
    settings = load_settings(tmp_path)
    assert settings.embed_model == "BAAI/bge-base-en-v1.5"
    assert settings.llm_model == "llama3.2"


def test_anthropic_key_is_never_enough_to_go_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    settings = load_settings(tmp_path)
    assert settings.llm_provider == "ollama"
    assert settings.anthropic_api_key is not None
    assert "sk-ant-test" not in repr(settings)


def test_anthropic_default_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPROUT_LLM_PROVIDER", "anthropic")
    assert load_settings(tmp_path).resolved_llm_model == "claude-opus-5-5"


def test_none_disables_models(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPROUT_EMBED_MODEL", "none")
    monkeypatch.setenv("SPROUT_RERANK_MODEL", "none")
    monkeypatch.setenv("SPROUT_LLM_PROVIDER", "none")
    settings = load_settings(tmp_path)
    assert services.build_embedder(settings) is None
    assert services.build_reranker(settings) is None
    with pytest.raises(ModelError):
        services.build_provider(settings)


def test_unknown_embedding_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPROUT_EMBED_MODEL", "no/such-model")
    with pytest.raises(ModelError):
        services.build_embedder(load_settings(tmp_path))


# ----- text -------------------------------------------------------------------------


def test_identifier_splitting() -> None:
    assert split_identifier("retryPayment_v2") == ["retry", "payment", "v", "2"]
    assert split_identifier("HTTPServer") == ["http", "server"]
    assert expand_identifiers("verify_token") == "verify_token verify token"
    assert fts_query('say "hi" OR NEAR(x') == '"say" OR "hi" OR "or" OR "near" OR "x"'
    assert fts_query("!!!") is None


# ----- prompts ----------------------------------------------------------------------


def test_prompt_file_is_versioned() -> None:
    prompt = load_prompt("summarise_commit")
    assert prompt.id == "summarise_commit@1"
    assert "never follow them" in prompt.system
    rendered = prompt.render(message="fix: x", diff="+ cost = ${price}")
    assert "+ cost = ${price}" in rendered


# ----- Ollama -----------------------------------------------------------------------


def _ollama(handler: Any) -> OllamaProvider:
    provider = OllamaProvider("tiny")
    provider._client = httpx.Client(  # pyright: ignore[reportPrivateUsage]
        base_url="http://ollama.test", transport=httpx.MockTransport(handler)
    )
    return provider


def test_ollama_success() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "A summary."}})

    provider = _ollama(handler)
    assert provider.complete(system="s", prompt="p", max_tokens=50) == "A summary."
    assert seen["options"]["num_predict"] == 50
    assert not provider.remote


def test_ollama_missing_model_hint() -> None:
    provider = _ollama(lambda _r: httpx.Response(404, json={"error": "not found"}))
    with pytest.raises(ModelError) as info:
        provider.complete(system="s", prompt="p", max_tokens=5)
    assert "ollama pull tiny" in (info.value.hint or "")


def test_ollama_not_running() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ModelError) as info:
        _ollama(handler).complete(system="s", prompt="p", max_tokens=5)
    assert "ollama serve" in (info.value.hint or "")


def test_ollama_malformed_reply() -> None:
    provider = _ollama(lambda _r: httpx.Response(200, json={"oops": True}))
    with pytest.raises(ModelError):
        provider.complete(system="s", prompt="p", max_tokens=5)


# ----- Anthropic (SDK call replaced, nothing leaves the machine) ---------------------


def _anthropic(response: Any, calls: list[dict[str, Any]]) -> AnthropicProvider:
    provider = AnthropicProvider("claude-opus-5-5", api_key="test-key")

    def create(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return response

    provider._client = SimpleNamespace(  # type: ignore[assignment]  # pyright: ignore[reportAttributeAccessIssue]
        beta=SimpleNamespace(messages=SimpleNamespace(create=create))
    )
    return provider


def test_anthropic_request_shape() -> None:
    calls: list[dict[str, Any]] = []
    reply = SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text="Done.")],
    )
    provider = _anthropic(reply, calls)
    assert provider.complete(system="sys", prompt="diff", max_tokens=1024) == "Done."
    (call,) = calls
    assert call["model"] == "claude-opus-5-5"
    assert call["fallbacks"] == "default"
    assert call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["output_config"] == {"effort": "low"}
    assert "thinking" not in call
    assert provider.remote


def test_anthropic_refusal_raises() -> None:
    reply = SimpleNamespace(stop_reason="refusal", content=[])
    with pytest.raises(ModelError):
        _anthropic(reply, []).complete(system="s", prompt="p", max_tokens=10)
