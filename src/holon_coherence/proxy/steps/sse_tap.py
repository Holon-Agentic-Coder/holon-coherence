from __future__ import annotations

import codecs
import time
from typing import Any

from holon_coherence.proxy.steps.base import logger
from holon_coherence.proxy.translation.gemini_openai import translate_openai_sse_chunk_to_gemini

__all__ = ["_MAX_SSE_BUFFER_BYTES", "install_sse_tap", "response_content_type"]

_MAX_SSE_BUFFER_BYTES = 50 * 1024 * 1024


def response_content_type(response: Any) -> str:
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


def _record_sse_chunk(flow: Any, chunk: bytes) -> None:
    flow.sse_bytes = getattr(flow, "sse_bytes", 0) + len(chunk)
    if flow.sse_bytes <= _MAX_SSE_BUFFER_BYTES:
        flow.sse_chunks.append(chunk)


def _translate_bridged_text(flow: Any, text: str, *, flush: bool = False) -> bytes:
    if not text and not flush:
        return b""
    try:
        translated = translate_openai_sse_chunk_to_gemini(
            text,
            stream_state=getattr(flow, "_sse_stream_state", None),
            flush=flush,
        )
        return translated.encode("utf-8")
    except Exception as exc:
        logger.debug("Failed translating bridged Gemini SSE chunk: %s", exc)
        return text.encode("utf-8")


def install_sse_tap(flow: Any, response: Any) -> None:
    flow.sse_chunks = []
    flow.sse_bytes = 0
    flow._sse_stream_state = {}
    utf8_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    existing_stream = getattr(response, "stream", None)

    def sse_stream_wrapper(chunk: bytes) -> bytes:
        if chunk:
            if getattr(flow, "first_chunk_time", None) is None:
                flow.first_chunk_time = time.perf_counter()
            flow.last_chunk_time = time.perf_counter()
            if getattr(flow, "is_gemini_bridged", False):
                decoded = utf8_decoder.decode(chunk, final=False)
                chunk = _translate_bridged_text(flow, decoded)
                if chunk or "\n" in decoded:
                    _record_sse_chunk(flow, chunk)
            else:
                _record_sse_chunk(flow, chunk)
        elif getattr(flow, "is_gemini_bridged", False):
            flushed_text = utf8_decoder.decode(b"", final=True)
            chunk = _translate_bridged_text(flow, flushed_text, flush=True)
            if chunk:
                _record_sse_chunk(flow, chunk)
        if callable(existing_stream):
            return existing_stream(chunk)
        return chunk

    response.stream = sse_stream_wrapper
