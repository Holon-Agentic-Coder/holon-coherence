"""Provider wire format protocol definitions and type annotations."""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from holon_coherence.parsers.tokens import TokenCounts

ProviderName = Literal["anthropic", "openai", "gemini"]


@runtime_checkable
class ProviderFormat(Protocol):
    """Protocol defining format operations for a specific LLM wire format."""

    def clean(
        self,
        cleaner: Any,
        payload: dict[str, Any],
        seen_content_hashes: dict[str, tuple[int, str]],
        stats: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """Formats and cleans request payloads (tool deduplication, turn truncation/summarization,
        cache breakpoint injection).
        """
        ...

    def token_counts_from_sse(
        self,
        resp_text: str,
        req_data: dict[str, Any],
    ) -> TokenCounts:
        """Extracts input, output, and cache read token counts from raw SSE text stream."""
        ...

    def token_counts_from_dict(
        self,
        req_data: dict[str, Any],
        resp_data: dict[str, Any],
    ) -> TokenCounts:
        """Extracts token counts from a parsed dictionary response."""
        ...

    def extract_sse_content(self, resp_text: str) -> str:
        """Extracts aggregated completion text or tool call strings from SSE chunks."""
        ...

    def extract_cache_key_parts(
        self,
        payload: dict[str, Any],
        max_recent_turns: int = 2,
    ) -> tuple[str, str]:
        """Extracts (user_content, system_prompt) for hybrid semantic cache key generation."""
        ...
