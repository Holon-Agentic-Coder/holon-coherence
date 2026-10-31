"""Server-Sent Events (SSE) stream parsing and reassembly routines."""

from __future__ import annotations

import logging
from typing import Any

from holon_coherence.parsers.tokens import TokenCounts

logger = logging.getLogger(__name__)


def find_nested_key(data: Any, target_keys: tuple[str, ...] | str, max_depth: int = 10) -> Any:  # noqa: C901, PLR0912
    """Recursively searches nested dicts/lists to find the first occurrence of any key in target_keys.

    Evaluates target keys on the immediate node before recursively traversing child dictionaries
    or lists in depth-first order.
    """
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


KNOWN_PROVIDERS: tuple[str, ...] = ("anthropic", "openai", "gemini")


def extract_sse_content(resp_text: str, provider: str) -> str:
    """Extracts aggregated completion text from SSE lines."""
    if not provider or provider.strip().lower() not in KNOWN_PROVIDERS:
        return ""
    from holon_coherence.providers import get_provider

    return get_provider(provider).extract_sse_content(resp_text)


def extract_sse_token_counts(resp_text: str, req_data: dict[str, Any], provider: str) -> TokenCounts:
    """Extracts (input_tokens, output_tokens, cache_read_tokens) from SSE stream text.

    Args:
        resp_text: Full raw SSE text accumulated from stream chunks.
        req_data: Original request payload dictionary used for input token fallback estimation.
        provider: Detected model provider ("anthropic", "openai", "gemini").

    Returns:
        TokenCounts: A 3-tuple compatible object containing (input_tokens, output_tokens, cache_read_tokens).

    Note:
        When explicit usage metadata is absent from the SSE stream chunks, fallback token estimation
        derives counts from accumulated character counts using an integer division heuristic of
        1 token per 4 characters (i.e. chars // 4).
    """
    from holon_coherence.providers import get_provider

    return get_provider(provider).token_counts_from_sse(resp_text, req_data)


def extract_sse_cache_read_tokens(resp_text: str) -> int:
    """Extracts cache_read_input_tokens from Anthropic SSE text if present.

    Delegates to extract_sse_token_counts to ensure single-pass SSE stream line parsing.
    """
    counts = extract_sse_token_counts(resp_text, {}, "anthropic")
    return counts.cache_read_tokens
