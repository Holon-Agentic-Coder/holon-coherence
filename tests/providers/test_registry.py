"""Unit tests for provider registry and resolution."""

from __future__ import annotations

from holon_coherence.providers import (
    ProviderFormat,
    detect_provider_name,
    get_provider,
    resolve_provider,
)
from holon_coherence.providers.anthropic import AnthropicProvider
from holon_coherence.providers.gemini import GeminiProvider
from holon_coherence.providers.openai import OpenAIProvider


def test_registry_get_known_providers() -> None:
    anthropic = get_provider("anthropic")
    assert isinstance(anthropic, AnthropicProvider)
    assert isinstance(anthropic, ProviderFormat)

    gemini = get_provider("gemini")
    assert isinstance(gemini, GeminiProvider)
    assert isinstance(gemini, ProviderFormat)

    openai = get_provider("openai")
    assert isinstance(openai, OpenAIProvider)
    assert isinstance(openai, ProviderFormat)


def test_registry_fallback_to_openai() -> None:
    fallback = get_provider("unknown-custom-model")
    assert isinstance(fallback, OpenAIProvider)
    assert isinstance(fallback, ProviderFormat)

    empty_fallback = get_provider("")
    assert isinstance(empty_fallback, OpenAIProvider)


def test_detect_provider_name_from_url() -> None:
    assert detect_provider_name("https://api.anthropic.com/v1/messages") == "anthropic"
    assert detect_provider_name("https://generativelanguage.googleapis.com/v1beta/models") == "gemini"
    assert detect_provider_name("https://api.openai.com/v1/chat/completions") == "openai"
    assert detect_provider_name("https://openrouter.ai/api/v1/chat/completions") == "openai"


def test_detect_provider_name_from_payload() -> None:
    assert detect_provider_name("", {"anthropic-version": "2023-06-01"}) == "anthropic"
    assert (
        detect_provider_name(
            "",
            {"model": "claude-3-5-sonnet-20241022", "messages": [{"role": "user", "content": "hello"}]},
        )
        == "anthropic"
    )
    assert (
        detect_provider_name(
            "",
            {"system": "You are a helpful assistant", "messages": [{"role": "user", "content": "hello"}]},
        )
        == "anthropic"
    )
    assert detect_provider_name("", {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}) == "gemini"
    assert detect_provider_name("", {"messages": [{"role": "user", "content": "hello"}]}) == "openai"


def test_resolve_provider() -> None:
    p_anthropic = resolve_provider("https://api.anthropic.com/v1/messages")
    assert isinstance(p_anthropic, AnthropicProvider)

    p_gemini = resolve_provider("https://generativelanguage.googleapis.com/v1beta/models/gemini-pro")
    assert isinstance(p_gemini, GeminiProvider)

    p_openai = resolve_provider("https://api.openai.com/v1/chat/completions")
    assert isinstance(p_openai, OpenAIProvider)
