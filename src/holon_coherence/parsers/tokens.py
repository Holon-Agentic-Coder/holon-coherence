from __future__ import annotations

import logging
from typing import Any

from holon_coherence.providers._common import (
    CHARS_PER_ESTIMATED_TOKEN,
    DEFAULT_MAX_ESTIMATE_DEPTH,
    PAYLOAD_TEXT_CONTAINER_KEYS,
    TokenCounts,
    estimate_chars,
    estimate_tokens_from_chars,
    safe_int,
)
from holon_coherence.providers.registry import get_provider

logger = logging.getLogger(__name__)


def extract_token_counts(req_data: dict[str, Any], resp_data: dict[str, Any] | str, provider: str) -> TokenCounts:
    provider_format = get_provider(provider)
    if isinstance(resp_data, str):
        return provider_format.token_counts_from_sse(resp_data, req_data)
    return provider_format.token_counts_from_dict(req_data, resp_data)


def extract_detailed_token_counts(
    req_data: dict[str, Any], resp_data: dict[str, Any] | str, provider: str
) -> dict[str, int]:
    counts = extract_token_counts(req_data, resp_data, provider)
    return {
        "input_tokens": counts[0],
        "output_tokens": counts[1],
        "cache_read_input_tokens": counts[2],
        "cache_creation_input_tokens": getattr(counts, "cache_creation_tokens", 0),
        "reasoning_tokens": getattr(counts, "reasoning_tokens", 0),
    }


__all__ = [
    "CHARS_PER_ESTIMATED_TOKEN",
    "DEFAULT_MAX_ESTIMATE_DEPTH",
    "PAYLOAD_TEXT_CONTAINER_KEYS",
    "TokenCounts",
    "estimate_chars",
    "estimate_tokens_from_chars",
    "extract_detailed_token_counts",
    "extract_token_counts",
    "safe_int",
]
