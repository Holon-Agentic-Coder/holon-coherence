from __future__ import annotations

import copy
import json
import logging
from collections.abc import Collection, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from holon_coherence.providers import get_provider
from holon_coherence.providers.anthropic import (
    count_existing_cache_controls,
    deduplicate_anthropic_tool_outputs,
    inject_anthropic_cache_control,
    merge_consecutive_roles,
    sanitize_and_normalize_cache_controls,
    summarize_anthropic_history,
)
from holon_coherence.reduction_passes import (
    ReductionContext,
    ReductionPassRegistry,
    default_pass_registry,
)

logger = logging.getLogger(__name__)

_DEFAULT_RECENT_TURNS_TO_KEEP = 10
_RECENT_TURNS_TO_KEEP = _DEFAULT_RECENT_TURNS_TO_KEEP
_IN_PLACE_MUTATION: ContextVar[bool] = ContextVar("_in_place_mutation", default=False)


@contextmanager
def in_place_cleaning() -> Iterator[None]:
    token = _IN_PLACE_MUTATION.set(True)
    try:
        yield
    finally:
        _IN_PLACE_MUTATION.reset(token)


def _serialized_length(payload: Any) -> int | None:
    try:
        return len(json.dumps(payload))
    except Exception:
        return None


@dataclass
class CleaningResult:
    payload: dict[str, Any]
    tool_outputs_omitted: int = 0
    turns_summarized: int = 0
    cache_control_injected: int = 0
    chars_saved: int = 0


@dataclass(eq=False)
class JSONContextCleaner:
    enable_deduplication: bool = True
    enable_prompt_caching: bool = True
    max_turns: int = 50
    recent_turns_to_keep: int = _DEFAULT_RECENT_TURNS_TO_KEEP
    pass_registry: ReductionPassRegistry | None = None
    enabled_passes: Collection[str] | None = None
    disabled_passes: Collection[str] | None = None

    def __post_init__(self) -> None:
        if self.pass_registry is None:
            self.pass_registry = default_pass_registry()
        if self.enabled_passes is not None:
            self.enabled_passes = frozenset(self.enabled_passes)
        if self.disabled_passes is not None:
            self.disabled_passes = frozenset(self.disabled_passes)

    def process_payload(self, payload: dict[str, Any], provider: str = "anthropic") -> dict[str, Any]:
        return self.process_payload_with_stats(payload, provider=provider).payload

    def process_payload_with_stats(
        self,
        payload: dict[str, Any],
        provider: str = "anthropic",
        *,
        copy_payload: bool | None = None,
    ) -> CleaningResult:
        seen_content_hashes: dict[str, tuple[int, str]] = {}
        should_copy = (not _IN_PLACE_MUTATION.get()) if copy_payload is None else copy_payload
        raw_chars = _serialized_length(payload)
        cleaned_payload = copy.deepcopy(payload) if should_copy else payload
        stats = {
            "tool_outputs_omitted": 0,
            "turns_summarized": 0,
            "cache_control_injected": 0,
        }

        context = ReductionContext(
            cleaner=self,
            provider=provider,
            seen_content_hashes=seen_content_hashes,
            stats=stats,
        )
        cleaned_payload = self.pass_registry.run(
            cleaned_payload,
            context,
            enabled_passes=self.enabled_passes,
            disabled_passes=self.disabled_passes,
        )

        cleaned_chars = _serialized_length(cleaned_payload) if raw_chars is not None else None
        chars_saved = max(0, raw_chars - cleaned_chars) if raw_chars is not None and cleaned_chars is not None else 0

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

    def _sanitize_and_normalize_cache_controls(self, payload: dict[str, Any]) -> dict[str, Any]:
        return sanitize_and_normalize_cache_controls(payload)

    def _inject_anthropic_cache_control(
        self, payload: dict[str, Any], stats: dict[str, int] | None = None
    ) -> dict[str, Any]:
        return inject_anthropic_cache_control(payload, stats=stats)
