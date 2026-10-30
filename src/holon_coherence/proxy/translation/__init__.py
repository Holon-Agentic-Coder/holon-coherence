"""Protocol translation adapters (Gemini <-> OpenAI)."""

from __future__ import annotations

from holon_coherence.proxy.translation.gemini_openai import (
    translate_gemini_to_openai_request,
    translate_openai_sse_chunk_to_gemini,
    translate_openai_to_gemini_response,
)

__all__ = [
    "translate_gemini_to_openai_request",
    "translate_openai_sse_chunk_to_gemini",
    "translate_openai_to_gemini_response",
]
