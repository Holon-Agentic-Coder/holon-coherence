"""OpenAI wire format implementation."""

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


def _dedup_tool_output(
    msg_copy: dict[str, Any],
    turn_idx: int,
    is_older_turn: bool,
    seen_content_hashes: dict[str, tuple[int, str]],
    stats: dict[str, int] | None,
) -> None:
    content = msg_copy.get("content", "")
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    tool_res_id = msg_copy.get("tool_call_id", f"tool_result_{turn_idx}")
    if content_hash in seen_content_hashes and is_older_turn:
        prev_turn, _ = seen_content_hashes[content_hash]
        msg_copy["content"] = f"[Tool output omitted: identical output matches Turn {prev_turn}]"
        if stats is not None:
            stats["tool_outputs_omitted"] += 1
    else:
        seen_content_hashes[content_hash] = (turn_idx, tool_res_id)


def _dedup_message_content(
    msg_copy: dict[str, Any],
    turn_idx: int,
    is_older_turn: bool,
    seen_content_hashes: dict[str, tuple[int, str]],
    stats: dict[str, int] | None,
) -> None:
    content = msg_copy.get("content", "")
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if content_hash in seen_content_hashes and is_older_turn:
        prev_turn, _ = seen_content_hashes[content_hash]
        msg_copy["content"] = f"[Message content omitted: identical output matches Turn {prev_turn}]"
        if stats is not None:
            stats["tool_outputs_omitted"] += 1
    else:
        seen_content_hashes[content_hash] = (turn_idx, f"turn_{turn_idx}")


def _dedup_single_openai_message(
    msg: dict[str, Any],
    turn_idx: int,
    is_older_turn: bool,
    seen_content_hashes: dict[str, tuple[int, str]],
    stats: dict[str, int] | None,
) -> dict[str, Any]:
    msg_copy = copy.deepcopy(msg)
    role = msg_copy.get("role")
    content = msg_copy.get("content", "")
    if role == "tool" and isinstance(content, str) and len(content) > 100:
        _dedup_tool_output(msg_copy, turn_idx, is_older_turn, seen_content_hashes, stats)
    elif isinstance(content, str) and len(content) > 200:
        _dedup_message_content(msg_copy, turn_idx, is_older_turn, seen_content_hashes, stats)
    return msg_copy


def deduplicate_openai_messages(
    messages: list[dict[str, Any]],
    enable_dedup: bool,
    seen_content_hashes: dict[str, tuple[int, str]],
    stats: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Deduplicates repeated tool outputs and long message contents in OpenAI history."""
    if not enable_dedup:
        return [copy.deepcopy(m) if isinstance(m, dict) else m for m in messages]
    cleaned: list[dict[str, Any]] = []
    turn_count = len(messages)
    for turn_idx, msg in enumerate(messages):
        if not isinstance(msg, dict):
            cleaned.append(msg)
            continue
        is_older = turn_idx < (turn_count - 2)
        cleaned.append(_dedup_single_openai_message(msg, turn_idx, is_older, seen_content_hashes, stats))
    return cleaned


def _is_clean_openai_user_message(msg: dict[str, Any]) -> bool:
    return isinstance(msg, dict) and msg.get("role") == "user"


def _calculate_openai_prefix_len(messages: list[dict[str, Any]]) -> int:
    if len(messages) > 1:
        first, second = messages[0], messages[1]
        if (
            isinstance(first, dict)
            and first.get("role") == "system"
            and isinstance(second, dict)
            and second.get("role") == "user"
        ):
            return 2
    return 1


def _find_openai_suffix_idx(messages: list[dict[str, Any]], prefix_len: int, target_idx: int) -> int | None:
    for i in range(target_idx, len(messages)):
        if _is_clean_openai_user_message(messages[i]):
            return i
    for i in range(target_idx - 1, prefix_len, -1):
        if _is_clean_openai_user_message(messages[i]):
            return i
    return None


def summarize_openai_history(
    messages: list[dict[str, Any]],
    recent_turns_to_keep: int,
    stats: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Summarizes intermediate history turns in OpenAI message sequence."""
    prefix_len = _calculate_openai_prefix_len(messages)
    target_idx = max(prefix_len + 1, len(messages) - recent_turns_to_keep)
    suffix_idx = _find_openai_suffix_idx(messages, prefix_len, target_idx)

    if suffix_idx is None or suffix_idx <= prefix_len:
        return messages

    prefix = messages[:prefix_len]
    suffix = messages[suffix_idx:]
    middle_count = len(messages) - len(prefix) - len(suffix)
    if middle_count <= 0:
        return messages

    if stats is not None:
        stats["turns_summarized"] += middle_count

    summary_msg = {
        "role": "assistant",
        "content": f"[Summary of omitted {middle_count} intermediate conversation turns]",
    }
    return merge_consecutive_roles([*prefix, summary_msg, *suffix])


def _process_tool_calls_delta(tool_calls: list[Any], in_tool: bool, accumulated: list[str]) -> bool:
    curr_tool = in_tool
    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function")
        if not isinstance(fn, dict):
            continue
        fn_name = fn.get("name", "")
        args = fn.get("arguments", "")
        if fn_name:
            if curr_tool:
                accumulated.append(")")
            accumulated.append(f"{fn_name}(")
            curr_tool = True
        if args:
            accumulated.append(args)
    return curr_tool


def _process_choice_delta(choice: dict[str, Any], in_tool: bool, accumulated: list[str]) -> bool:
    curr_tool = in_tool
    delta = choice.get("delta")
    if isinstance(delta, dict):
        content = delta.get("content")
        if isinstance(content, str):
            if curr_tool:
                accumulated.append(")")
                curr_tool = False
            accumulated.append(content)

        tool_calls = delta.get("tool_calls")
        if isinstance(tool_calls, list):
            curr_tool = _process_tool_calls_delta(tool_calls, curr_tool, accumulated)

    if choice.get("finish_reason") in ("tool_calls", "stop") and curr_tool:
        accumulated.append(")")
        curr_tool = False
    return curr_tool


def _parse_openai_usage(usage: dict[str, Any]) -> tuple[int, int, int, int]:
    inp = safe_int(usage.get("prompt_tokens"))
    out = safe_int(usage.get("completion_tokens"))
    cached = 0
    prompt_details = usage.get("prompt_tokens_details")
    if isinstance(prompt_details, dict) and "cached_tokens" in prompt_details:
        cached = safe_int(prompt_details.get("cached_tokens"))
    elif "cached_tokens" in usage:
        cached = safe_int(usage.get("cached_tokens"))

    reasoning = 0
    comp_details = usage.get("completion_tokens_details")
    if isinstance(comp_details, dict) and "reasoning_tokens" in comp_details:
        reasoning = safe_int(comp_details.get("reasoning_tokens"))
    return inp, out, cached, reasoning


def _extract_item_text(item: Any) -> list[str]:
    texts: list[str] = []
    if isinstance(item, str):
        texts.append(item)
    elif isinstance(item, dict):
        if "text" in item and isinstance(item["text"], str):
            texts.append(item["text"])
        if item.get("type") == "tool_result":
            tr_content = item.get("content")
            if isinstance(tr_content, str):
                texts.append(tr_content)
            elif isinstance(tr_content, list):
                for sub in tr_content:
                    texts.extend(_extract_item_text(sub))
            elif isinstance(tr_content, dict):
                texts.extend(_extract_item_text(tr_content))
    return texts


def _extract_single_message_user_text(msg: dict[str, Any]) -> list[str]:
    content = msg.get("content")
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        out: list[str] = []
        for item in content:
            extracted = _extract_item_text(item)
            if extracted:
                out.extend(extracted)
            elif isinstance(item, str):
                out.append(item)
        return out
    if isinstance(content, dict):
        return _extract_item_text(content)
    if content is not None:
        return [json.dumps(content, default=str)]
    return []


def _extract_openai_user_content(messages: Any, prompt: Any, max_recent_turns: int) -> str:
    user_texts: list[str] = []
    if isinstance(messages, list):
        user_msgs = [m for m in messages if isinstance(m, dict) and m.get("role") == "user"]
        recent = user_msgs[-max_recent_turns:] if max_recent_turns > 0 else user_msgs
        for msg in recent:
            user_texts.extend(_extract_single_message_user_text(msg))
    if not user_texts and isinstance(prompt, str) and prompt:
        user_texts.append(prompt)
    return " ".join(user_texts)


def _extract_messages_system_texts(messages: list[Any]) -> list[str]:
    texts: list[str] = []
    for msg in messages:
        if isinstance(msg, dict) and msg.get("role") == "system":
            content = msg.get("content")
            if isinstance(content, str):
                texts.append(content)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, str):
                        texts.append(item)
                    elif isinstance(item, dict) and isinstance(item.get("text"), str):
                        texts.append(item["text"])
    return texts


def _extract_top_system_texts(system_val: Any) -> list[str]:
    texts: list[str] = []
    if isinstance(system_val, str):
        texts.append(system_val)
    elif isinstance(system_val, list):
        for item in system_val:
            if isinstance(item, str):
                texts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                texts.append(item["text"])
    return texts


def _extract_openai_system_prompt(payload: dict[str, Any]) -> str:
    messages = payload.get("messages")
    system_texts: list[str] = []
    if isinstance(messages, list):
        system_texts = _extract_messages_system_texts(messages)
    if not system_texts and "system" in payload:
        system_texts = _extract_top_system_texts(payload.get("system"))
    return " ".join(system_texts).strip()


def _parse_openai_delta_len(delta: dict[str, Any]) -> int:
    acc_len = 0
    txt = delta.get("content")
    if isinstance(txt, str) and txt:
        acc_len += len(txt)
    tool_calls = delta.get("tool_calls")
    if isinstance(tool_calls, list):
        for tc in tool_calls:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function")
            if isinstance(fn, dict):
                fn_name = fn.get("name")
                if isinstance(fn_name, str) and fn_name:
                    acc_len += len(fn_name)
                args = fn.get("arguments")
                if isinstance(args, str) and args:
                    acc_len += len(args)
    return acc_len


class OpenAIProvider(ProviderFormat):
    """Wire format implementation for OpenAI Chat Completions API."""

    def clean(
        self,
        cleaner: JSONContextCleaner,
        payload: dict[str, Any],
        seen_content_hashes: dict[str, tuple[int, str]],
        stats: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """Cleans OpenAI request payloads (tool deduplication and turn summarization)."""
        messages = payload.get("messages", [])
        if not isinstance(messages, list):
            return payload

        enable_dedup = getattr(cleaner, "enable_deduplication", True)
        cleaned_messages = deduplicate_openai_messages(messages, enable_dedup, seen_content_hashes, stats=stats)

        max_turns = getattr(cleaner, "max_turns", 40)
        recent_turns_to_keep = getattr(cleaner, "recent_turns_to_keep", 10)
        if len(cleaned_messages) > max_turns:
            cleaned_messages = summarize_openai_history(cleaned_messages, recent_turns_to_keep, stats=stats)

        payload["messages"] = cleaned_messages
        return payload

    def extract_sse_content(self, resp_text: str) -> str:
        """Extracts text and tool call invocations from OpenAI SSE stream lines."""
        accumulated: list[str] = []
        in_tool = False
        for chunk in _iter_sse_chunks(resp_text):
            choices = chunk.get("choices")
            if isinstance(choices, list):
                for choice in choices:
                    if isinstance(choice, dict):
                        in_tool = _process_choice_delta(choice, in_tool, accumulated)
        if in_tool:
            accumulated.append(")")
        return "".join(accumulated)

    def token_counts_from_sse(self, resp_text: str, req_data: dict[str, Any]) -> TokenCounts:
        """Extracts token counts from OpenAI SSE stream chunks or falls back to char counts."""
        inp_tok: int | None = None
        out_tok: int | None = None
        cached_tok: int | None = None
        reasoning_tok: int | None = None
        acc_len = 0

        for chunk in _iter_sse_chunks(resp_text):
            usage = chunk.get("usage")
            if isinstance(usage, dict):
                i, o, c, r = _parse_openai_usage(usage)
                inp_tok, out_tok, cached_tok, reasoning_tok = i, o, c, r
            choices = chunk.get("choices")
            if isinstance(choices, list):
                for ch in choices:
                    if isinstance(ch, dict) and isinstance(ch.get("delta"), dict):
                        acc_len += _parse_openai_delta_len(ch["delta"])

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
        """Extracts token counts from OpenAI dictionary response."""
        input_tokens = 0
        output_tokens = 0
        cache_read = 0
        reasoning = 0
        parsed = False

        usage = resp_data.get("usage") if isinstance(resp_data, dict) else None
        if isinstance(usage, dict) and "prompt_tokens" in usage and "completion_tokens" in usage:
            input_tokens, output_tokens, cache_read, reasoning = _parse_openai_usage(usage)
            parsed = True

        if not parsed:
            tokens_logger = logging.getLogger("holon_coherence.parsers.tokens")
            tokens_logger.debug(
                "Provider usage dictionary missing or invalid for %s; estimating token counts from payload characters",
                "openai",
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
        """Extracts (user_content, system_prompt) for OpenAI requests."""
        if not isinstance(payload, dict):
            return str(payload) if payload else "", ""
        user_content = _extract_openai_user_content(payload.get("messages"), payload.get("prompt"), max_recent_turns)
        system_prompt = _extract_openai_system_prompt(payload)
        return user_content, system_prompt
