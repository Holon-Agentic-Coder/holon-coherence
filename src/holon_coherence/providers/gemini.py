"""Gemini wire format implementation."""

from __future__ import annotations

import copy
import hashlib
import json
import logging
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from holon_coherence.parsers.tokens import TokenCounts, estimate_chars, safe_int
from holon_coherence.providers.anthropic import merge_consecutive_roles
from holon_coherence.providers.base import ProviderFormat

if TYPE_CHECKING:
    from holon_coherence.payload_cleaner import JSONContextCleaner

logger = logging.getLogger(__name__)


def _iter_sse_chunks(resp_text: str) -> Iterator[dict[str, Any]]:
    for line in resp_text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        json_str = line[5:].strip()
        if not json_str or json_str == "[DONE]":
            continue
        try:
            chunk = json.loads(json_str)
            if isinstance(chunk, dict):
                yield chunk
        except Exception:
            continue


def _dedup_func_response(
    part_copy: dict[str, Any],
    turn_idx: int,
    is_older: bool,
    seen_content_hashes: dict[str, tuple[int, str]],
    stats: dict[str, int] | None,
) -> None:
    func_resp = part_copy["functionResponse"]
    resp_data = func_resp.get("response", {})
    func_name = func_resp.get("name", f"func_{turn_idx}")
    serialized = json.dumps(resp_data, sort_keys=True) if isinstance(resp_data, dict) else str(resp_data)
    if len(serialized) > 100:
        content_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        if content_hash in seen_content_hashes and is_older:
            prev_turn, _ = seen_content_hashes[content_hash]
            func_resp["response"] = {"content": f"[Tool output omitted: identical output matches Turn {prev_turn}]"}
            if stats is not None:
                stats["tool_outputs_omitted"] += 1
        else:
            seen_content_hashes[content_hash] = (turn_idx, func_name)


def _dedup_text_part(
    part_copy: dict[str, Any],
    turn_idx: int,
    is_older: bool,
    seen_content_hashes: dict[str, tuple[int, str]],
    stats: dict[str, int] | None,
) -> None:
    text = part_copy.get("text", "")
    if isinstance(text, str) and len(text) > 100:
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if text_hash in seen_content_hashes and is_older:
            prev_turn, _ = seen_content_hashes[text_hash]
            part_copy["text"] = f"[Tool output omitted: identical output matches Turn {prev_turn}]"
            if stats is not None:
                stats["tool_outputs_omitted"] += 1
        else:
            seen_content_hashes[text_hash] = (turn_idx, f"turn_{turn_idx}")


def _dedup_gemini_part(
    part: Any,
    turn_idx: int,
    is_older: bool,
    seen_content_hashes: dict[str, tuple[int, str]],
    stats: dict[str, int] | None,
) -> Any:
    if not isinstance(part, dict):
        return part
    part_copy = copy.deepcopy(part)
    if "functionResponse" in part_copy and isinstance(part_copy["functionResponse"], dict):
        _dedup_func_response(part_copy, turn_idx, is_older, seen_content_hashes, stats)
    else:
        _dedup_text_part(part_copy, turn_idx, is_older, seen_content_hashes, stats)
    return part_copy


def deduplicate_gemini_contents(
    contents: list[dict[str, Any]],
    enable_dedup: bool,
    seen_content_hashes: dict[str, tuple[int, str]],
    stats: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Deduplicates function responses and repeated text in Gemini contents history."""
    if not enable_dedup:
        return [copy.deepcopy(t) if isinstance(t, dict) else t for t in contents]
    cleaned: list[dict[str, Any]] = []
    turn_count = len(contents)
    for turn_idx, turn in enumerate(contents):
        if not isinstance(turn, dict):
            cleaned.append(turn)
            continue
        turn_copy = copy.deepcopy(turn)
        is_older = turn_idx < (turn_count - 2)
        parts = turn_copy.get("parts", [])
        if isinstance(parts, list):
            turn_copy["parts"] = [_dedup_gemini_part(p, turn_idx, is_older, seen_content_hashes, stats) for p in parts]
        cleaned.append(turn_copy)
    return cleaned


def _is_clean_gemini_user_message(turn: dict[str, Any]) -> bool:
    if not isinstance(turn, dict):
        return False
    role = turn.get("role", "user")
    return role == "user"


def _find_gemini_suffix_idx(contents: list[dict[str, Any]], recent_turns_to_keep: int) -> int | None:
    target_idx = len(contents) - recent_turns_to_keep
    for i in range(target_idx, 0, -1):
        if _is_clean_gemini_user_message(contents[i]):
            return i
    for i in range(target_idx + 1, len(contents)):
        if _is_clean_gemini_user_message(contents[i]):
            return i
    return None


def summarize_gemini_history(
    contents: list[dict[str, Any]],
    recent_turns_to_keep: int,
    stats: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Summarizes intermediate history turns in Gemini content sequence."""
    suffix_idx = _find_gemini_suffix_idx(contents, recent_turns_to_keep)
    if suffix_idx is None or suffix_idx <= 1:
        return contents

    prefix = contents[:1]
    suffix = contents[suffix_idx:]
    middle_count = len(contents) - len(prefix) - len(suffix)
    if middle_count <= 0:
        return contents

    if stats is not None:
        stats["turns_summarized"] += middle_count

    summary_msg = {
        "role": "model",
        "parts": [{"text": f"[Summary of omitted {middle_count} intermediate conversation turns]"}],
    }
    return merge_consecutive_roles([*prefix, summary_msg, *suffix])


def _parse_gemini_usage(usage: dict[str, Any]) -> tuple[int, int, int, int]:
    inp = safe_int(usage.get("promptTokenCount"))
    out = safe_int(usage.get("candidatesTokenCount"))
    cached = safe_int(usage.get("cachedContentTokenCount")) if "cachedContentTokenCount" in usage else 0
    reasoning = safe_int(usage.get("reasoningTokenCount")) if "reasoningTokenCount" in usage else 0
    return inp, out, cached, reasoning


def _process_gemini_part_len(part: Any) -> int:
    if isinstance(part, str) and part:
        return len(part)
    if not isinstance(part, dict):
        return 0
    acc_len = 0
    text = part.get("text", "")
    if isinstance(text, str) and text:
        acc_len += len(text)
    func_call = part.get("functionCall")
    if isinstance(func_call, dict):
        fn_name = func_call.get("name", "")
        if isinstance(fn_name, str) and fn_name:
            acc_len += len(fn_name)
        fn_args = func_call.get("args")
        if isinstance(fn_args, dict):
            acc_len += len(json.dumps(fn_args))
        elif isinstance(fn_args, str) and fn_args:
            acc_len += len(fn_args)
    return acc_len


def _process_gemini_candidate_len(cand: Any) -> int:
    if isinstance(cand, str) and cand:
        return len(cand)
    if not isinstance(cand, dict):
        return 0
    content = cand.get("content")
    if isinstance(content, str) and content:
        return len(content)
    if not isinstance(content, dict):
        return 0
    parts = content.get("parts")
    if not isinstance(parts, list):
        return 0
    return sum(_process_gemini_part_len(p) for p in parts)


def _process_gemini_candidates(
    candidates: list[Any],
    accumulated: list[str],
) -> int:
    added_len = 0
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        content = cand.get("content")
        if isinstance(content, dict):
            parts = content.get("parts")
            if isinstance(parts, list):
                for part in parts:
                    if not isinstance(part, dict):
                        continue
                    if "text" in part and isinstance(part["text"], str):
                        accumulated.append(part["text"])
                        added_len += len(part["text"])
                    fc = part.get("functionCall")
                    if isinstance(fc, dict):
                        serialized = json.dumps(fc)
                        accumulated.append(serialized)
                        added_len += len(serialized)
    return added_len


def _extract_gemini_user_content(contents: Any, prompt: Any, max_recent_turns: int) -> str:
    user_texts: list[str] = []
    if isinstance(contents, list):
        user_turns = [turn for turn in contents if isinstance(turn, dict) and turn.get("role") in ("user", None, "")]
        recent = user_turns[-max_recent_turns:] if max_recent_turns > 0 else user_turns
        for turn in recent:
            parts = turn.get("parts")
            if isinstance(parts, list):
                for part in parts:
                    if isinstance(part, str):
                        user_texts.append(part)
                    elif isinstance(part, dict) and isinstance(part.get("text"), str):
                        user_texts.append(part["text"])
    if not user_texts and isinstance(prompt, str) and prompt:
        user_texts.append(prompt)
    return " ".join(user_texts)


def _extract_gemini_system_prompt(payload: dict[str, Any]) -> str:
    system_val = payload.get("system_instruction") or payload.get("systemInstruction")
    if system_val is None:
        return ""
    if isinstance(system_val, str):
        return system_val.strip()
    texts: list[str] = []
    if isinstance(system_val, dict):
        parts = system_val.get("parts", [])
        if isinstance(parts, list):
            for part in parts:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    texts.append(part["text"])
                elif isinstance(part, str):
                    texts.append(part)
        elif isinstance(system_val.get("text"), str):
            texts.append(system_val["text"])
    return " ".join(texts).strip()


class GeminiProvider(ProviderFormat):
    """Wire format implementation for Google Gemini API."""

    def clean(
        self,
        cleaner: JSONContextCleaner,
        payload: dict[str, Any],
        seen_content_hashes: dict[str, tuple[int, str]],
        stats: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """Cleans Gemini request payloads (function response deduplication and turn summarization)."""
        contents = payload.get("contents")
        if contents is None or not isinstance(contents, list):
            return payload

        enable_dedup = getattr(cleaner, "enable_deduplication", True)
        cleaned_contents = deduplicate_gemini_contents(contents, enable_dedup, seen_content_hashes, stats=stats)

        max_turns = getattr(cleaner, "max_turns", 40)
        recent_turns_to_keep = getattr(cleaner, "recent_turns_to_keep", 10)
        if len(cleaned_contents) > max_turns:
            cleaned_contents = summarize_gemini_history(cleaned_contents, recent_turns_to_keep, stats=stats)

        payload["contents"] = cleaned_contents
        return payload

    def extract_sse_content(self, resp_text: str) -> str:
        """Extracts text and function calls from Gemini SSE stream chunks."""
        accumulated: list[str] = []
        for chunk in _iter_sse_chunks(resp_text):
            candidates = chunk.get("candidates")
            if isinstance(candidates, list):
                _process_gemini_candidates(candidates, accumulated)
        return "".join(accumulated)

    def token_counts_from_sse(self, resp_text: str, req_data: dict[str, Any]) -> TokenCounts:
        """Extracts token counts from Gemini SSE stream chunks or falls back to char counts."""
        inp_tok: int | None = None
        out_tok: int | None = None
        cached_tok: int | None = None
        reasoning_tok: int | None = None
        acc_len = 0

        for chunk in _iter_sse_chunks(resp_text):
            usage = chunk.get("usageMetadata") or chunk.get("usage")
            if isinstance(usage, dict):
                i, o, c, r = _parse_gemini_usage(usage)
                inp_tok, out_tok, cached_tok, reasoning_tok = i, o, c, r
            candidates = chunk.get("candidates") or chunk.get("choices") or chunk.get("contents")
            if isinstance(candidates, list):
                acc_len += sum(_process_gemini_candidate_len(c) for c in candidates)

        input_tokens = (
            inp_tok
            if inp_tok is not None
            else max(1, estimate_chars(req_data) // 4)
            if estimate_chars(req_data) > 0
            else 0
        )
        output_tokens = out_tok if out_tok is not None else max(1, acc_len // 4) if acc_len > 0 else 0

        return TokenCounts(
            input_tokens,
            output_tokens,
            cached_tok or 0,
            cache_creation_tokens=0,
            reasoning_tokens=reasoning_tok or 0,
        )

    def token_counts_from_dict(self, req_data: dict[str, Any], resp_data: dict[str, Any]) -> TokenCounts:
        """Extracts token counts from Gemini dictionary response."""
        input_tokens = 0
        output_tokens = 0
        cache_read = 0
        reasoning = 0
        parsed = False

        usage = resp_data.get("usageMetadata") or resp_data.get("usage") if isinstance(resp_data, dict) else None
        if isinstance(usage, dict) and "promptTokenCount" in usage and "candidatesTokenCount" in usage:
            input_tokens, output_tokens, cache_read, reasoning = _parse_gemini_usage(usage)
            parsed = True

        if not parsed:
            tokens_logger = logging.getLogger("holon_coherence.parsers.tokens")
            tokens_logger.debug(
                "Provider usage dictionary missing or invalid for %s; estimating token counts from payload characters",
                "gemini",
            )
            in_chars = estimate_chars(req_data)
            out_chars = estimate_chars(resp_data)
            input_tokens = max(1, in_chars // 4) if in_chars > 0 else 0
            output_tokens = max(1, out_chars // 4) if out_chars > 0 else 0

        return TokenCounts(
            input_tokens,
            output_tokens,
            cache_read,
            cache_creation_tokens=0,
            reasoning_tokens=reasoning,
        )

    def extract_cache_key_parts(self, payload: dict[str, Any], max_recent_turns: int = 2) -> tuple[str, str]:
        """Extracts (user_content, system_prompt) for Gemini requests."""
        if not isinstance(payload, dict):
            return str(payload) if payload else "", ""
        user_content = _extract_gemini_user_content(payload.get("contents"), payload.get("prompt"), max_recent_turns)
        system_prompt = _extract_gemini_system_prompt(payload)
        return user_content, system_prompt
