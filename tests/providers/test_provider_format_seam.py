from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from holon_coherence.parsers import sse as sse_module
from holon_coherence.parsers.sse import extract_sse_content
from holon_coherence.parsers.tokens import TokenCounts
from holon_coherence.providers import (
    ProviderFormat,
    detect_provider_name,
    register_provider,
    registry,
    resolve_provider,
)
from holon_coherence.providers.anthropic import AnthropicProvider
from holon_coherence.providers.gemini import GeminiProvider
from holon_coherence.providers.openai import OpenAIProvider
from holon_coherence.proxy.addon import MITMProxyInterceptor
from holon_coherence.proxy.routing import is_local_target
from tests.test_import_cycle_ratchet import PACKAGE_ROOT, collect_subpackage_edges, find_cyclic_edges

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROVIDERS_DIR = REPO_ROOT / "src" / "holon_coherence" / "providers"
PARSERS_DIR = REPO_ROOT / "src" / "holon_coherence" / "parsers"


class CustomSeamProvider:
    def matches(self, url: str, payload: dict[str, Any] | None = None) -> bool:
        if url and "custom-seam.example" in url.lower():
            return True
        return isinstance(payload, dict) and "custom_seam_marker" in payload

    def is_cloud_host(self, host: str) -> bool:
        return host.lower() == "api.custom-seam.example"

    def clean(
        self,
        cleaner: Any,
        payload: dict[str, Any],
        seen_content_hashes: dict[str, tuple[int, str]],
        stats: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        return payload

    def token_counts_from_sse(self, resp_text: str, req_data: dict[str, Any]) -> TokenCounts:
        return TokenCounts(1, 2, 0)

    def token_counts_from_dict(self, req_data: dict[str, Any], resp_data: dict[str, Any]) -> TokenCounts:
        return TokenCounts(1, 2, 0)

    def extract_sse_content(self, resp_text: str) -> str:
        return f"custom:{resp_text.strip()}"

    def extract_cache_key_parts(
        self,
        payload: dict[str, Any],
        max_recent_turns: int = 2,
    ) -> tuple[str, str]:
        return "custom-user", "custom-system"


@pytest.fixture
def isolated_registry() -> Iterator[None]:
    snapshot = dict(registry._REGISTRY)
    try:
        yield
    finally:
        registry._REGISTRY.clear()
        registry._REGISTRY.update(snapshot)


@pytest.mark.parametrize(
    ("url", "payload", "expected_name", "expected_cls"),
    [
        ("https://api.anthropic.com/v1/messages", None, "anthropic", AnthropicProvider),
        ("https://api.openai.com/v1/chat/completions", None, "openai", OpenAIProvider),
        (
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent",
            None,
            "gemini",
            GeminiProvider,
        ),
        ("https://example.invalid/v1/other", None, "unknown", OpenAIProvider),
        (
            "https://proxy.internal/v1/custom",
            {"system": "Be concise", "messages": [{"role": "user", "content": "hi"}]},
            "anthropic",
            AnthropicProvider,
        ),
        (
            "https://proxy.internal/v1/custom",
            {"model": "claude-3-5-sonnet-20241022", "messages": [{"role": "user", "content": "hi"}]},
            "anthropic",
            AnthropicProvider,
        ),
        (
            "https://proxy.internal/v1/custom",
            {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]},
            "gemini",
            GeminiProvider,
        ),
        (
            "https://proxy.internal/v1/custom",
            {"messages": [{"role": "user", "content": "hi"}]},
            "openai",
            OpenAIProvider,
        ),
    ],
)
def test_single_path_detection_parity(
    url: str,
    payload: dict[str, Any] | None,
    expected_name: str,
    expected_cls: type[Any],
) -> None:
    interceptor = MITMProxyInterceptor(enable_caching=False)
    registry_name = detect_provider_name(url, payload)
    addon_name = interceptor.detect_provider(url, payload)
    resolved = resolve_provider(url, payload)

    assert registry_name == expected_name
    assert addon_name == registry_name
    assert isinstance(resolved, expected_cls)
    assert isinstance(resolved, ProviderFormat)


def test_custom_provider_registration_seam(isolated_registry: None) -> None:
    custom = CustomSeamProvider()
    assert isinstance(custom, ProviderFormat)
    assert ProviderFormat not in CustomSeamProvider.__mro__

    register_provider("custom_seam", custom)
    interceptor = MITMProxyInterceptor(enable_caching=False)

    assert "custom_seam" in sse_module.KNOWN_PROVIDERS
    assert detect_provider_name("https://api.custom-seam.example/v1/infer") == "custom_seam"
    assert interceptor.detect_provider("https://api.custom-seam.example/v1/infer") == "custom_seam"

    payload_with_messages = {
        "custom_seam_marker": True,
        "messages": [{"role": "user", "content": "hello"}],
    }
    assert detect_provider_name("https://proxy.internal/infer", payload_with_messages) == "custom_seam"
    assert interceptor.detect_provider("https://proxy.internal/infer", payload_with_messages) == "custom_seam"
    assert resolve_provider("https://proxy.internal/infer", payload_with_messages) is custom

    assert extract_sse_content("data: ok\n", "custom_seam") == "custom:data: ok"
    assert extract_sse_content("data: ok\n", "mistral") == ""


def test_routing_is_local_target_delegates_to_registered_provider(isolated_registry: None) -> None:
    custom = CustomSeamProvider()
    register_provider("custom_seam", custom)

    cloud_flow = SimpleNamespace(
        request=SimpleNamespace(pretty_host="api.custom-seam.example", host="api.custom-seam.example", pretty_url=""),
        provider="custom_seam",
    )
    local_flow = SimpleNamespace(
        request=SimpleNamespace(pretty_host="custom.lan.internal", host="custom.lan.internal", pretty_url=""),
        provider="custom_seam",
    )

    assert is_local_target(cloud_flow) is False
    assert is_local_target(local_flow) is True


def test_parsers_and_providers_have_no_cyclic_edges() -> None:
    observed_cycles = find_cyclic_edges(collect_subpackage_edges(PACKAGE_ROOT))
    assert ("parsers", "providers") not in observed_cycles
    assert ("providers", "parsers") not in observed_cycles


def _imported_module_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _function_scoped_provider_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for child in ast.walk(node):
            is_from_providers = isinstance(child, ast.ImportFrom) and bool(child.module) and "providers" in child.module
            is_import_providers = isinstance(child, ast.Import) and any("providers" in a.name for a in child.names)
            if is_from_providers or is_import_providers:
                violations.append(f"{path.name}:{node.name}")
    return violations


def test_provider_and_parser_import_hygiene() -> None:
    for provider_file in sorted(PROVIDERS_DIR.glob("*.py")):
        imported = _imported_module_names(provider_file)
        assert not any(
            mod == "holon_coherence.parsers" or mod.startswith("holon_coherence.parsers.") for mod in imported
        )

    for sibling in (PROVIDERS_DIR / "openai.py", PROVIDERS_DIR / "gemini.py"):
        imported = _imported_module_names(sibling)
        assert not any(mod.startswith("holon_coherence.providers.anthropic") for mod in imported)

    for parser_file in (PARSERS_DIR / "sse.py", PARSERS_DIR / "tokens.py"):
        assert _function_scoped_provider_imports(parser_file) == []


def test_providers_base_has_no_closed_literal() -> None:
    base_tree = ast.parse((PROVIDERS_DIR / "base.py").read_text(encoding="utf-8"))
    for node in ast.walk(base_tree):
        if isinstance(node, ast.Name) and node.id == "Literal":
            pytest.fail("Closed Literal must not be used in providers/base.py")
        if isinstance(node, ast.ImportFrom) and any(alias.name == "Literal" for alias in node.names):
            pytest.fail("Literal must not be imported in providers/base.py")
