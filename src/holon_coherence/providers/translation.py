"""Bidirectional translation between Gemini v1beta and OpenAI protocols."""

from __future__ import annotations

import copy
import json
from typing import Any

__all__ = [
    "translate_gemini_to_openai_request",
    "translate_openai_sse_chunk_to_gemini",
    "translate_openai_to_gemini_response",
]


def _translate_system_instruction(gemini_req: dict[str, Any]) -> dict[str, Any] | None:
    sys_inst = gemini_req.get("systemInstruction") or gemini_req.get("system_instruction")
    if not isinstance(sys_inst, dict):
        return None
    parts = sys_inst.get("parts", [])
    sys_texts = [p["text"] for p in parts if isinstance(p, dict) and "text" in p]
    if sys_texts:
        return {"role": "system", "content": "\n\n".join(sys_texts)}
    return None


def _format_function_call(
    fc: dict[str, Any],
    pending_tool_call_ids: dict[str, list[str]],
    tool_call_counts: dict[str, int],
) -> dict[str, Any]:
    fn_name = fc.get("name", "")
    fn_args = fc.get("args", {})
    call_id = fc.get("id")
    if not call_id:
        tool_call_counts[fn_name] = tool_call_counts.get(fn_name, 0) + 1
        idx = tool_call_counts[fn_name]
        call_id = f"call_{fn_name}" if idx == 1 else f"call_{fn_name}_{idx}"
    pending_tool_call_ids.setdefault(fn_name, []).append(call_id)
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": fn_name,
            "arguments": json.dumps(fn_args) if not isinstance(fn_args, str) else fn_args,
        },
    }


class _PartCollector:
    def __init__(self, pending_ids: dict[str, list[str]], counts: dict[str, int]) -> None:
        self.pending_ids = pending_ids
        self.counts = counts
        self.text_chunks: list[str] = []
        self.tool_calls: list[dict[str, Any]] = []
        self.tool_responses: list[dict[str, Any]] = []


def _process_content_part(
    p: dict[str, Any],
    collector: _PartCollector,
) -> None:
    if "text" in p:
        collector.text_chunks.append(str(p["text"]))
    elif "functionCall" in p:
        fc = p["functionCall"]
        if isinstance(fc, dict):
            collector.tool_calls.append(_format_function_call(fc, collector.pending_ids, collector.counts))
    elif "functionResponse" in p:
        fr = p["functionResponse"]
        if isinstance(fr, dict):
            collector.tool_responses.append(
                {
                    "name": fr.get("name", ""),
                    "response": fr.get("response", {}),
                    "id": fr.get("id"),
                }
            )


def _translate_tool_responses(
    tool_responses: list[dict[str, Any]],
    pending_tool_call_ids: dict[str, list[str]],
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for tr in tool_responses:
        resp_data = tr["response"]
        if isinstance(resp_data, dict) and "content" in resp_data:
            content = resp_data["content"]
            content_body = json.dumps(content) if not isinstance(content, str) else content
        else:
            content_body = json.dumps(resp_data) if not isinstance(resp_data, str) else resp_data

        fn_name = tr["name"]
        tool_call_id = tr.get("id")
        if not tool_call_id:
            pending = pending_tool_call_ids.get(fn_name)
            tool_call_id = pending.pop(0) if pending else f"call_{fn_name}"

        messages.append(
            {
                "role": "tool",
                "name": fn_name,
                "tool_call_id": tool_call_id,
                "content": content_body,
            }
        )
    return messages


def _translate_single_content_item(
    item: dict[str, Any],
    pending_tool_call_ids: dict[str, list[str]],
    tool_call_counts: dict[str, int],
) -> list[dict[str, Any]]:
    role = item.get("role", "user")
    mapped_role = "assistant" if role in ("model", "assistant") else "user"
    parts = item.get("parts", [])

    collector = _PartCollector(pending_tool_call_ids, tool_call_counts)

    if isinstance(parts, list):
        for p in parts:
            if isinstance(p, dict):
                _process_content_part(p, collector)

    if collector.tool_responses:
        return _translate_tool_responses(collector.tool_responses, pending_tool_call_ids)

    msg: dict[str, Any] = {"role": mapped_role}
    if collector.text_chunks:
        msg["content"] = "\n".join(collector.text_chunks)
    else:
        msg["content"] = "" if not collector.tool_calls else None
    if collector.tool_calls:
        msg["tool_calls"] = collector.tool_calls
    return [msg]


def _translate_contents(
    contents: list[Any],
    pending_tool_call_ids: dict[str, list[str]],
    tool_call_counts: dict[str, int],
) -> list[dict[str, Any]]:
    openai_messages: list[dict[str, Any]] = []
    for item in contents:
        if isinstance(item, dict):
            openai_messages.extend(_translate_single_content_item(item, pending_tool_call_ids, tool_call_counts))
    return openai_messages


def _translate_tools(tools: list[Any]) -> list[dict[str, Any]]:
    openai_tools: list[dict[str, Any]] = []
    for t in tools:
        if not isinstance(t, dict):
            continue
        for fd in t.get("functionDeclarations", []):
            if not isinstance(fd, dict):
                continue
            tool_dict: dict[str, Any] = {
                "type": "function",
                "function": {
                    "name": fd.get("name", ""),
                    "description": fd.get("description", ""),
                },
            }
            if "parameters" in fd and isinstance(fd["parameters"], dict):
                tool_dict["function"]["parameters"] = copy.deepcopy(fd["parameters"])
            openai_tools.append(tool_dict)
    return openai_tools


def _translate_gen_config(gen_config: dict[str, Any], openai_req: dict[str, Any]) -> None:
    if "temperature" in gen_config:
        openai_req["temperature"] = gen_config["temperature"]
    if "maxOutputTokens" in gen_config:
        openai_req["max_tokens"] = gen_config["maxOutputTokens"]
    if "topP" in gen_config:
        openai_req["top_p"] = gen_config["topP"]
    if "stopSequences" in gen_config:
        openai_req["stop"] = gen_config["stopSequences"]


def translate_gemini_to_openai_request(
    gemini_req: dict[str, Any],
    model: str | None = None,
) -> dict[str, Any]:
    """Translates a Gemini v1beta generateContent/streamGenerateContent request to OpenAI format."""
    openai_messages: list[dict[str, Any]] = []
    pending_tool_call_ids: dict[str, list[str]] = {}
    tool_call_counts: dict[str, int] = {}

    sys_msg = _translate_system_instruction(gemini_req)
    if sys_msg:
        openai_messages.append(sys_msg)

    contents = gemini_req.get("contents", [])
    if isinstance(contents, list):
        openai_messages.extend(_translate_contents(contents, pending_tool_call_ids, tool_call_counts))

    resolved_model = model or gemini_req.get("model") or "default"
    openai_req: dict[str, Any] = {"messages": openai_messages, "model": resolved_model}

    tools = gemini_req.get("tools")
    if isinstance(tools, list):
        openai_tools = _translate_tools(tools)
        if openai_tools:
            openai_req["tools"] = openai_tools

    gen_config = gemini_req.get("generationConfig", {})
    if isinstance(gen_config, dict):
        _translate_gen_config(gen_config, openai_req)

    return openai_req


def _parse_func_args(raw_args: Any) -> dict[str, Any]:
    if isinstance(raw_args, dict):
        return raw_args
    if isinstance(raw_args, str):
        try:
            return json.loads(raw_args)
        except Exception:
            return {"raw": raw_args}
    return {}


def _translate_choice_parts(message: dict[str, Any]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    content = message.get("content")
    if content:
        parts.append({"text": content})

    tool_calls = message.get("tool_calls", [])
    if isinstance(tool_calls, list):
        for tc in tool_calls:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function", {})
            fn_name = fn.get("name", "")
            raw_args = fn.get("arguments", "{}")
            parts.append({"functionCall": {"name": fn_name, "args": _parse_func_args(raw_args)}})

    if not parts:
        parts.append({"text": ""})
    return parts


def _map_finish_reason(finish_reason: Any) -> str:
    if finish_reason == "length":
        return "MAX_TOKENS"
    return "STOP"


def _translate_choices(choices: list[Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for idx, choice in enumerate(choices):
        if not isinstance(choice, dict):
            continue
        message = choice.get("message", {})
        parts = _translate_choice_parts(message)
        mapped_reason = _map_finish_reason(choice.get("finish_reason"))
        candidates.append(
            {
                "index": choice.get("index", idx),
                "content": {"role": "model", "parts": parts},
                "finishReason": mapped_reason,
            }
        )
    return candidates


def _translate_usage_to_gemini(usage: Any) -> dict[str, Any]:
    prompt_toks = usage.get("prompt_tokens", 0) if isinstance(usage, dict) else 0
    completion_toks = usage.get("completion_tokens", 0) if isinstance(usage, dict) else 0
    total_toks = usage.get("total_tokens", prompt_toks + completion_toks) if isinstance(usage, dict) else 0
    return {
        "promptTokenCount": prompt_toks,
        "candidatesTokenCount": completion_toks,
        "totalTokenCount": total_toks,
    }


def translate_openai_to_gemini_response(openai_resp: dict[str, Any]) -> dict[str, Any]:
    """Translates an OpenAI chat completion response to Gemini v1beta candidate structure."""
    choices = openai_resp.get("choices", [])
    if isinstance(choices, list) and choices:
        candidates = _translate_choices(choices)
    else:
        candidates = [{"index": 0, "content": {"role": "model", "parts": [{"text": ""}]}, "finishReason": "STOP"}]

    return {
        "candidates": candidates,
        "usageMetadata": _translate_usage_to_gemini(openai_resp.get("usage", {})),
    }


def _buffer_tool_call(tc: dict[str, Any], stream_state: dict[str, Any]) -> None:
    fn = tc.get("function", {})
    fn_name = fn.get("name", "")
    raw_args = fn.get("arguments", "")
    idx = tc.get("index", 0)
    tool_buf = stream_state.setdefault("tool_calls", {}).setdefault(idx, {"name": "", "arguments": ""})
    if fn_name:
        tool_buf["name"] = fn_name
    if raw_args:
        tool_buf["arguments"] += raw_args


def _extract_unbuffered_tool_call(tc: dict[str, Any]) -> dict[str, Any] | None:
    fn = tc.get("function", {})
    fn_name = fn.get("name", "")
    raw_args = fn.get("arguments", "")
    if not fn_name:
        return None
    parsed_args = _parse_func_args(raw_args) if raw_args else {}
    return {"functionCall": {"name": fn_name, "args": parsed_args}}


def _flush_buffered_tool_calls(stream_state: dict[str, Any]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    buffered_calls = stream_state.pop("tool_calls", {})
    for idx in sorted(buffered_calls.keys()):
        b_call = buffered_calls[idx]
        b_name = b_call.get("name", "")
        b_args_raw = b_call.get("arguments", "{}")
        if not b_name:
            continue
        try:
            b_args = json.loads(b_args_raw) if b_args_raw else {}
        except Exception:
            b_args = {"raw": b_args_raw}
        parts.append({"functionCall": {"name": b_name, "args": b_args}})
    return parts


def _process_sse_choice_parts(
    choice: dict[str, Any],
    stream_state: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], str | None]:
    parts: list[dict[str, Any]] = []
    delta = choice.get("delta", {})
    if "content" in delta and delta["content"] is not None:
        parts.append({"text": delta["content"]})

    for tc in delta.get("tool_calls", []):
        if not isinstance(tc, dict):
            continue
        if stream_state is not None:
            _buffer_tool_call(tc, stream_state)
        else:
            fc_part = _extract_unbuffered_tool_call(tc)
            if fc_part:
                parts.append(fc_part)

    finish_reason = choice.get("finish_reason")
    if finish_reason == "tool_calls" and stream_state is not None:
        parts.extend(_flush_buffered_tool_calls(stream_state))

    return parts, finish_reason


def _build_gemini_candidate_chunk(
    choice: dict[str, Any],
    stream_state: dict[str, Any] | None,
) -> dict[str, Any]:
    parts, finish_reason = _process_sse_choice_parts(choice, stream_state)
    cand: dict[str, Any] = {}
    if parts:
        cand["content"] = {"role": "model", "parts": parts}
    if finish_reason:
        cand["finishReason"] = "STOP" if finish_reason in ("stop", "tool_calls") else "MAX_TOKENS"
    return cand


def _translate_sse_usage(usage: dict[str, Any]) -> dict[str, Any]:
    return {
        "promptTokenCount": usage.get("prompt_tokens", 0),
        "candidatesTokenCount": usage.get("completion_tokens", 0),
        "totalTokenCount": usage.get("total_tokens", 0),
    }


def _process_single_sse_payload(
    payload_str: str,
    stream_state: dict[str, Any] | None,
    output_lines: list[str],
) -> None:
    try:
        chunk_json = json.loads(payload_str)
    except Exception:
        return
    if not isinstance(chunk_json, dict):
        return

    usage = chunk_json.get("usage")
    usage_metadata = _translate_sse_usage(usage) if isinstance(usage, dict) else None
    choices = chunk_json.get("choices", [])
    if not choices and usage_metadata:
        output_lines.append(f"data: {json.dumps({'usageMetadata': usage_metadata})}")
        return

    for choice in choices:
        cand = _build_gemini_candidate_chunk(choice, stream_state)
        if cand:
            payload: dict[str, Any] = {"candidates": [cand]}
            if usage_metadata:
                payload["usageMetadata"] = usage_metadata
                usage_metadata = None
            output_lines.append(f"data: {json.dumps(payload)}")
        elif usage_metadata:
            output_lines.append(f"data: {json.dumps({'usageMetadata': usage_metadata})}")
            usage_metadata = None


def translate_openai_sse_chunk_to_gemini(
    chunk_str: str,
    stream_state: dict[str, Any] | None = None,
) -> str:
    """Translates OpenAI SSE streaming chunk(s) to Gemini v1beta candidate SSE chunks."""
    output_lines: list[str] = []
    for line in chunk_str.split("\n"):
        stripped = line.strip()
        if not stripped or stripped == "data: [DONE]":
            continue
        if stripped.startswith("data:"):
            payload_str = stripped[len("data:") :].strip()
            if payload_str:
                _process_single_sse_payload(payload_str, stream_state, output_lines)

    if not output_lines:
        return ""
    return "\n\n".join(output_lines) + "\n\n"
