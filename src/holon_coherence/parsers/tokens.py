"""Token counting and payload estimation heuristics."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def safe_int(val: Any, default: int = 0) -> int:
    """Safely converts val to int, returning default on None or ValueError/TypeError."""
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def estimate_chars(data: Any, max_depth: int = 10) -> int:
    """Recursively estimates prompt/response characters from nested request/response structures.

    Returns 0 for unsupported primitive types or when max_depth is reached.
    """
    if max_depth <= 0:
        return 0
    if isinstance(data, str):
        return len(data)
    if isinstance(data, list):
        return sum(estimate_chars(x, max_depth - 1) for x in data)
    if isinstance(data, dict):
        total = 0
        found_target = False
        if "system" in data:
            total += estimate_chars(data["system"], max_depth - 1)
            found_target = True
        for key in ("messages", "message", "prompt", "contents", "parts", "choices", "candidates", "content", "text"):
            if key in data:
                total += estimate_chars(data[key], max_depth - 1)
                found_target = True
        if found_target:
            return total
        return sum(estimate_chars(v, max_depth - 1) for v in data.values())
    return 0


class TokenCounts(tuple):
    """3-tuple compatible with (input_tokens, output_tokens, cache_read_tokens) with extra metadata."""

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    reasoning_tokens: int

    def __new__(
        cls,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int,
        cache_creation_tokens: int = 0,
        reasoning_tokens: int = 0,
    ):
        inst = super().__new__(cls, (input_tokens, output_tokens, cache_read_tokens))
        inst.input_tokens = input_tokens
        inst.output_tokens = output_tokens
        inst.cache_read_tokens = cache_read_tokens
        inst.cache_creation_tokens = cache_creation_tokens
        inst.reasoning_tokens = reasoning_tokens
        return inst


def extract_token_counts(req_data: dict[str, Any], resp_data: dict[str, Any] | str, provider: str) -> TokenCounts:
    """Extracts (input_tokens, output_tokens, cache_read_tokens) from request/response data.

    Args:
        req_data: Request payload dictionary used for input token fallback estimation.
        resp_data: Response payload dictionary or raw SSE stream text string.
        provider: Detected model provider ("anthropic", "openai", "gemini").

    Returns:
        TokenCounts: A 3-tuple compatible object containing (input_tokens, output_tokens, cache_read_tokens).
            For Anthropic prompt caching, input_tokens reflects total input tokens (prompt tokens,
            cache read tokens, and cache creation tokens), while cache_read_tokens tracks ephemeral
            prompt cache read hits separately.

    Note:
        If provider usage metadata is missing or unparseable, fallback token counts are estimated
        using character count integer division (chars // 4 heuristic, ~4 characters per token).
    """
    from holon_coherence.providers import get_provider

    provider_format = get_provider(provider)
    if isinstance(resp_data, str):
        return provider_format.token_counts_from_sse(resp_data, req_data)
    return provider_format.token_counts_from_dict(req_data, resp_data)


def extract_detailed_token_counts(
    req_data: dict[str, Any], resp_data: dict[str, Any] | str, provider: str
) -> dict[str, int]:
    """Extracts normalized token counts and cache breakdown from request and response."""
    if isinstance(resp_data, str):
        from holon_coherence.parsers.sse import extract_sse_token_counts

        counts = extract_sse_token_counts(resp_data, req_data, provider)
    else:
        counts = extract_token_counts(req_data, resp_data, provider)
    return {
        "input_tokens": counts[0],
        "output_tokens": counts[1],
        "cache_read_input_tokens": counts[2],
        "cache_creation_input_tokens": getattr(counts, "cache_creation_tokens", 0),
        "reasoning_tokens": getattr(counts, "reasoning_tokens", 0),
    }
