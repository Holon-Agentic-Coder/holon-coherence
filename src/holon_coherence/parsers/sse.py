"""Server-Sent Events (SSE) stream parsing and reassembly routines."""

from __future__ import annotations

import json
import logging
from typing import Any

from holon_coherence.parsers.tokens import TokenCounts, estimate_chars, safe_int

logger = logging.getLogger(__name__)


def find_nested_key(data: Any, target_keys: tuple[str, ...] | str, max_depth: int = 10) -> Any:
    """Recursively searches nested dicts/lists to find the first occurrence of any key in target_keys.

    Evaluates target keys on the immediate node before recursively traversing child dictionaries
    or lists in depth-first order.
    """
    if not isinstance(data, (dict, list)):
        return None
    if max_depth <= 0 or not data:
        return None
    if isinstance(target_keys, str):
        target_keys = (target_keys,)

    if isinstance(data, dict):
        for key in target_keys:
            if key in data and data[key] is not None:
                return data[key]
        for val in data.values():
            if isinstance(val, (dict, list)):
                res = find_nested_key(val, target_keys, max_depth - 1)
                if res is not None:
                    return res
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, (dict, list)):
                res = find_nested_key(item, target_keys, max_depth - 1)
                if res is not None:
                    return res
    return None


def extract_sse_content(resp_text: str, provider: str) -> str:
    """Extracts aggregated completion text from SSE lines."""
    accumulated_content: list[str] = []
    lines = resp_text.splitlines()
    in_anthropic_tool = False
    in_openai_tool = False
    for line in lines:
        line = line.strip()
        if not line.startswith("data:"):
            continue
        json_str = line[5:].strip()
        if not json_str or json_str == "[DONE]":
            continue
        try:
            chunk = json.loads(json_str)
        except Exception:
            continue
        if not isinstance(chunk, dict):
            continue

        if provider == "anthropic":
            content_block = chunk.get("content_block") or {}
            if content_block.get("type") == "tool_use":
                in_anthropic_tool = True
                name = content_block.get("name", "")
                if name:
                    accumulated_content.append(f"{name}(")

            delta = find_nested_key(chunk, ("delta",)) or {}
            text = delta.get("text", "")
            if text:
                accumulated_content.append(text)
            thinking = delta.get("thinking", "")
            if thinking:
                accumulated_content.append(thinking)
            partial_json = delta.get("partial_json", "")
            if partial_json:
                accumulated_content.append(partial_json)

            if in_anthropic_tool and chunk.get("type") == "content_block_stop":
                accumulated_content.append(")")
                in_anthropic_tool = False
        elif provider == "openai":
            choices = find_nested_key(chunk, ("choices",))
            if isinstance(choices, list):
                for choice in choices:
                    if isinstance(choice, dict):
                        delta = choice.get("delta")
                        if isinstance(delta, dict):
                            content = delta.get("content")
                            if isinstance(content, str):
                                if in_openai_tool:
                                    accumulated_content.append(")")
                                    in_openai_tool = False
                                accumulated_content.append(content)
                            tool_calls = delta.get("tool_calls")
                            if isinstance(tool_calls, list):
                                for tc in tool_calls:
                                    fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                                    fn_name = fn.get("name", "")
                                    args = fn.get("arguments", "")
                                    if fn_name:
                                        if in_openai_tool:
                                            accumulated_content.append(")")
                                        accumulated_content.append(f"{fn_name}(")
                                        in_openai_tool = True
                                    if args:
                                        accumulated_content.append(args)
                        if choice.get("finish_reason") in ("tool_calls", "stop") and in_openai_tool:
                            accumulated_content.append(")")
                            in_openai_tool = False
        elif provider == "gemini":
            candidates = find_nested_key(chunk, ("candidates",))
            if isinstance(candidates, list):
                for candidate in candidates:
                    if isinstance(candidate, dict):
                        content = candidate.get("content")
                        if isinstance(content, dict):
                            parts = content.get("parts")
                            if isinstance(parts, list):
                                for part in parts:
                                    if isinstance(part, dict):
                                        if "text" in part:
                                            accumulated_content.append(part["text"])
                                        func_call = part.get("functionCall")
                                        if isinstance(func_call, dict):
                                            accumulated_content.append(json.dumps(func_call))

    if in_openai_tool:
        accumulated_content.append(")")
    if in_anthropic_tool:
        accumulated_content.append(")")

    return "".join(accumulated_content)


def extract_sse_token_counts(resp_text: str, req_data: dict[str, Any], provider: str) -> TokenCounts:
    """Extracts (input_tokens, output_tokens, cache_read_tokens) from SSE stream text.

    Args:
        resp_text: Full raw SSE text accumulated from stream chunks.
        req_data: Original request payload dictionary used for input token fallback estimation.
        provider: Detected model provider ("anthropic", "openai", "gemini").

    Returns:
        TokenCounts: A 3-tuple compatible object containing (input_tokens, output_tokens, cache_read_tokens).

    Note:
        When explicit usage metadata is absent from the SSE stream chunks, fallback token estimation
        derives counts from accumulated character counts using an integer division heuristic of
        1 token per 4 characters (i.e. chars // 4).
    """
    input_tokens = 0
    output_tokens = 0
    cache_read_tokens = 0

    # Track parsed metrics
    input_tokens_parsed = None
    output_tokens_parsed = None
    cache_read_tokens_parsed = None
    cache_creation_tokens_parsed = None
    reasoning_tokens_parsed = None
    accumulated_content_len = 0
    accumulated_thinking_len = 0

    # We split the stream by lines.
    lines = resp_text.splitlines()
    for line in lines:
        line = line.strip()
        if not line or not line.startswith("data:"):
            continue

        # Strip "data:" prefix
        json_str = line[5:].strip()

        if not json_str or json_str == "[DONE]":
            continue

        try:
            chunk = json.loads(json_str)
        except Exception:
            continue

        if not isinstance(chunk, dict):
            continue

        if provider == "anthropic":
            # Anthropic SSE format
            event_type = find_nested_key(chunk, ("type",))
            if event_type == "message_start":
                message = find_nested_key(chunk, ("message",)) or {}
                usage = find_nested_key(message, ("usage",))
                if isinstance(usage, dict):
                    if "cache_read_input_tokens" in usage:
                        cache_read_tokens_parsed = safe_int(usage.get("cache_read_input_tokens"))
                    if "cache_creation_input_tokens" in usage:
                        cache_creation_tokens_parsed = safe_int(usage.get("cache_creation_input_tokens"))
                    if "input_tokens" in usage:
                        input_tokens_parsed = (
                            safe_int(usage.get("input_tokens"))
                            + safe_int(usage.get("cache_read_input_tokens"))
                            + safe_int(usage.get("cache_creation_input_tokens"))
                        )
            elif event_type == "message_delta":
                usage = find_nested_key(chunk, ("usage",))
                if isinstance(usage, dict):
                    if "output_tokens" in usage:
                        output_tokens_parsed = safe_int(usage.get("output_tokens"))
                    if "thinking_tokens" in usage:
                        reasoning_tokens_parsed = safe_int(usage.get("thinking_tokens"))
            elif event_type == "content_block_delta":
                delta = find_nested_key(chunk, ("delta",)) or {}
                text = delta.get("text", "")
                if text:
                    accumulated_content_len += len(text)
                partial_json = delta.get("partial_json", "")
                if partial_json:
                    accumulated_content_len += len(partial_json)
                thinking = delta.get("thinking", "")
                if thinking:
                    accumulated_content_len += len(thinking)
                    accumulated_thinking_len += len(thinking)

        elif provider == "openai":
            # OpenAI SSE format
            usage = find_nested_key(chunk, ("usage",))
            if usage and isinstance(usage, dict):
                if "prompt_tokens" in usage:
                    input_tokens_parsed = safe_int(usage.get("prompt_tokens"))
                if "completion_tokens" in usage:
                    output_tokens_parsed = safe_int(usage.get("completion_tokens"))
                prompt_tokens_details = usage.get("prompt_tokens_details")
                if isinstance(prompt_tokens_details, dict) and "cached_tokens" in prompt_tokens_details:
                    cache_read_tokens_parsed = safe_int(prompt_tokens_details.get("cached_tokens"))
                elif "cached_tokens" in usage:
                    cache_read_tokens_parsed = safe_int(usage.get("cached_tokens"))
                comp_details = usage.get("completion_tokens_details")
                if isinstance(comp_details, dict) and "reasoning_tokens" in comp_details:
                    reasoning_tokens_parsed = safe_int(comp_details.get("reasoning_tokens"))

            choices = find_nested_key(chunk, ("choices",))
            if choices and isinstance(choices, list):
                for choice in choices:
                    if isinstance(choice, dict):
                        delta = choice.get("delta")
                        if isinstance(delta, dict):
                            content = delta.get("content", "")
                            if isinstance(content, str) and content:
                                accumulated_content_len += len(content)
                            tool_calls = delta.get("tool_calls")
                            if isinstance(tool_calls, list):
                                for tc in tool_calls:
                                    fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                                    fn_name = fn.get("name", "")
                                    if isinstance(fn_name, str) and fn_name:
                                        accumulated_content_len += len(fn_name)
                                    args = fn.get("arguments", "")
                                    if isinstance(args, str) and args:
                                        accumulated_content_len += len(args)

        elif provider == "gemini":
            # Gemini / Cloud Code PA format
            usage = find_nested_key(chunk, ("usageMetadata", "usage"))
            if usage and isinstance(usage, dict):
                if "promptTokenCount" in usage:
                    input_tokens_parsed = safe_int(usage.get("promptTokenCount"))
                if "candidatesTokenCount" in usage:
                    output_tokens_parsed = safe_int(usage.get("candidatesTokenCount"))
                if "cachedContentTokenCount" in usage:
                    cache_read_tokens_parsed = safe_int(usage.get("cachedContentTokenCount"))
                if "reasoningTokenCount" in usage:
                    reasoning_tokens_parsed = safe_int(usage.get("reasoningTokenCount"))

            candidates = find_nested_key(chunk, ("candidates", "choices", "contents"))
            if candidates and isinstance(candidates, list):
                for candidate in candidates:
                    if isinstance(candidate, dict):
                        content = candidate.get("content")
                        if isinstance(content, dict):
                            parts = content.get("parts")
                            if isinstance(parts, list):
                                for part in parts:
                                    if isinstance(part, dict):
                                        text = part.get("text", "")
                                        if isinstance(text, str) and text:
                                            accumulated_content_len += len(text)
                                        func_call = part.get("functionCall")
                                        if isinstance(func_call, dict):
                                            fn_name = func_call.get("name", "")
                                            if isinstance(fn_name, str) and fn_name:
                                                accumulated_content_len += len(fn_name)
                                            fn_args = func_call.get("args")
                                            if isinstance(fn_args, dict):
                                                accumulated_content_len += len(json.dumps(fn_args))
                                            elif isinstance(fn_args, str) and fn_args:
                                                accumulated_content_len += len(fn_args)
                                    elif isinstance(part, str) and part:
                                        accumulated_content_len += len(part)
                        elif isinstance(content, str) and content:
                            accumulated_content_len += len(content)
                    elif isinstance(candidate, str) and candidate:
                        accumulated_content_len += len(candidate)

    # Fallback/estimate calculations
    if input_tokens_parsed is not None:
        input_tokens = input_tokens_parsed
    else:
        input_chars = estimate_chars(req_data)
        input_tokens = max(1, input_chars // 4) if input_chars > 0 else 0

    if output_tokens_parsed is not None:
        output_tokens = output_tokens_parsed
    else:
        output_tokens = max(1, accumulated_content_len // 4) if accumulated_content_len > 0 else 0

    if cache_read_tokens_parsed is not None:
        cache_read_tokens = cache_read_tokens_parsed

    reasoning_tokens = reasoning_tokens_parsed or (
        max(1, accumulated_thinking_len // 4) if accumulated_thinking_len > 0 else 0
    )

    return TokenCounts(
        input_tokens,
        output_tokens,
        cache_read_tokens,
        cache_creation_tokens=cache_creation_tokens_parsed or 0,
        reasoning_tokens=reasoning_tokens,
    )


def extract_sse_cache_read_tokens(resp_text: str) -> int:
    """Extracts cache_read_input_tokens from Anthropic SSE text if present.

    Delegates to extract_sse_token_counts to ensure single-pass SSE stream line parsing.
    """
    _, _, cache_read_tokens = extract_sse_token_counts(resp_text, {}, "anthropic")
    return cache_read_tokens
