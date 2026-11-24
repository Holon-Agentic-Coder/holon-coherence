from __future__ import annotations

import logging
from typing import Any

from holon_coherence.parsers.tokens import TokenCounts

logger = logging.getLogger(__name__)

DEFAULT_MAX_TRAVERSAL_DEPTH = 10
ANTHROPIC_PROVIDER_NAME = "anthropic"


def find_nested_key(data: Any, target_keys: tuple[str, ...] | str, max_depth: int = 10) -> Any:  # noqa: C901, PLR0912
    if not isinstance(data, (dict, list)):
        return None
    if max_depth <= 0 or not data:
        return None
    if isinstance(target_keys, str):
        target_keys = (target_keys,)

    if isinstance(data, dict):
        for key in target_keys:
            if key in data and data[key] is not None:
                return data[key]
        for val in data.values():
            if isinstance(val, (dict, list)):
                res = find_nested_key(val, target_keys, max_depth - 1)
                if res is not None:
                    return res
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, (dict, list)):
                res = find_nested_key(item, target_keys, max_depth - 1)
                if res is not None:
                    return res
    return None


KNOWN_PROVIDERS: tuple[str, ...] = (
    "anthropic",
    "openai",
    "gemini",
    "openrouter",
    "deepseek",
    "groq",
    "together",
)


def extract_sse_content(resp_text: str, provider: str) -> str:
    if not provider or provider.strip().lower() not in KNOWN_PROVIDERS:
        return ""
    from holon_coherence.providers import get_provider

    return get_provider(provider).extract_sse_content(resp_text)


def extract_sse_token_counts(resp_text: str, req_data: dict[str, Any], provider: str) -> TokenCounts:
    from holon_coherence.providers import get_provider

    return get_provider(provider).token_counts_from_sse(resp_text, req_data)


def extract_sse_cache_read_tokens(resp_text: str) -> int:
    counts = extract_sse_token_counts(resp_text, {}, ANTHROPIC_PROVIDER_NAME)
    return counts.cache_read_tokens
