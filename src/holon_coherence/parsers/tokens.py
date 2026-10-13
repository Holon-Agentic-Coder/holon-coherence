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


def extract_token_counts(
    req_data: dict[str, Any], resp_data: dict[str, Any] | str, provider: str
) -> tuple[int, int, int]:
    """Extracts (input_tokens, output_tokens, cache_read_tokens) from request/response data.

    Args:
        req_data: Request payload dictionary used for input token fallback estimation.
        resp_data: Response payload dictionary or raw SSE stream text string.
        provider: Detected model provider ("anthropic", "openai", "gemini").

    Returns:
        tuple[int, int, int]: A 3-tuple containing (input_tokens, output_tokens, cache_read_tokens).
            For Anthropic prompt caching, input_tokens reflects total input tokens (prompt tokens,
            cache read tokens, and cache creation tokens), while cache_read_tokens tracks ephemeral
            prompt cache read hits separately.

    Note:
        If provider usage metadata is missing or unparseable, fallback token counts are estimated
        using character count integer division (chars // 4 heuristic, ~4 characters per token).
    """
    if isinstance(resp_data, str):
        from holon_coherence.parsers.sse import extract_sse_token_counts

        return extract_sse_token_counts(resp_data, req_data, provider)

    input_tokens = 0
    output_tokens = 0
    cache_read_tokens = 0
    cache_creation_tokens = 0
    reasoning_tokens = 0
    parsed = False

    try:
        if isinstance(resp_data, dict):
            if provider == "anthropic":
                usage = resp_data.get("usage")
                if isinstance(usage, dict) and "input_tokens" in usage and "output_tokens" in usage:
                    cache_read_tokens = safe_int(usage.get("cache_read_input_tokens"))
                    cache_creation_tokens = safe_int(usage.get("cache_creation_input_tokens"))
                    input_tokens = safe_int(usage.get("input_tokens")) + cache_read_tokens + cache_creation_tokens
                    output_tokens = safe_int(usage.get("output_tokens"))
                    reasoning_tokens = safe_int(usage.get("reasoning_tokens")) or safe_int(usage.get("thinking_tokens"))
                    parsed = True
            elif provider == "openai":
                usage = resp_data.get("usage")
                if isinstance(usage, dict) and "prompt_tokens" in usage and "completion_tokens" in usage:
                    input_tokens = safe_int(usage.get("prompt_tokens"))
                    output_tokens = safe_int(usage.get("completion_tokens"))
                    prompt_tokens_details = usage.get("prompt_tokens_details")
                    if isinstance(prompt_tokens_details, dict) and "cached_tokens" in prompt_tokens_details:
                        cache_read_tokens = safe_int(prompt_tokens_details.get("cached_tokens"))
                    elif "cached_tokens" in usage:
                        cache_read_tokens = safe_int(usage.get("cached_tokens"))
                    comp_details = usage.get("completion_tokens_details")
                    if isinstance(comp_details, dict) and "reasoning_tokens" in comp_details:
                        reasoning_tokens = safe_int(comp_details.get("reasoning_tokens"))
                    parsed = True
            elif provider == "gemini":
                usage = resp_data.get("usageMetadata") or resp_data.get("usage")
                if isinstance(usage, dict) and "promptTokenCount" in usage and "candidatesTokenCount" in usage:
                    input_tokens = safe_int(usage.get("promptTokenCount"))
                    output_tokens = safe_int(usage.get("candidatesTokenCount"))
                    if "cachedContentTokenCount" in usage:
                        cache_read_tokens = safe_int(usage.get("cachedContentTokenCount"))
                    if "reasoningTokenCount" in usage:
                        reasoning_tokens = safe_int(usage.get("reasoningTokenCount"))
                    parsed = True
    except Exception:
        logger.debug("Failed to parse token counts for provider %s from response; using estimation fallback", provider)

    if not parsed:
        logger.debug(
            "Provider usage dictionary missing or invalid for %s; estimating token counts from payload characters",
            provider,
        )
        input_chars = estimate_chars(req_data)
        output_chars = estimate_chars(resp_data)
        input_tokens = max(1, input_chars // 4) if input_chars > 0 else 0
        output_tokens = max(1, output_chars // 4) if output_chars > 0 else 0

    return TokenCounts(
        input_tokens,
        output_tokens,
        cache_read_tokens,
        cache_creation_tokens=cache_creation_tokens,
        reasoning_tokens=reasoning_tokens,
    )


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
