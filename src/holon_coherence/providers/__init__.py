"""Provider wire format implementations and registry."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from holon_coherence.providers.base import ProviderFormat

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
    """Registers a provider instance in the global registry."""
    _REGISTRY[name.strip().lower()] = provider


def _load_default_providers() -> None:
    """Lazily loads and registers default provider implementations."""
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

        _REGISTRY.setdefault("openai", OpenAIProvider())
    except ImportError:
        pass


def get_provider(name: str) -> ProviderFormat:
    """Retrieves the provider implementation for a given provider name, defaulting to openai."""
    _load_default_providers()
    key = name.strip().lower() if name else ""
    if key in _REGISTRY:
        return _REGISTRY[key]
    if "openai" in _REGISTRY:
        return _REGISTRY["openai"]
    raise KeyError(f"No provider registered for '{name}' and fallback 'openai' is unavailable.")


def _detect_by_url(url_or_path: str) -> str | None:
    url_lower = url_or_path.lower()
    target = url_lower if "://" in url_lower else f"https://{url_lower}"
    parsed = urlparse(target)
    hostname = parsed.hostname or url_lower

    if "anthropic" in url_lower or "v1/messages" in url_lower:
        return "anthropic"
    if (
        hostname == "generativelanguage.googleapis.com"
        or hostname.endswith(".generativelanguage.googleapis.com")
        or "gemini" in url_lower
        or "generatecontent" in url_lower
        or "streamgeneratecontent" in url_lower
    ):
        return "gemini"
    if any(p in url_lower for p in OPENAI_PROVIDERS):
        return "openai"
    return None


def _detect_by_payload(payload: dict[str, Any]) -> str | None:
    if "anthropic-version" in payload or "anthropic_version" in payload:
        return "anthropic"
    model = payload.get("model", "")
    if isinstance(model, str) and "claude" in model.lower():
        return "anthropic"
    if "contents" in payload:
        return "gemini"
    if "system" in payload:
        return "anthropic"
    if "messages" in payload or "prompt" in payload:
        return "openai"
    return None


def detect_provider_name(url_or_path: str, payload: dict[str, Any] | None = None) -> str:
    """Infers provider name from request URL or payload signature."""
    if url_or_path:
        detected = _detect_by_url(url_or_path)
        if detected:
            return detected
    if payload and isinstance(payload, dict):
        detected = _detect_by_payload(payload)
        if detected:
            return detected
    return "unknown"


def resolve_provider(url_or_path: str, payload: dict[str, Any] | None = None) -> ProviderFormat:
    """Resolves provider implementation from URL or payload heuristics."""
    name = detect_provider_name(url_or_path, payload)
    return get_provider(name)


__all__ = ["ProviderFormat", "detect_provider_name", "get_provider", "register_provider", "resolve_provider"]
