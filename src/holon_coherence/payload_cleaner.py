"""Context cleaning, tool output deduplication, and prompt cache optimization for LLM payloads."""

from __future__ import annotations

import copy
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from holon_coherence.providers import get_provider
from holon_coherence.providers.anthropic import (
    count_existing_cache_controls,
    deduplicate_anthropic_tool_outputs,
    inject_anthropic_cache_control,
    merge_consecutive_roles,
    summarize_anthropic_history,
)

logger = logging.getLogger(__name__)

_SECRET_DICT_KEY_PATTERN = re.compile(
    r"(?i)^(?:auth|credential|credentials|password|passwd|api[-_]?key|apikey|api[-_]?token|auth[-_]?token|access[-_]?token|refresh[-_]?token|id[-_]?token|secret[-_]?key|secret|private[-_]?key|client[-_]?secret|session[-_]?token)$"
)

_DEFAULT_RECENT_TURNS_TO_KEEP = 10
_RECENT_TURNS_TO_KEEP = _DEFAULT_RECENT_TURNS_TO_KEEP
"""Number of recent conversation turns preserved verbatim at the end of the history during summarization."""


@dataclass
class CleaningResult:
    """Result of context cleaning, tool output deduplication, and prompt cache optimization."""

    payload: dict[str, Any]
    tool_outputs_omitted: int = 0
    turns_summarized: int = 0
    cache_control_injected: int = 0
    chars_saved: int = 0


class JSONContextCleaner:
    """Cleans JSON LLM payloads by deduplicating tool outputs, summarizing history,

    and inserting prompt cache control breakpoints for Anthropic API schemas.
    """

    def __init__(
        self,
        enable_deduplication: bool = True,
        enable_prompt_caching: bool = True,
        max_turns: int = 50,
        recent_turns_to_keep: int = _DEFAULT_RECENT_TURNS_TO_KEEP,
    ):
        self.enable_deduplication = enable_deduplication
        self.enable_prompt_caching = enable_prompt_caching
        self.max_turns = max_turns
        self.recent_turns_to_keep = recent_turns_to_keep

    def process_payload(self, payload: dict[str, Any], provider: str = "anthropic") -> dict[str, Any]:
        """Convenience wrapper that returns only the cleaned payload dict, dropping stats.

        Matches the original `process_payload(payload)` signature for backward compatibility.
        """
        return self.process_payload_with_stats(payload, provider=provider).payload

    def process_payload_with_stats(self, payload: dict[str, Any], provider: str = "anthropic") -> CleaningResult:
        """Processes and optimizes an outgoing LLM JSON request payload and returns metrics.

        Args:
            payload: Parsed JSON payload dictionary.
            provider: Provider format ('anthropic', 'openai', or 'gemini').

        Returns:
            CleaningResult: Dataclass containing the cleaned payload and execution stats.
        """
        seen_content_hashes: dict[str, tuple[int, str]] = {}
        cleaned_payload = copy.deepcopy(payload)
        stats = {
            "tool_outputs_omitted": 0,
            "turns_summarized": 0,
            "cache_control_injected": 0,
        }

        provider_format = get_provider(provider)
        cleaned_payload = provider_format.clean(self, cleaned_payload, seen_content_hashes, stats=stats)

        try:
            raw_chars = len(json.dumps(payload))
            cleaned_chars = len(json.dumps(cleaned_payload))
            chars_saved = max(0, raw_chars - cleaned_chars)
        except Exception:
            chars_saved = 0

        return CleaningResult(
            payload=cleaned_payload,
            tool_outputs_omitted=stats["tool_outputs_omitted"],
            turns_summarized=stats["turns_summarized"],
            cache_control_injected=stats["cache_control_injected"],
            chars_saved=chars_saved,
        )

    def _clean_anthropic(
        self,
        payload: dict[str, Any],
        seen_content_hashes: dict[str, tuple[int, str]],
        stats: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        return get_provider("anthropic").clean(self, payload, seen_content_hashes, stats=stats)

    def _clean_openai(
        self,
        payload: dict[str, Any],
        seen_content_hashes: dict[str, tuple[int, str]],
        stats: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        return get_provider("openai").clean(self, payload, seen_content_hashes, stats=stats)

    def _clean_gemini(
        self,
        payload: dict[str, Any],
        seen_content_hashes: dict[str, tuple[int, str]],
        stats: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        return get_provider("gemini").clean(self, payload, seen_content_hashes, stats=stats)

    def _deduplicate_anthropic_tool_outputs(
        self,
        messages: list[dict[str, Any]],
        seen_content_hashes: dict[str, tuple[int, str]],
        stats: dict[str, int] | None = None,
    ) -> list[dict[str, Any]]:
        return deduplicate_anthropic_tool_outputs(messages, seen_content_hashes, stats=stats)

    def _is_clean_user_message(self, msg: dict[str, Any], provider: str) -> bool:
        if not isinstance(msg, dict):
            return False
        role = msg.get("role", "user" if provider == "gemini" else "")
        if role != "user":
            return False
        content = msg.get("content")
        if provider == "anthropic" and isinstance(content, list):
            return not any(isinstance(item, dict) and item.get("type") == "tool_result" for item in content)
        return True

    def _summarize_anthropic_history(
        self, messages: list[dict[str, Any]], stats: dict[str, int] | None = None
    ) -> list[dict[str, Any]]:
        return summarize_anthropic_history(messages, self.recent_turns_to_keep, stats=stats)

    def _merge_consecutive_roles(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return merge_consecutive_roles(messages)

    def _count_existing_cache_controls(self, payload: dict[str, Any]) -> int:
        return count_existing_cache_controls(payload)

    def _inject_anthropic_cache_control(
        self, payload: dict[str, Any], stats: dict[str, int] | None = None
    ) -> dict[str, Any]:
        return inject_anthropic_cache_control(payload, stats=stats)
