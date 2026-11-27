from __future__ import annotations

import ast
import copy
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import holon_coherence.payload_cleaner as payload_cleaner_mod
from holon_coherence.mitm_addon import MitmproxyAddon
from holon_coherence.payload_cleaner import JSONContextCleaner
from holon_coherence.providers.anthropic import (
    AnthropicProvider,
    inject_anthropic_cache_control,
    sanitize_and_normalize_cache_controls,
)
from holon_coherence.providers.gemini import GeminiProvider
from holon_coherence.providers.openai import OpenAIProvider
from holon_coherence.providers.translation import (
    translate_gemini_to_openai_request,
    translate_openai_to_gemini_response,
)
from holon_coherence.proxy.steps.base import Outcome, RequestContext
from holon_coherence.proxy.steps.clean_payload import clean_payload, snapshot_request
from holon_coherence.reduction_passes import ReductionContext, ReductionPassRegistry

clean_payload_mod = importlib.import_module("holon_coherence.proxy.steps.clean_payload")


class _Req:
    def __init__(
        self,
        url: str = "https://api.anthropic.com/v1/messages",
        text: str = "",
        **attrs: Any,
    ) -> None:
        self.pretty_url = url
        self.url = url
        self.method = attrs.pop("method", "POST")
        self.path = attrs.pop("path", "/v1/messages")
        self.host = attrs.pop("host", "api.anthropic.com")
        self.port = attrs.pop("port", 443)
        self.scheme = attrs.pop("scheme", "https")
        self.headers: dict[str, str] = attrs.pop("headers", {})
        self._text = text
        for key, value in attrs.items():
            setattr(self, key, value)

    def get_text(self) -> str:
        return self._text

    def set_text(self, text: str) -> None:
        self._text = text


class _InPlaceShortenPass:
    name = "in_place_shorten"

    def applies(self, provider: str, payload: dict[str, Any]) -> bool:
        return isinstance(payload.get("messages"), list) and bool(payload["messages"])

    def apply(self, payload: dict[str, Any], context: ReductionContext) -> dict[str, Any]:
        payload["messages"][0]["content"] = "short"
        context.stats["tool_outputs_omitted"] += 1
        return payload


def _make_addon(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> MitmproxyAddon:
    for name in (
        "HOLON_PASSIVE_MONITORING",
        "COHERENCE_TOKEN_REDUCTION",
        "HOLON_HOST_LOCAL_HOSTS",
        "HOLON_COHERENCE_API_TOKEN",
        "HOLON_COHERENCE_WEB_PASSWORD",
        "HOLON_WIRE_LOG_BASE_DIR",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("holon_coherence.mitm_addon.log_telemetry", lambda _msg: None)
    return MitmproxyAddon(cache_dir=str(tmp_path / "cache"), wire_log_dir=str(tmp_path / "wire"))


def _make_flow(payload: dict[str, Any], url: str = "https://api.anthropic.com/v1/messages") -> SimpleNamespace:
    return SimpleNamespace(id="flow-single-copy", request=_Req(url=url, text=json.dumps(payload)), response=None)


def _duplicate_tool_output_payload() -> dict[str, Any]:
    repeated_output = "duplicate tool output line\n" * 40
    return {
        "model": "claude-3-5-sonnet-20241022",
        "max_tokens": 1024,
        "messages": [
            {"role": "user", "content": "Run the first tool."},
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "tu_1", "name": "read_file", "input": {"path": "a.py"}}],
            },
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "tu_1", "content": repeated_output}],
            },
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "tu_2", "name": "read_file", "input": {"path": "a.py"}}],
            },
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "tu_2", "content": repeated_output}],
            },
            {"role": "assistant", "content": "Checked both."},
            {"role": "user", "content": "Continue."},
        ],
    }


def _spy_module_deepcopies(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    real_deepcopy = copy.deepcopy
    counts = {"clean_payload": 0, "payload_cleaner": 0}

    def _clean_payload_deepcopy(value: Any, memo: dict[int, Any] | None = None) -> Any:
        counts["clean_payload"] += 1
        return real_deepcopy(value, memo)

    def _payload_cleaner_deepcopy(value: Any, memo: dict[int, Any] | None = None) -> Any:
        counts["payload_cleaner"] += 1
        return real_deepcopy(value, memo)

    monkeypatch.setattr(clean_payload_mod, "copy", SimpleNamespace(deepcopy=_clean_payload_deepcopy))
    monkeypatch.setattr(payload_cleaner_mod, "copy", SimpleNamespace(deepcopy=_payload_cleaner_deepcopy))
    return counts


def test_pipeline_mutated_request_performs_single_deepcopy_and_preserves_raw(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    addon = _make_addon(tmp_path, monkeypatch)
    addon.interceptor.cleaner = JSONContextCleaner(pass_registry=ReductionPassRegistry((_InPlaceShortenPass(),)))
    original_payload = {
        "model": "claude-3-5-sonnet-20241022",
        "messages": [{"role": "user", "content": "x" * 200}],
    }
    flow = _make_flow(original_payload)

    real_deepcopy = copy.deepcopy
    global_copies = 0

    def _counting_deepcopy(value: Any, memo: dict[int, Any] | None = None) -> Any:
        nonlocal global_copies
        global_copies += 1
        return real_deepcopy(value, memo)

    monkeypatch.setattr(copy, "deepcopy", _counting_deepcopy)

    addon.request(flow)

    assert global_copies == 1
    assert flow.raw_request_data == original_payload
    assert flow.raw_request_data is not flow.req_data
    assert flow.req_data["messages"][0]["content"] == "short"
    assert flow.cleaner_result.chars_saved > 0
    assert flow.cleaner_result.tool_outputs_omitted == 1


def test_snapshot_then_clean_payload_real_provider_single_copy_across_hot_path(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    addon = _make_addon(tmp_path, monkeypatch)
    counts = _spy_module_deepcopies(monkeypatch)
    original_payload = _duplicate_tool_output_payload()
    request_data = copy.deepcopy(original_payload)
    flow = _make_flow(original_payload)
    ctx = RequestContext.from_flow(addon, flow)
    ctx.data = request_data

    assert snapshot_request(ctx) is Outcome.CONTINUE
    assert clean_payload(ctx) is Outcome.CONTINUE

    assert counts["clean_payload"] == 1
    assert counts["payload_cleaner"] == 0
    assert counts["clean_payload"] + counts["payload_cleaner"] <= 1
    assert flow.raw_request_data == original_payload
    assert flow.raw_request_data is not flow.req_data
    assert flow.req_data != flow.raw_request_data
    assert flow.cleaner_result.chars_saved > 0


def test_local_anthropic_normalization_preserves_raw_request_with_single_copy(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    addon = _make_addon(tmp_path, monkeypatch)
    counts = _spy_module_deepcopies(monkeypatch)
    original_payload = {
        "model": "claude-3-5-sonnet-20241022",
        "thinking": {"type": "enabled", "budget_tokens": 1024},
        "system": [{"type": "text", "text": "Be concise.", "cache_control": {"type": "ephemeral"}}],
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": "Hello", "cache_control": {"type": "ephemeral"}}],
            }
        ],
    }
    request_data = copy.deepcopy(original_payload)
    flow = _make_flow(original_payload, url="http://localhost:11434/v1/messages")
    ctx = RequestContext.from_flow(addon, flow)
    ctx.data = request_data
    ctx.is_local = True

    assert snapshot_request(ctx) is Outcome.CONTINUE
    assert clean_payload(ctx) is Outcome.CONTINUE

    assert counts["clean_payload"] == 1
    assert counts["payload_cleaner"] == 0
    assert "thinking" not in flow.req_data
    assert "cache_control" not in flow.req_data["system"][0]
    assert "cache_control" not in flow.req_data["messages"][0]["content"][0]
    assert flow.raw_request_data == original_payload
    assert flow.raw_request_data["thinking"] == {"type": "enabled", "budget_tokens": 1024}
    assert flow.raw_request_data["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_direct_cleaner_and_standalone_clean_payload_preserve_caller_input(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    counts = _spy_module_deepcopies(monkeypatch)
    direct_cleaner = JSONContextCleaner(pass_registry=ReductionPassRegistry((_InPlaceShortenPass(),)))
    direct_payload = {
        "model": "claude-3-5-sonnet-20241022",
        "messages": [{"role": "user", "content": "y" * 120}],
    }
    direct_expected = copy.deepcopy(direct_payload)

    direct_result = direct_cleaner.process_payload_with_stats(direct_payload, provider="anthropic")

    assert counts["payload_cleaner"] == 1
    assert counts["clean_payload"] == 0
    assert direct_payload == direct_expected
    assert direct_result.payload["messages"][0]["content"] == "short"
    assert direct_result.chars_saved > 0

    counts["clean_payload"] = 0
    counts["payload_cleaner"] = 0

    addon = _make_addon(tmp_path, monkeypatch)
    addon.interceptor.cleaner = JSONContextCleaner(pass_registry=ReductionPassRegistry((_InPlaceShortenPass(),)))
    standalone_payload = {
        "model": "claude-3-5-sonnet-20241022",
        "messages": [{"role": "user", "content": "z" * 120}],
    }
    standalone_expected = copy.deepcopy(standalone_payload)
    flow = _make_flow(standalone_payload)
    ctx = RequestContext.from_flow(addon, flow)
    ctx.data = standalone_payload

    assert clean_payload(ctx) is Outcome.CONTINUE

    assert counts["clean_payload"] == 0
    assert counts["payload_cleaner"] == 1
    assert standalone_payload == standalone_expected
    assert flow.req_data["messages"][0]["content"] == "short"


def test_in_place_context_resets_after_intercept_exception(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    addon = _make_addon(tmp_path, monkeypatch)

    def _raise_boom(_url: str, _data: Any) -> tuple[Any, Any, Any]:
        raise RuntimeError("boom")

    monkeypatch.setattr(addon.interceptor, "intercept_request_with_stats", _raise_boom)

    payload = {"model": "claude-3-5-sonnet-20241022", "messages": [{"role": "user", "content": "hello"}]}
    flow = _make_flow(payload)
    ctx = RequestContext.from_flow(addon, flow)
    ctx.data = payload

    assert snapshot_request(ctx) is Outcome.CONTINUE
    with pytest.raises(RuntimeError, match="boom"):
        clean_payload(ctx)

    caller_payload = _duplicate_tool_output_payload()
    caller_expected = copy.deepcopy(caller_payload)
    result = JSONContextCleaner().process_payload_with_stats(caller_payload, provider="anthropic")

    assert caller_payload == caller_expected
    assert result.payload != caller_expected
    assert result.chars_saved > 0


def _forbid_deepcopy(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("unexpected copy.deepcopy")

    monkeypatch.setattr(copy, "deepcopy", _fail)


def test_anthropic_provider_clean_zero_deepcopy_and_caller_immutability(monkeypatch: pytest.MonkeyPatch) -> None:
    repeated = "anthropic repeated block output " * 10
    payload = {
        "model": "claude-3-5-sonnet-20241022",
        "system": [
            {"type": "text", "text": "sys-a", "cache_control": {"type": "ephemeral", "ttl": "invalid"}},
            {"type": "text", "text": "sys-b", "cache_control": {"type": "ephemeral", "ttl": "1h"}},
        ],
        "tools": [
            {"name": "t1", "input_schema": {"type": "object"}, "cache_control": {"type": "ephemeral"}},
            {"name": "t2", "input_schema": {"type": "object"}, "cache_control": {"type": "ephemeral", "ttl": "1h"}},
            {"name": "t3", "input_schema": {"type": "object"}, "cache_control": {"type": "ephemeral"}},
        ],
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": repeated, "cache_control": {"type": "ephemeral"}}]},
            {"role": "assistant", "content": "ok1"},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "u1", "content": repeated}]},
            {"role": "user", "content": [{"type": "text", "text": repeated}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "u2", "content": repeated}]},
            {"role": "assistant", "content": "ok2"},
            {"role": "user", "content": "recent-1"},
            {"role": "assistant", "content": "recent-2"},
        ],
    }
    expected = copy.deepcopy(payload)
    _forbid_deepcopy(monkeypatch)

    provider = AnthropicProvider()
    cleaner = SimpleNamespace(
        enable_deduplication=True,
        enable_prompt_caching=True,
        max_turns=5,
        recent_turns_to_keep=2,
    )
    stats = {"tool_outputs_omitted": 0, "turns_summarized": 0, "cache_control_injected": 0}
    cleaned = provider.clean(cleaner, payload, {}, stats=stats)

    assert payload == expected
    assert stats["tool_outputs_omitted"] >= 1
    assert stats["turns_summarized"] >= 1
    cleaned["messages"][0]["role"] = "mutated"
    cleaned["messages"][0]["content"][0]["text"] = "mutated"
    cleaned["system"][0]["cache_control"]["ttl"] = "99h"
    cleaned["tools"][0]["cache_control"]["type"] = "mutated"
    assert payload == expected

    sanitized = sanitize_and_normalize_cache_controls(payload)
    injected = inject_anthropic_cache_control(payload, stats={"cache_control_injected": 0})
    sanitized["system"][0]["text"] = "mutated"
    injected["tools"][-1]["name"] = "mutated"
    assert payload == expected

    no_dedup_cleaner = SimpleNamespace(
        enable_deduplication=False,
        enable_prompt_caching=False,
        max_turns=100,
        recent_turns_to_keep=2,
    )
    cleaned_no_dedup = provider.clean(no_dedup_cleaner, payload, {}, stats=None)
    cleaned_no_dedup["messages"][0]["content"][0]["text"] = "mutated"
    assert payload == expected


def test_gemini_provider_clean_zero_deepcopy_and_caller_immutability(monkeypatch: pytest.MonkeyPatch) -> None:
    repeated_text = "gemini repeated text payload " * 10
    repeated_resp = {"output": "gemini repeated tool response " * 10}
    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": repeated_text}]},
            {"role": "model", "parts": [{"text": "calling tool"}]},
            {"role": "user", "parts": [{"functionResponse": {"name": "read", "response": repeated_resp}}]},
            {"role": "user", "parts": [{"functionResponse": {"name": "read", "response": dict(repeated_resp)}}]},
            {"role": "user", "parts": [{"text": repeated_text}]},
            {"role": "model", "parts": [{"text": "done"}]},
            {"role": "user", "parts": [{"text": "final question"}]},
        ]
    }
    expected = copy.deepcopy(payload)
    _forbid_deepcopy(monkeypatch)

    provider = GeminiProvider()
    cleaner = SimpleNamespace(enable_deduplication=True, max_turns=4, recent_turns_to_keep=2)
    stats = {"tool_outputs_omitted": 0, "turns_summarized": 0}
    cleaned = provider.clean(cleaner, payload, {}, stats=stats)

    assert payload == expected
    assert stats["tool_outputs_omitted"] >= 2
    assert stats["turns_summarized"] >= 1
    cleaned["contents"][0]["parts"][0]["text"] = "mutated"
    assert payload == expected

    dedup_only_cleaner = SimpleNamespace(enable_deduplication=True, max_turns=100, recent_turns_to_keep=2)
    cleaned_dedup = provider.clean(dedup_only_cleaner, payload, {}, stats={"tool_outputs_omitted": 0})
    cleaned_dedup["contents"][2]["parts"][0]["functionResponse"]["response"] = {"mutated": True}
    assert payload == expected

    no_dedup_cleaner = SimpleNamespace(enable_deduplication=False, max_turns=100, recent_turns_to_keep=2)
    cleaned_no_dedup = provider.clean(no_dedup_cleaner, payload, {}, stats=None)
    cleaned_no_dedup["contents"][0]["role"] = "mutated"
    assert payload == expected


def test_openai_provider_clean_zero_deepcopy_and_caller_immutability(monkeypatch: pytest.MonkeyPatch) -> None:
    repeated_tool = "openai repeated tool output " * 10
    repeated_msg = "openai repeated long message " * 12
    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": repeated_msg},
            {"role": "tool", "tool_call_id": "c1", "content": repeated_tool},
            {"role": "tool", "tool_call_id": "c2", "content": repeated_tool},
            {"role": "user", "content": repeated_msg},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "recent"},
        ],
    }
    expected = copy.deepcopy(payload)
    _forbid_deepcopy(monkeypatch)

    provider = OpenAIProvider()
    cleaner = SimpleNamespace(enable_deduplication=True, max_turns=4, recent_turns_to_keep=2)
    stats = {"tool_outputs_omitted": 0, "turns_summarized": 0}
    cleaned = provider.clean(cleaner, payload, {}, stats=stats)

    assert payload == expected
    assert stats["tool_outputs_omitted"] >= 2
    assert stats["turns_summarized"] >= 1
    cleaned["messages"][0]["content"] = "mutated"
    assert payload == expected

    no_dedup_cleaner = SimpleNamespace(enable_deduplication=False, max_turns=100, recent_turns_to_keep=2)
    cleaned_no_dedup = provider.clean(no_dedup_cleaner, payload, {}, stats=None)
    cleaned_no_dedup["messages"][1]["content"] = "mutated"
    assert payload == expected


def test_translation_zero_deepcopy_and_caller_immutability(monkeypatch: pytest.MonkeyPatch) -> None:
    gemini_req = {
        "model": "gemini-2.5-pro",
        "systemInstruction": {"parts": [{"text": "Be precise."}]},
        "contents": [
            {"role": "user", "parts": [{"text": "Run lookup"}]},
            {"role": "model", "parts": [{"functionCall": {"name": "lookup", "args": {"q": "abc"}}}]},
            {"role": "user", "parts": [{"functionResponse": {"name": "lookup", "response": {"content": "ok"}}}]},
        ],
        "tools": [
            {
                "functionDeclarations": [
                    {
                        "name": "lookup",
                        "description": "Search",
                        "parameters": {
                            "type": "object",
                            "properties": {"q": {"type": "string", "enum": ["a", "b"]}},
                            "required": ["q"],
                        },
                    }
                ]
            }
        ],
        "generationConfig": {"temperature": 0.2, "stopSequences": ["END", "STOP"]},
    }
    openai_resp = {
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "lookup", "arguments": {"nested": [1, 2]}},
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    gemini_expected = copy.deepcopy(gemini_req)
    openai_expected = copy.deepcopy(openai_resp)
    _forbid_deepcopy(monkeypatch)

    openai_req = translate_gemini_to_openai_request(gemini_req)
    gemini_resp = translate_openai_to_gemini_response(openai_resp)

    assert gemini_req == gemini_expected
    assert openai_resp == openai_expected

    openai_req["tools"][0]["function"]["parameters"]["properties"]["q"]["enum"].append("c")
    openai_req["tools"][0]["function"]["parameters"]["required"].append("extra")
    openai_req["stop"].append("EXTRA")
    gemini_resp["candidates"][0]["content"]["parts"][0]["functionCall"]["args"]["nested"].append(3)

    assert gemini_req == gemini_expected
    assert openai_resp == openai_expected


def test_provider_modules_contain_no_copy_import_or_deepcopy_references() -> None:
    providers_dir = Path(__file__).resolve().parents[1] / "src" / "holon_coherence" / "providers"
    for filename in ("_common.py", "anthropic.py", "gemini.py", "openai.py", "translation.py"):
        tree = ast.parse((providers_dir / filename).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name != "copy" for alias in node.names), filename
            elif isinstance(node, ast.ImportFrom):
                assert node.module != "copy", filename
            elif isinstance(node, ast.Attribute):
                assert node.attr != "deepcopy", filename
            elif isinstance(node, ast.Name):
                assert node.id != "deepcopy", filename
