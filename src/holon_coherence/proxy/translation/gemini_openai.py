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


def translate_gemini_to_openai_request(  # noqa: C901, PLR0912, PLR0915
    gemini_req: dict[str, Any],
    model: str | None = None,
) -> dict[str, Any]:
    """Translates a Gemini v1beta generateContent/streamGenerateContent request to OpenAI format."""
    openai_messages: list[dict[str, Any]] = []
    pending_tool_call_ids: dict[str, list[str]] = {}
    tool_call_counts: dict[str, int] = {}

    # 1. System instruction translation
    sys_inst = gemini_req.get("systemInstruction") or gemini_req.get("system_instruction")
    if isinstance(sys_inst, dict):
        parts = sys_inst.get("parts", [])
        sys_texts = [p["text"] for p in parts if isinstance(p, dict) and "text" in p]
        if sys_texts:
            openai_messages.append({"role": "system", "content": "\n\n".join(sys_texts)})

    # 2. Contents translation
    contents = gemini_req.get("contents", [])
    if isinstance(contents, list):
        for item in contents:
            if not isinstance(item, dict):
                continue
            role = item.get("role", "user")
            mapped_role = "assistant" if role in ("model", "assistant") else "user"
            parts = item.get("parts", [])

            text_chunks: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            tool_responses: list[dict[str, Any]] = []

            for p in parts:
                if not isinstance(p, dict):
                    continue
                if "text" in p:
                    text_chunks.append(str(p["text"]))
                elif "functionCall" in p:
                    fc = p["functionCall"]
                    fn_name = fc.get("name", "")
                    fn_args = fc.get("args", {})
                    call_id = fc.get("id")
                    if not call_id:
                        tool_call_counts[fn_name] = tool_call_counts.get(fn_name, 0) + 1
                        idx = tool_call_counts[fn_name]
                        call_id = f"call_{fn_name}" if idx == 1 else f"call_{fn_name}_{idx}"
                    pending_tool_call_ids.setdefault(fn_name, []).append(call_id)
                    tool_calls.append(
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": fn_name,
                                "arguments": json.dumps(fn_args) if not isinstance(fn_args, str) else fn_args,
                            },
                        }
                    )
                elif "functionResponse" in p:
                    fr = p["functionResponse"]
                    fn_name = fr.get("name", "")
                    resp_val = fr.get("response", {})
                    fr_id = fr.get("id")
                    tool_responses.append(
                        {
                            "name": fn_name,
                            "response": resp_val,
                            "id": fr_id,
                        }
                    )

            if tool_responses:
                for tr in tool_responses:
                    resp_data = tr["response"]
                    if isinstance(resp_data, dict) and "content" in resp_data:
                        content_body = (
                            json.dumps(resp_data["content"])
                            if not isinstance(resp_data["content"], str)
                            else resp_data["content"]
                        )
                    else:
                        content_body = json.dumps(resp_data) if not isinstance(resp_data, str) else resp_data

                    fn_name = tr["name"]
                    tool_call_id = tr.get("id")
                    if not tool_call_id:
                        if pending_tool_call_ids.get(fn_name):
                            tool_call_id = pending_tool_call_ids[fn_name].pop(0)
                        else:
                            tool_call_id = f"call_{fn_name}"

                    openai_messages.append(
                        {
                            "role": "tool",
                            "name": fn_name,
                            "tool_call_id": tool_call_id,
                            "content": content_body,
                        }
                    )
            else:
                msg: dict[str, Any] = {"role": mapped_role}
                if text_chunks:
                    msg["content"] = "\n".join(text_chunks)
                else:
                    msg["content"] = "" if not tool_calls else None
                if tool_calls:
                    msg["tool_calls"] = tool_calls
                openai_messages.append(msg)

    openai_req: dict[str, Any] = {"messages": openai_messages}

    # 3. Model name
    if model:
        openai_req["model"] = model
    elif gemini_req.get("model"):
        openai_req["model"] = gemini_req["model"]
    else:
        openai_req["model"] = "default"

    # 4. Tools translation
    tools = gemini_req.get("tools")
    if isinstance(tools, list):
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
        if openai_tools:
            openai_req["tools"] = openai_tools

    # 5. Generation config
    gen_config = gemini_req.get("generationConfig", {})
    if isinstance(gen_config, dict):
        if "temperature" in gen_config:
            openai_req["temperature"] = gen_config["temperature"]
        if "maxOutputTokens" in gen_config:
            openai_req["max_tokens"] = gen_config["maxOutputTokens"]
        if "topP" in gen_config:
            openai_req["top_p"] = gen_config["topP"]
        if "stopSequences" in gen_config:
            openai_req["stop"] = gen_config["stopSequences"]

    return openai_req


def translate_openai_to_gemini_response(openai_resp: dict[str, Any]) -> dict[str, Any]:  # noqa: C901, PLR0912
    """Translates an OpenAI chat completion response to Gemini v1beta candidate structure."""
    candidates: list[dict[str, Any]] = []
    choices = openai_resp.get("choices", [])

    if isinstance(choices, list) and choices:
        for idx, choice in enumerate(choices):
            if not isinstance(choice, dict):
                continue
            message = choice.get("message", {})
            parts: list[dict[str, Any]] = []

            # 1. Text content
            content = message.get("content")
            if content:
                parts.append({"text": content})

            # 2. Tool calls
            tool_calls = message.get("tool_calls", [])
            if isinstance(tool_calls, list):
                for tc in tool_calls:
                    if not isinstance(tc, dict):
                        continue
                    fn = tc.get("function", {})
                    fn_name = fn.get("name", "")
                    raw_args = fn.get("arguments", "{}")
                    if isinstance(raw_args, str):
                        try:
                            parsed_args = json.loads(raw_args)
                        except Exception:
                            parsed_args = {"raw": raw_args}
                    elif isinstance(raw_args, dict):
                        parsed_args = raw_args
                    else:
                        parsed_args = {}
                    parts.append(
                        {
                            "functionCall": {
                                "name": fn_name,
                                "args": parsed_args,
                            }
                        }
                    )

            if not parts:
                parts.append({"text": ""})

            # Map finish reason
            finish_reason = choice.get("finish_reason")
            mapped_reason = "STOP"
            if finish_reason == "length":
                mapped_reason = "MAX_TOKENS"
            elif finish_reason == "tool_calls":
                mapped_reason = "STOP"

            candidates.append(
                {
                    "index": choice.get("index", idx),
                    "content": {
                        "role": "model",
                        "parts": parts,
                    },
                    "finishReason": mapped_reason,
                }
            )
    else:
        candidates.append(
            {
                "index": 0,
                "content": {
                    "role": "model",
                    "parts": [{"text": ""}],
                },
                "finishReason": "STOP",
            }
        )

    # Usage metadata
    usage = openai_resp.get("usage", {})
    prompt_toks = usage.get("prompt_tokens", 0) if isinstance(usage, dict) else 0
    completion_toks = usage.get("completion_tokens", 0) if isinstance(usage, dict) else 0
    total_toks = usage.get("total_tokens", prompt_toks + completion_toks) if isinstance(usage, dict) else 0

    return {
        "candidates": candidates,
        "usageMetadata": {
            "promptTokenCount": prompt_toks,
            "candidatesTokenCount": completion_toks,
            "totalTokenCount": total_toks,
        },
    }


def translate_openai_sse_chunk_to_gemini(  # noqa: C901, PLR0912, PLR0915
    chunk_str: str,
    stream_state: dict[str, Any] | None = None,
) -> str:
    """Translates OpenAI SSE streaming chunk(s) to Gemini v1beta candidate SSE chunks."""
    output_lines: list[str] = []
    lines = chunk_str.split("\n")

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == "data: [DONE]":
            continue
        if stripped.startswith("data:"):
            payload_str = stripped[len("data:") :].strip()
            if not payload_str:
                continue
            try:
                chunk_json = json.loads(payload_str)
            except Exception:
                continue

            usage = chunk_json.get("usage")
            usage_metadata: dict[str, Any] | None = None
            if isinstance(usage, dict):
                usage_metadata = {
                    "promptTokenCount": usage.get("prompt_tokens", 0),
                    "candidatesTokenCount": usage.get("completion_tokens", 0),
                    "totalTokenCount": usage.get("total_tokens", 0),
                }

            choices = chunk_json.get("choices", [])
            if not choices and usage_metadata:
                output_lines.append(f"data: {json.dumps({'usageMetadata': usage_metadata})}")
                continue

            for choice in choices:
                delta = choice.get("delta", {})
                parts: list[dict[str, Any]] = []

                if "content" in delta and delta["content"] is not None:
                    parts.append({"text": delta["content"]})

                tool_calls = delta.get("tool_calls", [])
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    fn_name = fn.get("name", "")
                    raw_args = fn.get("arguments", "")

                    if stream_state is not None:
                        idx = tc.get("index", 0)
                        tool_buf = stream_state.setdefault("tool_calls", {}).setdefault(
                            idx, {"name": "", "arguments": ""}
                        )
                        if fn_name:
                            tool_buf["name"] = fn_name
                        if raw_args:
                            tool_buf["arguments"] += raw_args
                    else:
                        if not fn_name and not raw_args:
                            continue
                        if not fn_name:
                            continue
                        if isinstance(raw_args, str):
                            try:
                                parsed_args = json.loads(raw_args) if raw_args else {}
                            except Exception:
                                continue
                        elif isinstance(raw_args, dict):
                            parsed_args = raw_args
                        else:
                            parsed_args = {}
                        parts.append({"functionCall": {"name": fn_name, "args": parsed_args}})

                finish_reason = choice.get("finish_reason")
                if finish_reason == "tool_calls" and stream_state is not None:
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

                gemini_candidate: dict[str, Any] = {}
                if parts:
                    gemini_candidate["content"] = {"role": "model", "parts": parts}
                if finish_reason:
                    gemini_candidate["finishReason"] = (
                        "STOP" if finish_reason in ("stop", "tool_calls") else "MAX_TOKENS"
                    )

                if gemini_candidate:
                    gemini_payload = {"candidates": [gemini_candidate]}
                    if usage_metadata:
                        gemini_payload["usageMetadata"] = usage_metadata
                        usage_metadata = None
                    output_lines.append(f"data: {json.dumps(gemini_payload)}")
                elif usage_metadata:
                    output_lines.append(f"data: {json.dumps({'usageMetadata': usage_metadata})}")
                    usage_metadata = None

    if not output_lines:
        return ""
    return "\n\n".join(output_lines) + "\n\n"
