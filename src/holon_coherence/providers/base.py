from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from holon_coherence.providers._common import TokenCounts

if TYPE_CHECKING:
    from holon_coherence.payload_cleaner import JSONContextCleaner


@runtime_checkable
class ProviderFormat(Protocol):
    def matches(self, url: str, payload: dict[str, Any] | None = None) -> bool: ...

    def clean(
        self,
        cleaner: JSONContextCleaner,
        payload: dict[str, Any],
        seen_content_hashes: dict[str, tuple[int, str]],
        stats: dict[str, int] | None = None,
    ) -> dict[str, Any]: ...

    def token_counts_from_sse(
        self,
        resp_text: str,
        req_data: dict[str, Any],
    ) -> TokenCounts: ...

    def token_counts_from_dict(
        self,
        req_data: dict[str, Any],
        resp_data: dict[str, Any],
    ) -> TokenCounts: ...

    def extract_sse_content(self, resp_text: str) -> str: ...

    def extract_cache_key_parts(
        self,
        payload: dict[str, Any],
        max_recent_turns: int = 2,
    ) -> tuple[str, str]: ...
