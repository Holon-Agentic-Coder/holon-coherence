from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from holon_coherence.payload_cleaner import CleaningResult, JSONContextCleaner
from holon_coherence.reduction_passes import (
    ProviderCleanPass,
    ReductionContext,
    ReductionPass,
    ReductionPassRegistry,
    default_pass_registry,
)


class _AttributeDuckPass:
    name: str = "duck_attr"

    def applies(self, provider: str, payload: dict[str, Any]) -> bool:
        return True

    def apply(self, payload: dict[str, Any], context: ReductionContext) -> dict[str, Any]:
        payload.setdefault("trace", []).append(self.name)
        return payload


class _PropertyDuckPass:
    def __init__(self, pass_name: str = "duck_prop") -> None:
        self._name = pass_name

    @property
    def name(self) -> str:
        return self._name

    def applies(self, provider: str, payload: dict[str, Any]) -> bool:
        return True

    def apply(self, payload: dict[str, Any], context: ReductionContext) -> dict[str, Any]:
        payload.setdefault("trace", []).append(self.name)
        return payload


class _MissingNamePass:
    def applies(self, provider: str, payload: dict[str, Any]) -> bool:
        return True

    def apply(self, payload: dict[str, Any], context: ReductionContext) -> dict[str, Any]:
        return payload


class _MissingAppliesPass:
    name: str = "missing_applies"

    def apply(self, payload: dict[str, Any], context: ReductionContext) -> dict[str, Any]:
        return payload


class _MissingApplyPass:
    name: str = "missing_apply"

    def applies(self, provider: str, payload: dict[str, Any]) -> bool:
        return True


class _BlankNamePass:
    name: str = "   "

    def applies(self, provider: str, payload: dict[str, Any]) -> bool:
        return True

    def apply(self, payload: dict[str, Any], context: ReductionContext) -> dict[str, Any]:
        return payload


class _OpenAIOnlyPass:
    name: str = "openai_only"

    def applies(self, provider: str, payload: dict[str, Any]) -> bool:
        return provider == "openai"

    def apply(self, payload: dict[str, Any], context: ReductionContext) -> dict[str, Any]:
        payload.setdefault("trace", []).append(self.name)
        return payload


class _CustomTrimPass:
    name: str = "custom_trim"

    def __init__(self) -> None:
        self.observed_snapshots: list[dict[str, Any]] = []

    def applies(self, provider: str, payload: dict[str, Any]) -> bool:
        return isinstance(payload.get("messages"), list)

    def apply(self, payload: dict[str, Any], context: ReductionContext) -> dict[str, Any]:
        self.observed_snapshots.append(
            {
                "provider": context.provider,
                "enable_deduplication": context.enable_deduplication,
                "enable_prompt_caching": context.enable_prompt_caching,
                "max_turns": context.max_turns,
                "recent_turns_to_keep": context.recent_turns_to_keep,
                "has_seen_hashes": isinstance(context.seen_content_hashes, dict),
                "has_stats": isinstance(context.stats, dict),
                "is_cleaner": isinstance(context.cleaner, JSONContextCleaner),
            }
        )
        payload.pop("verbose_debug_metadata", None)
        for msg in payload.get("messages", []):
            if isinstance(msg, dict) and isinstance(msg.get("content"), str):
                msg["content"] = " ".join(msg["content"].split())
        context.stats["tool_outputs_omitted"] += 1
        return payload


def _make_context(provider: str = "anthropic") -> ReductionContext:
    cleaner = JSONContextCleaner()
    return ReductionContext(
        cleaner=cleaner,
        provider=provider,
        seen_content_hashes={},
        stats={
            "tool_outputs_omitted": 0,
            "turns_summarized": 0,
            "cache_control_injected": 0,
        },
    )


def test_structural_protocol_conformance_and_validation() -> None:
    attr_pass = _AttributeDuckPass()
    prop_pass = _PropertyDuckPass()
    builtin_pass = ProviderCleanPass()

    assert isinstance(attr_pass, ReductionPass)
    assert isinstance(prop_pass, ReductionPass)
    assert isinstance(builtin_pass, ReductionPass)

    registry = ReductionPassRegistry()
    for invalid_pass in (_MissingNamePass(), _MissingAppliesPass(), _MissingApplyPass()):
        assert not isinstance(invalid_pass, ReductionPass)
        with pytest.raises(TypeError):
            registry.register(invalid_pass)  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        registry.register(_BlankNamePass())


def test_registry_deterministic_ordering_and_mutation() -> None:
    pass_a = _PropertyDuckPass("pass_a")
    pass_b = _PropertyDuckPass("pass_b")
    pass_c = _PropertyDuckPass("pass_c")

    registry = ReductionPassRegistry([pass_a, pass_b])
    registry.register(pass_c)

    assert len(registry) == 3
    assert registry.names() == ("pass_a", "pass_b", "pass_c")
    assert list(registry) == [pass_a, pass_b, pass_c]
    assert registry.get("pass_b") is pass_b
    assert registry.get("nonexistent") is None

    with pytest.raises(ValueError):
        registry.register(_PropertyDuckPass("pass_b"))

    replacement_b = _PropertyDuckPass("pass_b")
    registry.register(replacement_b, replace=True)
    assert registry.names() == ("pass_a", "pass_b", "pass_c")
    assert registry.get("pass_b") is replacement_b

    removed = registry.unregister("pass_b")
    assert removed is replacement_b
    assert registry.unregister("pass_b") is None
    assert registry.names() == ("pass_a", "pass_c")

    forward_registry = ReductionPassRegistry([_PropertyDuckPass("first"), _PropertyDuckPass("second")])
    reverse_registry = ReductionPassRegistry([_PropertyDuckPass("second"), _PropertyDuckPass("first")])

    forward_out = forward_registry.run({}, _make_context())
    reverse_out = reverse_registry.run({}, _make_context())

    assert forward_out["trace"] == ["first", "second"]
    assert reverse_out["trace"] == ["second", "first"]


def test_pass_toggling_and_isolation() -> None:
    registry = ReductionPassRegistry(
        [
            ProviderCleanPass(),
            _PropertyDuckPass("pass_a"),
            _PropertyDuckPass("pass_b"),
        ]
    )

    only_b = registry.run({"messages": []}, _make_context(), enabled_passes={"pass_b"})
    assert only_b.get("trace") == ["pass_b"]

    none_active = registry.run({"messages": []}, _make_context(), enabled_passes=set())
    assert "trace" not in none_active

    anthropic_payload = {
        "model": "claude-3-5-sonnet-20241022",
        "messages": [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
            {"role": "user", "content": "Continue"},
        ],
    }
    skip_provider = JSONContextCleaner(
        pass_registry=registry,
        disabled_passes={"provider_clean"},
    )
    skipped_result = skip_provider.process_payload_with_stats(anthropic_payload, provider="anthropic")
    assert skipped_result.cache_control_injected == 0
    assert skipped_result.payload["trace"] == ["pass_a", "pass_b"]

    disabled_wins = registry.run(
        {"messages": []},
        _make_context(),
        enabled_passes={"pass_a", "pass_b"},
        disabled_passes={"pass_b"},
    )
    assert disabled_wins["trace"] == ["pass_a"]


def test_provider_gating_via_applies() -> None:
    registry = ReductionPassRegistry([_OpenAIOnlyPass()])

    openai_out = registry.run({}, _make_context(provider="openai"))
    anthropic_out = registry.run({}, _make_context(provider="anthropic"))

    assert openai_out.get("trace") == ["openai_only"]
    assert "trace" not in anthropic_out


def test_custom_pass_injection_and_context_exposure() -> None:
    custom_pass = _CustomTrimPass()
    registry = default_pass_registry()
    registry.register(custom_pass)

    cleaner = JSONContextCleaner(
        enable_deduplication=False,
        enable_prompt_caching=True,
        max_turns=25,
        recent_turns_to_keep=4,
        pass_registry=registry,
    )
    payload = {
        "model": "gpt-4o",
        "verbose_debug_metadata": {"blob": "x" * 200},
        "messages": [
            {"role": "user", "content": "Trim    extra     spaces    here"},
        ],
    }

    result = cleaner.process_payload_with_stats(payload, provider="openai")
    cleaned_direct = cleaner.process_payload(payload, provider="openai")

    assert result.payload == cleaned_direct
    assert "verbose_debug_metadata" not in result.payload
    assert result.payload["messages"][0]["content"] == "Trim extra spaces here"
    assert result.tool_outputs_omitted == 1
    assert result.chars_saved > 200
    assert len(custom_pass.observed_snapshots) == 2
    assert custom_pass.observed_snapshots[0] == {
        "provider": "openai",
        "enable_deduplication": False,
        "enable_prompt_caching": True,
        "max_turns": 25,
        "recent_turns_to_keep": 4,
        "has_seen_hashes": True,
        "has_stats": True,
        "is_cleaner": True,
    }

    cleaner_a = JSONContextCleaner()
    cleaner_b = JSONContextCleaner()
    cleaner_a.pass_registry.register(_AttributeDuckPass())
    assert cleaner_a.pass_registry.names() == ("provider_clean", "duck_attr")
    assert cleaner_b.pass_registry.names() == ("provider_clean",)


def test_ab_pass_comparison_on_shared_registry() -> None:
    shared_registry = ReductionPassRegistry([ProviderCleanPass(), _CustomTrimPass()])
    payload = {
        "model": "gpt-4o",
        "verbose_debug_metadata": {"trace": "y" * 160},
        "messages": [
            {"role": "system", "content": "You are concise."},
            {"role": "user", "content": "Compare    baseline    and    variant    payloads"},
        ],
    }

    baseline_cleaner = JSONContextCleaner(
        pass_registry=shared_registry,
        disabled_passes={"custom_trim"},
    )
    variant_cleaner = JSONContextCleaner(
        pass_registry=shared_registry,
        enabled_passes={"provider_clean", "custom_trim"},
    )

    baseline_result = baseline_cleaner.process_payload_with_stats(payload, provider="openai")
    variant_result = variant_cleaner.process_payload_with_stats(payload, provider="openai")

    assert "verbose_debug_metadata" in baseline_result.payload
    assert "verbose_debug_metadata" not in variant_result.payload
    assert baseline_result.chars_saved == 0
    assert variant_result.chars_saved > baseline_result.chars_saved
    assert variant_result.payload["messages"][1]["content"] == "Compare baseline and variant payloads"


@pytest.mark.parametrize(
    ("provider", "payload"),
    [
        (
            "anthropic",
            {
                "model": "claude-3-5-sonnet-20241022",
                "system": "You are a helpful coding assistant.",
                "messages": [
                    {"role": "user", "content": "Inspect output"},
                    {
                        "role": "assistant",
                        "content": [{"type": "tool_use", "id": "t1", "name": "read", "input": {}}],
                    },
                    {
                        "role": "user",
                        "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "A" * 400}],
                    },
                    {
                        "role": "assistant",
                        "content": [{"type": "tool_use", "id": "t2", "name": "read", "input": {}}],
                    },
                    {
                        "role": "user",
                        "content": [{"type": "tool_result", "tool_use_id": "t2", "content": "A" * 400}],
                    },
                ],
            },
        ),
        (
            "openai",
            {
                "model": "gpt-4o",
                "messages": [
                    {"role": "user", "content": "Check tool"},
                    {"role": "tool", "tool_call_id": "c1", "content": "B" * 400},
                    {"role": "tool", "tool_call_id": "c2", "content": "B" * 400},
                ],
            },
        ),
        (
            "gemini",
            {
                "contents": [
                    {"role": "user", "parts": [{"text": "Hello"}]},
                    {"role": "model", "parts": [{"text": "World"}]},
                ]
            },
        ),
    ],
)
def test_default_cleaner_matches_direct_provider_clean_pass(
    provider: str,
    payload: dict[str, Any],
) -> None:
    cleaner = JSONContextCleaner()
    default_result = cleaner.process_payload_with_stats(payload, provider=provider)

    direct_stats = {
        "tool_outputs_omitted": 0,
        "turns_summarized": 0,
        "cache_control_injected": 0,
    }
    direct_context = ReductionContext(
        cleaner=cleaner,
        provider=provider,
        seen_content_hashes={},
        stats=direct_stats,
    )
    direct_payload = ProviderCleanPass().apply(copy.deepcopy(payload), direct_context)
    expected_chars_saved = max(0, len(json.dumps(payload)) - len(json.dumps(direct_payload)))
    expected_result = CleaningResult(
        payload=direct_payload,
        tool_outputs_omitted=direct_stats["tool_outputs_omitted"],
        turns_summarized=direct_stats["turns_summarized"],
        cache_control_injected=direct_stats["cache_control_injected"],
        chars_saved=expected_chars_saved,
    )

    assert default_result == expected_result
