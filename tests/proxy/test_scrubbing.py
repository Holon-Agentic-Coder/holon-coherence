"""Unit tests for secret scrubbing module."""

from __future__ import annotations

from holon_coherence.proxy.scrubbing import scrub_headers, scrub_payload, scrub_string


def test_scrub_string_url_params() -> None:
    url = "https://api.openai.com/v1/chat?key=AIzaSyA1234567890123456789012345678901&other=val"
    cleaned = scrub_string(url)
    assert "[REDACTED]" in cleaned
    assert "AIzaSy" not in cleaned
    assert "other=val" in cleaned


def test_scrub_string_api_keys() -> None:
    anthropic_key = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz123456789"
    assert scrub_string(anthropic_key) == "[REDACTED_SECRET]"

    openai_key = "sk-proj-abcdefghijklmnopqrstuvwxyz123456789"
    assert scrub_string(openai_key) == "[REDACTED_SECRET]"


def test_scrub_headers_case_insensitive() -> None:
    headers = {
        "Authorization": "Bearer sensitive_token_123",
        "X-API-KEY": "secret_key_abc",
        "Content-Type": "application/json",
    }
    scrubbed = scrub_headers(headers)
    assert scrubbed["authorization"] == "[REDACTED]"
    assert scrubbed["x-api-key"] == "[REDACTED]"
    assert scrubbed["content-type"] == "application/json"


def test_scrub_payload_nested() -> None:
    data = {
        "api_key": "supersecret",
        "nested": {
            "token": "tok123",
            "safe": "hello",
            "list": ["sk-ant-abcdefghijklmnopqrstuvwxyz12345", "world"],
        },
    }
    scrubbed = scrub_payload(data)
    assert scrubbed["api_key"] == "[REDACTED]"
    assert scrubbed["nested"]["token"] == "[REDACTED]"
    assert scrubbed["nested"]["safe"] == "hello"
    assert scrubbed["nested"]["list"][0] == "[REDACTED_SECRET]"
    assert scrubbed["nested"]["list"][1] == "world"
