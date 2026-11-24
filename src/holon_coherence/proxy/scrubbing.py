from __future__ import annotations

import re
from typing import Any

__all__ = [
    "_BODY_SECRET_PATTERNS",
    "_SECRET_DICT_KEY_PATTERN",
    "_SECRET_HEADER_NAMES",
    "_URL_QUERY_SECRET_PATTERN",
    "scrub_headers",
    "scrub_payload",
    "scrub_string",
]

REDACTED_VALUE = "[REDACTED]"
REDACTED_SECRET_VALUE = "[REDACTED_SECRET]"

_SECRET_HEADER_NAMES = {
    "authorization",
    "auth",
    "credential",
    "credentials",
    "x-api-key",
    "api-key",
    "x-anthropic-api-key",
    "x-goog-api-key",
    "holon-agent-key",
    "proxy-authorization",
    "x-amz-security-token",
    "cookie",
    "set-cookie",
    "x-auth-token",
    "openai-api-key",
    "x-session-token",
}

_URL_QUERY_SECRET_PATTERN = re.compile(
    r'(?i)([?&](?:key|api_key|apiKey|api-key|apikey|token|access_token|auth_token|secret)=)[^&\s"\'`<>#]+'
)

_ANTHROPIC_KEY_PATTERN = re.compile(r"\bsk-ant-[a-zA-Z0-9_\-]{20,}\b")
_OPENAI_KEY_PATTERN = re.compile(r"\bsk-(?:proj-|admin-|svcacct-)?[a-zA-Z0-9_\-]{20,}\b")
_GOOGLE_AI_KEY_PATTERN = re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b")
_GITHUB_CLASSIC_TOKEN_PATTERN = re.compile(r"\bgh[pousr]_[a-zA-Z0-9]{36}\b")
_GITHUB_FINE_GRAINED_PAT_PATTERN = re.compile(r"\bgithub_pat_[a-zA-Z0-9_]{22,}\b")
_AWS_AKIA_KEY_PATTERN = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_AWS_ASIA_KEY_PATTERN = re.compile(r"\bASIA[0-9A-Z]{16}\b")
_AWS_SECRET_ACCESS_KEY_PATTERN = re.compile(
    r'(?i)\b(?:aws_secret_access_key|aws_secret_key|secret_access_key)\s*[:=]\s*["\']?(?:[A-Za-z0-9/+=]{40})["\']?'
)
_HUGGINGFACE_TOKEN_PATTERN = re.compile(r"\bhf_[a-zA-Z0-9]{34,}\b")
_JWT_BEARER_TOKEN_PATTERN = re.compile(r"\beyJ[a-zA-Z0-9_\-]{20,}\.[a-zA-Z0-9_\-]{20,}\.[a-zA-Z0-9_\-]{20,}\b")
_PRIVATE_KEY_PEM_BLOCK_PATTERN = re.compile(
    r"-----BEGIN (?:[A-Z\s]+ )?PRIVATE KEY(?: BLOCK)?-----"
    r"[\s\S]*?-----END (?:[A-Z\s]+ )?PRIVATE KEY(?: BLOCK)?-----"
)

_BODY_SECRET_PATTERNS = [
    _ANTHROPIC_KEY_PATTERN,
    _OPENAI_KEY_PATTERN,
    _GOOGLE_AI_KEY_PATTERN,
    _GITHUB_CLASSIC_TOKEN_PATTERN,
    _GITHUB_FINE_GRAINED_PAT_PATTERN,
    _AWS_AKIA_KEY_PATTERN,
    _AWS_ASIA_KEY_PATTERN,
    _AWS_SECRET_ACCESS_KEY_PATTERN,
    _HUGGINGFACE_TOKEN_PATTERN,
    _JWT_BEARER_TOKEN_PATTERN,
    _PRIVATE_KEY_PEM_BLOCK_PATTERN,
]

_SECRET_DICT_KEY_PATTERN = re.compile(
    r"(?i)^(?:auth|authorization|credential|credentials|password|passwd|token|api[-_]?key|apikey|api[-_]?token|auth[-_]?token|access[-_]?token|refresh[-_]?token|id[-_]?token|secret[-_]?key|secret|private[-_]?key|client[-_]?secret|session[-_]?token)$"
)


def scrub_string(text: str) -> str:
    if not isinstance(text, str) or not text:
        return text
    text = _URL_QUERY_SECRET_PATTERN.sub(rf"\1{REDACTED_VALUE}", text)
    for pattern in _BODY_SECRET_PATTERNS:
        text = pattern.sub(REDACTED_SECRET_VALUE, text)
    return text


def scrub_headers(headers: Any) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    if hasattr(headers, "items"):
        items = headers.items()
    elif isinstance(headers, (list, tuple)):
        items = headers
    elif isinstance(headers, dict):
        items = headers.items()
    else:
        return {}

    for k, v in items:
        k_str = str(k).lower()
        if (
            k_str in _SECRET_HEADER_NAMES
            or _SECRET_DICT_KEY_PATTERN.match(k_str)
            or "token" in k_str
            or "secret" in k_str
        ):
            cleaned[k_str] = REDACTED_VALUE
        else:
            cleaned[k_str] = scrub_string(str(v))
    return cleaned


def scrub_payload(data: Any, max_depth: int = 50) -> Any:
    if max_depth <= 0:
        return data
    if isinstance(data, dict):
        cleaned: dict[str, Any] = {}
        for k, v in data.items():
            k_str = str(k).lower()
            if _SECRET_DICT_KEY_PATTERN.match(k_str):
                cleaned[k] = REDACTED_VALUE
            else:
                cleaned[k] = scrub_payload(v, max_depth=max_depth - 1)
        return cleaned
    elif isinstance(data, (list, tuple)):
        scrubbed_seq = [scrub_payload(elem, max_depth=max_depth - 1) for elem in data]
        return tuple(scrubbed_seq) if isinstance(data, tuple) else scrubbed_seq
    elif isinstance(data, str):
        return scrub_string(data)
    else:
        return data
