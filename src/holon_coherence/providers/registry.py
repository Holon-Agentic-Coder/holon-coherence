from __future__ import annotations

from typing import Any

from holon_coherence.providers.base import ProviderFormat

DEFAULT_FALLBACK_PROVIDER_NAME = "openai"
UNKNOWN_PROVIDER_NAME = "unknown"
GEMINI_API_HOSTNAME = "generativelanguage.googleapis.com"

OPENAI_PROVIDERS: tuple[str, ...] = (
    "openai",
    "openrouter",
    "deepseek",
    "groq",
    "together",
    "mistral",
    "fireworks",
    "ollama",
    "vllm",
    "lmstudio",
    "chat/completions",
    "v1/completions",
)

_REGISTRY: dict[str, ProviderFormat] = {}


def register_provider(name: str, provider: ProviderFormat) -> None:
    _REGISTRY[name.strip().lower()] = provider


def _load_default_providers() -> None:
    try:
        from holon_coherence.providers.anthropic import AnthropicProvider

        _REGISTRY.setdefault("anthropic", AnthropicProvider())
    except ImportError:
        pass

    try:
        from holon_coherence.providers.gemini import GeminiProvider

        _REGISTRY.setdefault("gemini", GeminiProvider())
    except ImportError:
        pass

    try:
        from holon_coherence.providers.openai import OpenAIProvider

        _REGISTRY.setdefault(DEFAULT_FALLBACK_PROVIDER_NAME, OpenAIProvider())
    except ImportError:
        pass


def _ordered_providers() -> list[tuple[str, ProviderFormat]]:
    _load_default_providers()
    ordered = [(name, provider) for name, provider in _REGISTRY.items() if name != DEFAULT_FALLBACK_PROVIDER_NAME]
    if DEFAULT_FALLBACK_PROVIDER_NAME in _REGISTRY:
        ordered.append((DEFAULT_FALLBACK_PROVIDER_NAME, _REGISTRY[DEFAULT_FALLBACK_PROVIDER_NAME]))
    return ordered


def get_provider(name: str) -> ProviderFormat:
    _load_default_providers()
    key = name.strip().lower() if name else ""
    if key in _REGISTRY:
        return _REGISTRY[key]
    if DEFAULT_FALLBACK_PROVIDER_NAME in _REGISTRY:
        return _REGISTRY[DEFAULT_FALLBACK_PROVIDER_NAME]
    raise KeyError(
        f"No provider registered for '{name}' and fallback '{DEFAULT_FALLBACK_PROVIDER_NAME}' is unavailable."
    )


def registered_provider_names() -> tuple[str, ...]:
    _load_default_providers()
    return tuple(_REGISTRY.keys())


def is_registered_provider(name: str) -> bool:
    _load_default_providers()
    return bool(name and name.strip().lower() in _REGISTRY)


def is_non_cloud_provider_host(provider_name: str, host: str) -> bool:
    _load_default_providers()
    if not provider_name or not host:
        return False
    provider = _REGISTRY.get(provider_name.strip().lower())
    is_cloud_host = getattr(provider, "is_cloud_host", None)
    if callable(is_cloud_host):
        return not bool(is_cloud_host(host.lower()))
    return False


def detect_provider_name(url_or_path: str, payload: dict[str, Any] | None = None) -> str:
    ordered = _ordered_providers()
    if url_or_path:
        for name, provider in ordered:
            if provider.matches(url_or_path, None):
                return name
    if payload and isinstance(payload, dict):
        for name, provider in ordered:
            if provider.matches(url_or_path, payload):
                return name
    return UNKNOWN_PROVIDER_NAME


def resolve_provider(url_or_path: str, payload: dict[str, Any] | None = None) -> ProviderFormat:
    name = detect_provider_name(url_or_path, payload)
    return get_provider(name)


__all__ = [
    "DEFAULT_FALLBACK_PROVIDER_NAME",
    "GEMINI_API_HOSTNAME",
    "OPENAI_PROVIDERS",
    "UNKNOWN_PROVIDER_NAME",
    "detect_provider_name",
    "get_provider",
    "is_non_cloud_provider_host",
    "is_registered_provider",
    "register_provider",
    "registered_provider_names",
    "resolve_provider",
]
