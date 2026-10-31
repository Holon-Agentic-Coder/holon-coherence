"""Anthropic wire format implementation."""

from __future__ import annotations

import copy
import hashlib
import json
import logging
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from holon_coherence.parsers.tokens import TokenCounts, estimate_chars, safe_int
from holon_coherence.providers.base import ProviderFormat

if TYPE_CHECKING:
    from holon_coherence.payload_cleaner import JSONContextCleaner

logger = logging.getLogger(__name__)


def _hash_content(content: str | list[Any]) -> str | None:
    if isinstance(content, str) and len(content) > 100:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
    if isinstance(content, list):
        serialized = json.dumps(content, sort_keys=True)
        if len(serialized) > 100:
            return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return None


def _dedup_tool_result_item(
    item: dict[str, Any],
    turn_idx: int,
    is_older_turn: bool,
    seen_content_hashes: dict[str, tuple[int, str]],
    stats: dict[str, int] | None,
) -> dict[str, Any]:
    item_copy = copy.deepcopy(item)
    tool_out = item_copy.get("content", "")
    resource_name = item_copy.get("tool_use_id", f"tool_result_{turn_idx}")
    content_hash = _hash_content(tool_out)
    if not content_hash:
        return item_copy

    if content_hash in seen_content_hashes and is_older_turn:
        prev_turn, prev_res = seen_content_hashes[content_hash]
        item_copy["content"] = f"[Tool output omitted: identical output matches Turn {prev_turn} ({prev_res})]"
        if stats is not None:
            stats["tool_outputs_omitted"] += 1
    else:
        seen_content_hashes[content_hash] = (turn_idx, resource_name)
    return item_copy


def _dedup_text_item(
    item: dict[str, Any],
    turn_idx: int,
    is_older_turn: bool,
    seen_content_hashes: dict[str, tuple[int, str]],
    stats: dict[str, int] | None,
) -> dict[str, Any]:
    item_copy = copy.deepcopy(item)
    text_out = item_copy.get("text", "")
    if isinstance(text_out, str) and len(text_out) > 100:
        content_hash = hashlib.sha256(text_out.encode("utf-8")).hexdigest()
        if content_hash in seen_content_hashes and is_older_turn:
            prev_turn, prev_res = seen_content_hashes[content_hash]
            item_copy["text"] = f"[Tool output omitted: identical output matches Turn {prev_turn} ({prev_res})]"
            if stats is not None:
                stats["tool_outputs_omitted"] += 1
        else:
            seen_content_hashes[content_hash] = (turn_idx, f"turn_{turn_idx}")
    return item_copy


def _dedup_content_block(
    item: Any,
    turn_idx: int,
    is_older_turn: bool,
    seen_content_hashes: dict[str, tuple[int, str]],
    stats: dict[str, int] | None,
) -> Any:
    if not isinstance(item, dict):
        return item
    item_type = item.get("type")
    if item_type == "tool_result":
        return _dedup_tool_result_item(item, turn_idx, is_older_turn, seen_content_hashes, stats)
    if item_type == "text":
        return _dedup_text_item(item, turn_idx, is_older_turn, seen_content_hashes, stats)
    return copy.deepcopy(item)


def _dedup_single_message(
    msg: dict[str, Any],
    turn_idx: int,
    is_older_turn: bool,
    seen_content_hashes: dict[str, tuple[int, str]],
    stats: dict[str, int] | None,
) -> dict[str, Any]:
    msg_copy = copy.deepcopy(msg)
    content = msg_copy.get("content")
    if isinstance(content, list):
        msg_copy["content"] = [
            _dedup_content_block(block, turn_idx, is_older_turn, seen_content_hashes, stats) for block in content
        ]
    elif isinstance(content, str) and len(content) > 200:
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if content_hash in seen_content_hashes and is_older_turn:
            prev_turn, prev_res = seen_content_hashes[content_hash]
            msg_copy["content"] = f"[Tool output omitted: identical output matches Turn {prev_turn} ({prev_res})]"
            if stats is not None:
                stats["tool_outputs_omitted"] += 1
        else:
            seen_content_hashes[content_hash] = (turn_idx, f"turn_{turn_idx}")
    return msg_copy


def deduplicate_anthropic_tool_outputs(
    messages: list[dict[str, Any]],
    seen_content_hashes: dict[str, tuple[int, str]],
    stats: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Deduplicates repeated tool outputs across previous turns in Anthropic messages."""
    cleaned_messages: list[dict[str, Any]] = []
    turn_count = len(messages)
    for turn_idx, msg in enumerate(messages):
        if not isinstance(msg, dict):
            cleaned_messages.append(msg)
            continue
        is_older_turn = turn_idx < (turn_count - 2)
        cleaned_messages.append(_dedup_single_message(msg, turn_idx, is_older_turn, seen_content_hashes, stats))
    return cleaned_messages


def _is_clean_anthropic_user_message(msg: dict[str, Any]) -> bool:
    if not isinstance(msg, dict) or msg.get("role") != "user":
        return False
    content = msg.get("content")
    if isinstance(content, list):
        return not any(isinstance(item, dict) and item.get("type") == "tool_result" for item in content)
    return True


def _find_anthropic_suffix_idx(messages: list[dict[str, Any]], recent_turns_to_keep: int) -> int | None:
    target_idx = len(messages) - recent_turns_to_keep
    for i in range(target_idx, 0, -1):
        if _is_clean_anthropic_user_message(messages[i]):
            return i
    for i in range(target_idx + 1, len(messages)):
        if _is_clean_anthropic_user_message(messages[i]):
            return i
    return None


def summarize_anthropic_history(
    messages: list[dict[str, Any]],
    recent_turns_to_keep: int,
    stats: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Summarizes intermediate history turns in Anthropic message sequence."""
    suffix_idx = _find_anthropic_suffix_idx(messages, recent_turns_to_keep)
    if suffix_idx is None or suffix_idx <= 1:
        return messages

    prefix = messages[:1]
    suffix = messages[suffix_idx:]
    middle = messages[1:suffix_idx]

    if stats is not None:
        stats["turns_summarized"] += len(middle)

    summary_text = f"[Summary of omitted {len(middle)} intermediate conversation turns]"
    summary_msg = {"role": "assistant", "content": summary_text}
    return [*prefix, summary_msg, *suffix]


def _to_content_blocks(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, list):
        return copy.deepcopy(content)
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return []


def _merge_two_messages(prev: dict[str, Any], curr: dict[str, Any]) -> None:
    if "content" in prev or "content" in curr:
        prev_content = prev.get("content")
        curr_content = curr.get("content")
        if isinstance(prev_content, list) or isinstance(curr_content, list):
            prev["content"] = _to_content_blocks(prev_content) + _to_content_blocks(curr_content)
        else:
            prev["content"] = f"{prev_content}\n\n{curr_content}"

    if "parts" in prev or "parts" in curr:
        prev_parts = prev.get("parts", [])
        curr_parts = curr.get("parts", [])
        if isinstance(prev_parts, list) and isinstance(curr_parts, list):
            prev["parts"] = copy.deepcopy(prev_parts) + copy.deepcopy(curr_parts)


def merge_consecutive_roles(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merges adjacent messages sharing identical role names."""
    if not messages:
        return []
    merged: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            merged.append(copy.deepcopy(msg))
            continue
        if not merged or not isinstance(merged[-1], dict) or merged[-1].get("role") != msg.get("role"):
            merged.append(copy.deepcopy(msg))
        else:
            _merge_two_messages(merged[-1], msg)
    return merged


def _count_system_cache_controls(system: Any) -> int:
    if isinstance(system, list):
        return sum(1 for b in system if isinstance(b, dict) and "cache_control" in b)
    if isinstance(system, dict) and "cache_control" in system:
        return 1
    return 0


def _count_tools_cache_controls(tools: Any) -> int:
    if isinstance(tools, list):
        return sum(1 for t in tools if isinstance(t, dict) and "cache_control" in t)
    return 0


def _count_message_cache_controls(messages: Any) -> int:
    if not isinstance(messages, list):
        return 0
    count = 0
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        if "cache_control" in msg:
            count += 1
        content = msg.get("content")
        if isinstance(content, list):
            count += sum(1 for b in content if isinstance(b, dict) and "cache_control" in b)
        elif isinstance(content, dict) and "cache_control" in content:
            count += 1
    return count


def count_existing_cache_controls(payload: dict[str, Any]) -> int:
    """Counts existing cache_control markers in Anthropic request payload."""
    return (
        _count_system_cache_controls(payload.get("system"))
        + _count_tools_cache_controls(payload.get("tools"))
        + _count_message_cache_controls(payload.get("messages"))
    )


def _inject_system_cache(payload: dict[str, Any]) -> bool:
    system = payload.get("system")
    if isinstance(system, list) and system:
        last_sys = system[-1]
        if isinstance(last_sys, dict) and "cache_control" not in last_sys:
            last_sys["cache_control"] = {"type": "ephemeral"}
            return True
    elif isinstance(system, str):
        payload["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        return True
    return False


def _inject_tools_cache(payload: dict[str, Any]) -> bool:
    tools = payload.get("tools")
    if isinstance(tools, list) and tools:
        last_tool = tools[-1]
        if isinstance(last_tool, dict) and "cache_control" not in last_tool:
            last_tool["cache_control"] = {"type": "ephemeral"}
            return True
    return False


def _inject_messages_cache(payload: dict[str, Any]) -> bool:
    messages = payload.get("messages", [])
    if isinstance(messages, list) and len(messages) >= 2:
        target_msg = messages[-2]
        if isinstance(target_msg, dict):
            content = target_msg.get("content")
            if isinstance(content, list) and content:
                last_block = content[-1]
                if isinstance(last_block, dict) and "cache_control" not in last_block:
                    last_block["cache_control"] = {"type": "ephemeral"}
                    return True
            elif isinstance(content, str):
                target_msg["content"] = [{"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}]
                return True
    return False


def inject_anthropic_cache_control(payload: dict[str, Any], stats: dict[str, int] | None = None) -> dict[str, Any]:
    """Injects ephemeral prompt cache controls into Anthropic payload within budget."""
    existing_count = count_existing_cache_controls(payload)
    budget = 4 - existing_count
    if budget <= 0:
        return payload

    injected = 0
    if _inject_system_cache(payload):
        budget -= 1
        injected += 1

    if budget > 0 and _inject_tools_cache(payload):
        budget -= 1
        injected += 1

    if budget > 0 and _inject_messages_cache(payload):
        budget -= 1
        injected += 1

    if stats is not None:
        stats["cache_control_injected"] += injected
    return payload


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


def _parse_anthropic_sse_content_chunk(chunk: dict[str, Any], in_tool: bool, accumulated: list[str]) -> bool:
    content_block = chunk.get("content_block") or {}
    if content_block.get("type") == "tool_use":
        in_tool = True
        name = content_block.get("name", "")
        if name:
            accumulated.append(f"{name}(")

    delta = chunk.get("delta")
    if isinstance(delta, dict):
        for key in ("text", "thinking", "partial_json"):
            val = delta.get(key)
            if val:
                accumulated.append(val)

    if in_tool and chunk.get("type") == "content_block_stop":
        accumulated.append(")")
        return False
    return in_tool


def _parse_anthropic_message_start(chunk: dict[str, Any]) -> tuple[int | None, int | None, int | None]:
    message = chunk.get("message")
    if not isinstance(message, dict):
        return None, None, None
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None, None, None

    cache_read = safe_int(usage.get("cache_read_input_tokens"))
    cache_creation = safe_int(usage.get("cache_creation_input_tokens"))
    input_tokens = safe_int(usage.get("input_tokens")) + cache_read + cache_creation
    return input_tokens, cache_read, cache_creation


def _parse_anthropic_message_delta(chunk: dict[str, Any]) -> tuple[int | None, int | None]:
    usage = chunk.get("usage")
    if not isinstance(usage, dict):
        return None, None
    out_tok = safe_int(usage.get("output_tokens")) if "output_tokens" in usage else None
    reasoning = safe_int(usage.get("thinking_tokens")) if "thinking_tokens" in usage else None
    return out_tok, reasoning


def _parse_anthropic_block_delta(chunk: dict[str, Any]) -> tuple[int, int]:
    delta = chunk.get("delta")
    if not isinstance(delta, dict):
        return 0, 0
    content_len = 0
    thinking_len = 0
    for key in ("text", "partial_json"):
        val = delta.get(key)
        if isinstance(val, str) and val:
            content_len += len(val)
    thinking = delta.get("thinking")
    if isinstance(thinking, str) and thinking:
        content_len += len(thinking)
        thinking_len += len(thinking)
    return content_len, thinking_len


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


def _extract_anthropic_user_content(messages: Any, prompt: Any, max_recent_turns: int) -> str:
    user_texts: list[str] = []
    if isinstance(messages, list):
        user_msgs = [m for m in messages if isinstance(m, dict) and m.get("role") == "user"]
        recent = user_msgs[-max_recent_turns:] if max_recent_turns > 0 else user_msgs
        for msg in recent:
            user_texts.extend(_extract_single_message_user_text(msg))
    if not user_texts and isinstance(prompt, str) and prompt:
        user_texts.append(prompt)
    return " ".join(user_texts)


def _extract_anthropic_system_prompt(system_val: Any) -> str:
    if system_val is None:
        return ""
    if isinstance(system_val, str):
        return system_val.strip()
    texts: list[str] = []
    if isinstance(system_val, list):
        for item in system_val:
            if isinstance(item, str):
                texts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                texts.append(item["text"])
    elif isinstance(system_val, dict) and isinstance(system_val.get("text"), str):
        texts.append(system_val["text"])
    return " ".join(texts).strip()


class AnthropicProvider(ProviderFormat):
    """Wire format implementation for Anthropic Messages API."""

    def clean(
        self,
        cleaner: JSONContextCleaner,
        payload: dict[str, Any],
        seen_content_hashes: dict[str, tuple[int, str]],
        stats: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """Cleans Anthropic request payloads (tool dedup, summarization, prompt cache breakpoints)."""
        messages = payload.get("messages", [])
        if not isinstance(messages, list):
            return payload

        if getattr(cleaner, "enable_deduplication", True):
            messages = deduplicate_anthropic_tool_outputs(messages, seen_content_hashes, stats=stats)

        max_turns = getattr(cleaner, "max_turns", 40)
        recent_turns_to_keep = getattr(cleaner, "recent_turns_to_keep", 10)
        if len(messages) > max_turns:
            messages = summarize_anthropic_history(messages, recent_turns_to_keep, stats=stats)
            messages = merge_consecutive_roles(messages)

        payload["messages"] = messages

        if getattr(cleaner, "enable_prompt_caching", True):
            payload = inject_anthropic_cache_control(payload, stats=stats)

        return payload

    def extract_sse_content(self, resp_text: str) -> str:
        """Extracts text and tool use invocations from Anthropic SSE stream lines."""
        accumulated: list[str] = []
        in_tool = False
        for chunk in _iter_sse_chunks(resp_text):
            in_tool = _parse_anthropic_sse_content_chunk(chunk, in_tool, accumulated)
        if in_tool:
            accumulated.append(")")
        return "".join(accumulated)

    def token_counts_from_sse(self, resp_text: str, req_data: dict[str, Any]) -> TokenCounts:
        """Extracts token counts and cache stats from Anthropic SSE stream."""
        inp_tok: int | None = None
        out_tok: int | None = None
        cache_read: int | None = None
        cache_creation: int | None = None
        reasoning: int | None = None
        acc_len = 0
        acc_thinking = 0

        for chunk in _iter_sse_chunks(resp_text):
            event_type = chunk.get("type")
            if event_type == "message_start":
                i, r, c = _parse_anthropic_message_start(chunk)
                if i is not None:
                    inp_tok, cache_read, cache_creation = i, r, c
            elif event_type == "message_delta":
                o, rea = _parse_anthropic_message_delta(chunk)
                if o is not None:
                    out_tok = o
                if rea is not None:
                    reasoning = rea
            elif event_type == "content_block_delta":
                clen, tlen = _parse_anthropic_block_delta(chunk)
                acc_len += clen
                acc_thinking += tlen

        input_tokens = (
            inp_tok
            if inp_tok is not None
            else max(1, estimate_chars(req_data) // 4)
            if estimate_chars(req_data) > 0
            else 0
        )
        output_tokens = out_tok if out_tok is not None else max(1, acc_len // 4) if acc_len > 0 else 0
        reasoning_tokens = reasoning or (max(1, acc_thinking // 4) if acc_thinking > 0 else 0)

        return TokenCounts(
            input_tokens,
            output_tokens,
            cache_read or 0,
            cache_creation_tokens=cache_creation or 0,
            reasoning_tokens=reasoning_tokens,
        )

    def token_counts_from_dict(self, req_data: dict[str, Any], resp_data: dict[str, Any]) -> TokenCounts:
        """Extracts token counts from Anthropic dictionary response."""
        input_tokens = 0
        output_tokens = 0
        cache_read = 0
        cache_creation = 0
        reasoning = 0
        parsed = False

        usage = resp_data.get("usage") if isinstance(resp_data, dict) else None
        if isinstance(usage, dict) and "input_tokens" in usage and "output_tokens" in usage:
            cache_read = safe_int(usage.get("cache_read_input_tokens"))
            cache_creation = safe_int(usage.get("cache_creation_input_tokens"))
            input_tokens = safe_int(usage.get("input_tokens")) + cache_read + cache_creation
            output_tokens = safe_int(usage.get("output_tokens"))
            reasoning = safe_int(usage.get("reasoning_tokens")) or safe_int(usage.get("thinking_tokens"))
            parsed = True

        if not parsed:
            tokens_logger = logging.getLogger("holon_coherence.parsers.tokens")
            tokens_logger.debug(
                "Provider usage dictionary missing or invalid for %s; estimating token counts from payload characters",
                "anthropic",
            )
            in_chars = estimate_chars(req_data)
            out_chars = estimate_chars(resp_data)
            input_tokens = max(1, in_chars // 4) if in_chars > 0 else 0
            output_tokens = max(1, out_chars // 4) if out_chars > 0 else 0

        return TokenCounts(
            input_tokens,
            output_tokens,
            cache_read,
            cache_creation_tokens=cache_creation,
            reasoning_tokens=reasoning,
        )

    def extract_cache_key_parts(self, payload: dict[str, Any], max_recent_turns: int = 2) -> tuple[str, str]:
        """Extracts (user_content, system_prompt) for Anthropic requests."""
        if not isinstance(payload, dict):
            return str(payload) if payload else "", ""
        user_content = _extract_anthropic_user_content(payload.get("messages"), payload.get("prompt"), max_recent_turns)
        system_prompt = _extract_anthropic_system_prompt(payload.get("system"))
        return user_content, system_prompt
