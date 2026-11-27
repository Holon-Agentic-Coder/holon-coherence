from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

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


def _detect_by_url(url_or_path: str) -> str | None:
    url_lower = url_or_path.lower()
    target = url_lower if "://" in url_lower else f"https://{url_lower}"
    parsed = urlparse(target)
    hostname = parsed.hostname or url_lower

    if "anthropic" in url_lower or "v1/messages" in url_lower:
        return "anthropic"
    if (
        hostname == GEMINI_API_HOSTNAME
        or hostname.endswith(f".{GEMINI_API_HOSTNAME}")
        or "gemini" in url_lower
        or "generatecontent" in url_lower
        or "streamgeneratecontent" in url_lower
    ):
        return "gemini"
    if any(p in url_lower for p in OPENAI_PROVIDERS):
        return DEFAULT_FALLBACK_PROVIDER_NAME
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
        return DEFAULT_FALLBACK_PROVIDER_NAME
    return None


def detect_provider_name(url_or_path: str, payload: dict[str, Any] | None = None) -> str:
    if url_or_path:
        detected = _detect_by_url(url_or_path)
        if detected:
            return detected
    if payload and isinstance(payload, dict):
        detected = _detect_by_payload(payload)
        if detected:
            return detected
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
    "register_provider",
    "resolve_provider",
]
