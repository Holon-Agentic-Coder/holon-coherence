from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from holon_coherence.providers import get_provider

if TYPE_CHECKING:
    from holon_coherence.payload_cleaner import JSONContextCleaner


@dataclass
class ReductionContext:
    cleaner: JSONContextCleaner
    provider: str
    seen_content_hashes: dict[str, tuple[int, str]]
    stats: dict[str, int]

    @property
    def enable_deduplication(self) -> bool:
        return self.cleaner.enable_deduplication

    @property
    def enable_prompt_caching(self) -> bool:
        return self.cleaner.enable_prompt_caching

    @property
    def max_turns(self) -> int:
        return self.cleaner.max_turns

    @property
    def recent_turns_to_keep(self) -> int:
        return self.cleaner.recent_turns_to_keep


@runtime_checkable
class ReductionPass(Protocol):
    @property
    def name(self) -> str: ...

    def applies(self, provider: str, payload: dict[str, Any]) -> bool: ...

    def apply(self, payload: dict[str, Any], context: ReductionContext) -> dict[str, Any]: ...


class ProviderCleanPass:
    name: str = "provider_clean"

    def applies(self, provider: str, payload: dict[str, Any]) -> bool:
        return True

    def apply(self, payload: dict[str, Any], context: ReductionContext) -> dict[str, Any]:
        provider_format = get_provider(context.provider)
        return provider_format.clean(
            context.cleaner,
            payload,
            context.seen_content_hashes,
            stats=context.stats,
        )


class ReductionPassRegistry:
    def __init__(self, passes: Iterable[ReductionPass] | None = None) -> None:
        self._passes: dict[str, ReductionPass] = {}
        if passes is not None:
            for reduction_pass in passes:
                self.register(reduction_pass)

    def register(self, reduction_pass: ReductionPass, *, replace: bool = False) -> None:
        if not isinstance(reduction_pass, ReductionPass):
            raise TypeError(f"Expected ReductionPass, got {type(reduction_pass).__name__}")
        pass_name = reduction_pass.name
        if not isinstance(pass_name, str) or not pass_name.strip():
            raise ValueError("ReductionPass.name must be a non-empty string")
        if pass_name in self._passes and not replace:
            raise ValueError(f"ReductionPass already registered: {pass_name!r}")
        self._passes[pass_name] = reduction_pass

    def unregister(self, name: str) -> ReductionPass | None:
        return self._passes.pop(name, None)

    def get(self, name: str) -> ReductionPass | None:
        return self._passes.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(self._passes)

    def __iter__(self) -> Iterator[ReductionPass]:
        return iter(self._passes.values())

    def __len__(self) -> int:
        return len(self._passes)

    def iter_active(
        self,
        enabled_passes: Collection[str] | None = None,
        disabled_passes: Collection[str] | None = None,
    ) -> Iterator[ReductionPass]:
        enabled = set(enabled_passes) if enabled_passes is not None else None
        disabled = set(disabled_passes) if disabled_passes is not None else None
        for name, reduction_pass in self._passes.items():
            if enabled is not None and name not in enabled:
                continue
            if disabled is not None and name in disabled:
                continue
            yield reduction_pass

    def run(
        self,
        payload: dict[str, Any],
        context: ReductionContext,
        *,
        enabled_passes: Collection[str] | None = None,
        disabled_passes: Collection[str] | None = None,
    ) -> dict[str, Any]:
        current_payload = payload
        for reduction_pass in self.iter_active(
            enabled_passes=enabled_passes,
            disabled_passes=disabled_passes,
        ):
            if reduction_pass.applies(context.provider, current_payload):
                current_payload = reduction_pass.apply(current_payload, context)
        return current_payload


def default_pass_registry() -> ReductionPassRegistry:
    return ReductionPassRegistry((ProviderCleanPass(),))
