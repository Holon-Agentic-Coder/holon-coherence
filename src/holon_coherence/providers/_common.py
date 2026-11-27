from __future__ import annotations

import copy
import json
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlparse

DEFAULT_MAX_ESTIMATE_DEPTH = 10
CHARS_PER_ESTIMATED_TOKEN = 4
SSE_DATA_PREFIX = "data:"
SSE_DONE_SENTINEL = "[DONE]"
PAYLOAD_TEXT_CONTAINER_KEYS: tuple[str, ...] = (
    "messages",
    "message",
    "prompt",
    "contents",
    "parts",
    "choices",
    "candidates",
    "content",
    "text",
)


def estimate_tokens_from_chars(char_count: int) -> int:
    return max(1, char_count // CHARS_PER_ESTIMATED_TOKEN) if char_count > 0 else 0


def safe_int(val: Any, default: int = 0) -> int:
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def estimate_chars(data: Any, max_depth: int = DEFAULT_MAX_ESTIMATE_DEPTH) -> int:
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
        for key in PAYLOAD_TEXT_CONTAINER_KEYS:
            if key in data:
                total += estimate_chars(data[key], max_depth - 1)
                found_target = True
        if found_target:
            return total
        return sum(estimate_chars(v, max_depth - 1) for v in data.values())
    return 0


class TokenCounts(tuple):
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


def iter_sse_chunks(resp_text: str) -> Iterator[dict[str, Any]]:
    for line in resp_text.splitlines():
        line = line.strip()
        if not line.startswith(SSE_DATA_PREFIX):
            continue
        json_str = line[len(SSE_DATA_PREFIX) :].strip()
        if not json_str or json_str == SSE_DONE_SENTINEL:
            continue
        try:
            chunk = json.loads(json_str)
            if isinstance(chunk, dict):
                yield chunk
        except (json.JSONDecodeError, TypeError, ValueError):
            continue


def extract_item_text(item: Any) -> list[str]:
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
                    texts.extend(extract_item_text(sub))
            elif isinstance(tr_content, dict):
                texts.extend(extract_item_text(tr_content))
    return texts


def extract_single_message_user_text(msg: dict[str, Any]) -> list[str]:
    content = msg.get("content")
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        out: list[str] = []
        for item in content:
            extracted = extract_item_text(item)
            if extracted:
                out.extend(extracted)
            elif isinstance(item, str):
                out.append(item)
        return out
    if isinstance(content, dict):
        return extract_item_text(content)
    if content is not None:
        return [json.dumps(content, default=str)]
    return []


def extract_user_content(messages: Any, prompt: Any, max_recent_turns: int) -> str:
    user_texts: list[str] = []
    if isinstance(messages, list):
        user_msgs = [m for m in messages if isinstance(m, dict) and m.get("role") == "user"]
        recent = user_msgs[-max_recent_turns:] if max_recent_turns > 0 else user_msgs
        for msg in recent:
            user_texts.extend(extract_single_message_user_text(msg))
    if not user_texts and isinstance(prompt, str) and prompt:
        user_texts.append(prompt)
    return " ".join(user_texts)


def parse_hostname(url_or_path: str) -> tuple[str, str]:
    url_lower = url_or_path.lower()
    target = url_lower if "://" in url_lower else f"https://{url_lower}"
    parsed = urlparse(target)
    hostname = parsed.hostname or url_lower
    return url_lower, hostname
