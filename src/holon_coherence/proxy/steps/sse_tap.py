"""Server-sent-event tap installed by the ``responseheaders`` hook.

The tap timestamps the first and last chunk, translates bridged Gemini streams on the fly and buffers
chunks (up to ``_MAX_SSE_BUFFER_BYTES``) for the response hook, while passing every chunk through to
any stream callable that was already installed.
"""

from __future__ import annotations

import time
from typing import Any

from holon_coherence.proxy.steps.base import logger
from holon_coherence.proxy.translation.gemini_openai import translate_openai_sse_chunk_to_gemini

__all__ = ["_MAX_SSE_BUFFER_BYTES", "install_sse_tap", "response_content_type"]

_MAX_SSE_BUFFER_BYTES = 50 * 1024 * 1024


def response_content_type(response: Any) -> str:
    """The response Content-Type, or ``""`` when absent."""
    headers = getattr(response, "headers", None)
    content_type = ""
    if headers:
        if hasattr(headers, "get"):
            content_type = headers.get("Content-Type") or headers.get("content-type") or ""
        elif isinstance(headers, dict):
            for k, v in headers.items():
                if k.lower() == "content-type":
                    content_type = v
                    break
    return content_type


def install_sse_tap(flow: Any, response: Any) -> None:
    """Wrap ``response.stream`` so streamed chunks are timed, translated and buffered."""
    flow.sse_chunks = []
    flow.sse_bytes = 0
    flow._sse_stream_state = {}
    existing_stream = getattr(response, "stream", None)

    def sse_stream_wrapper(chunk: bytes) -> bytes:
        if chunk:
            if getattr(flow, "first_chunk_time", None) is None:
                flow.first_chunk_time = time.perf_counter()
            flow.last_chunk_time = time.perf_counter()
            if getattr(flow, "is_gemini_bridged", False):
                try:
                    chunk_text = chunk.decode("utf-8", errors="ignore")
                    translated = translate_openai_sse_chunk_to_gemini(
                        chunk_text,
                        stream_state=getattr(flow, "_sse_stream_state", None),
                    )
                    chunk = translated.encode("utf-8")
                    flow._sse_stream_state = getattr(flow, "_sse_stream_state", None)
                except Exception as exc:
                    logger.debug("Failed translating bridged Gemini SSE chunk: %s", exc)
            flow.sse_bytes = getattr(flow, "sse_bytes", 0) + len(chunk)
            if flow.sse_bytes <= _MAX_SSE_BUFFER_BYTES:
                flow.sse_chunks.append(chunk)
        if callable(existing_stream):
            return existing_stream(chunk)
        return chunk

    response.stream = sse_stream_wrapper
