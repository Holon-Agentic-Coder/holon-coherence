"""Tests for SSE stream parsing in mitm_addon (Bean 0074).

These cover the aggregation the token-reduction accounting is built on: content reassembled from
stream fragments, for each supported provider, including the cases where a naive parser silently
loses text. Every test uses wire-shaped SSE text rather than mocks, because the behaviour under
test is exactly how byte lines are turned back into content.
"""

from __future__ import annotations

import json

import pytest

from holon_coherence.mitm_addon import (
    TokenCounts,
    estimate_chars,
    extract_detailed_token_counts,
    extract_sse_cache_read_tokens,
    extract_sse_content,
    extract_sse_token_counts,
    safe_int,
)


def _sse(*payloads: dict | str, prefix: str = "data: ") -> str:
    """Render SSE lines; `prefix='data:'` exercises the no-space variant providers really emit."""
    rendered = []
    for payload in payloads:
        body = payload if isinstance(payload, str) else json.dumps(payload)
        rendered.append(f"{prefix}{body}")
    return "\n".join(rendered)


class TestSSEContentAnthropic:
    def test_text_deltas_are_reassembled_in_order(self) -> None:
        stream = _sse(
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Refac"}},
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "tor"}},
            {"type": "message_stop"},
        )
        assert extract_sse_content(stream, "anthropic") == "Refactor"

    def test_thinking_deltas_are_kept_not_dropped(self) -> None:
        stream = _sse(
            {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "checking "}},
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "answer"}},
        )
        assert extract_sse_content(stream, "anthropic") == "checking answer"

    def test_tool_use_block_is_rendered_with_call_parentheses(self) -> None:
        start = {"type": "content_block_start", "content_block": {"type": "tool_use", "name": "read_file"}}
        first = {"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": '{"path":'}}
        second = {"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": '"a.py"}'}}
        stop = {"type": "content_block_stop"}

        stream = _sse(start, first, second, stop)

        assert extract_sse_content(stream, "anthropic") == 'read_file({"path":"a.py"})'

    def test_unclosed_tool_block_is_still_closed(self) -> None:
        """A stream cut off mid-call must not emit an unbalanced call rendering."""
        stream = _sse(
            {"type": "content_block_start", "content_block": {"type": "tool_use", "name": "grep"}},
            {"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": "x"}},
        )
        assert extract_sse_content(stream, "anthropic") == "grep(x)"


class TestSSEContentOpenAI:
    def test_content_deltas_are_reassembled(self) -> None:
        stream = _sse(
            {"choices": [{"delta": {"content": "Hel"}}]},
            {"choices": [{"delta": {"content": "lo"}}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        )
        assert extract_sse_content(stream, "openai") == "Hello"

    def test_fragmented_tool_call_arguments_are_reassembled_once(self) -> None:
        stream = _sse(
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "shell", "arguments": ""}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '{"cmd":'}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"ls"}'}}]}}]},
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
        )
        assert extract_sse_content(stream, "openai") == 'shell({"cmd":"ls"})'

    def test_tool_call_followed_by_text_closes_the_call(self) -> None:
        stream = _sse(
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "shell", "arguments": "x"}}]}}]},
            {"choices": [{"delta": {"content": " done"}}]},
        )
        assert extract_sse_content(stream, "openai") == "shell(x) done"

    def test_reasoning_content_is_not_mistaken_for_content(self) -> None:
        """Only `content` is completion text; reasoning deltas must not double-count into it."""
        stream = _sse({"choices": [{"delta": {"reasoning_content": "hidden chain of thought"}}]})
        assert extract_sse_content(stream, "openai") == ""


class TestSSEContentGemini:
    def test_candidate_parts_are_reassembled(self) -> None:
        stream = _sse(
            {"candidates": [{"content": {"parts": [{"text": "Pri"}]}}]},
            {"candidates": [{"content": {"parts": [{"text": "mary"}]}}]},
        )
        assert extract_sse_content(stream, "gemini") == "Pri" + "mary"

    def test_function_call_is_serialised(self) -> None:
        stream = _sse(
            {"candidates": [{"content": {"parts": [{"functionCall": {"name": "lookup", "args": {"q": 1}}}]}}]}
        )
        assert json.loads(extract_sse_content(stream, "gemini")) == {"name": "lookup", "args": {"q": 1}}


class TestSSEContentRobustness:
    @pytest.mark.parametrize("prefix", ["data: ", "data:", "data:  "])
    def test_space_variants_after_the_colon_are_all_parsed(self, prefix: str) -> None:
        stream = _sse({"choices": [{"delta": {"content": "ok"}}]}, prefix=prefix)
        assert extract_sse_content(stream, "openai") == "ok"

    def test_done_event_and_blank_lines_are_ignored(self) -> None:
        stream = _sse({"choices": [{"delta": {"content": "hi"}}]}, prefix="data: ") + "\n\ndata: [DONE]\n"
        assert extract_sse_content(stream, "openai") == "hi"

    def test_malformed_json_line_does_not_abort_the_stream(self) -> None:
        """One corrupt frame must not discard the content around it."""
        stream = "\n".join(
            [
                "data: " + json.dumps({"choices": [{"delta": {"content": "before"}}]}),
                "data: {this is not json",
                "data: " + json.dumps({"choices": [{"delta": {"content": "after"}}]}),
            ]
        )
        assert extract_sse_content(stream, "openai") == "beforeafter"

    def test_non_object_json_is_ignored(self) -> None:
        stream = "\n".join(["data: [1,2,3]", "data: " + json.dumps({"choices": [{"delta": {"content": "x"}}]})])
        assert extract_sse_content(stream, "openai") == "x"

    def test_non_sse_lines_are_skipped(self) -> None:
        stream = "event: message\ndata: " + json.dumps({"delta": {"text": "hi"}}) + "\n\n"
        assert extract_sse_content(stream, "anthropic") == "hi"

    def test_empty_stream_returns_empty_string(self) -> None:
        assert extract_sse_content("", "anthropic") == ""

    def test_unknown_provider_yields_empty_content(self) -> None:
        stream = _sse({"choices": [{"delta": {"content": "hi"}}]})
        assert extract_sse_content(stream, "mistral") == ""

    def test_truncated_final_frame_loses_only_that_frame(self) -> None:
        """The bean's zero-truncation requirement, at the frame boundary."""
        full = _sse(
            {"choices": [{"delta": {"content": "alpha"}}]},
            {"choices": [{"delta": {"content": "beta"}}]},
        )
        assert extract_sse_content(full, "openai") == "alphabeta"
        truncated = full[: full.rindex("data: ")] + '{"choices": [{"delta": {"content'
        assert extract_sse_content(truncated, "openai") == "alpha"


class TestTokenCountsAndHelpers:
    def test_token_counts_is_a_plain_three_tuple(self) -> None:
        counts = TokenCounts(10, 20, 30, cache_creation_tokens=5, reasoning_tokens=7)
        assert counts == (10, 20, 30)
        assert tuple(counts) == (10, 20, 30)
        assert counts.cache_creation_tokens == 5 and counts.reasoning_tokens == 7

    def test_token_counts_defaults_optional_fields(self) -> None:
        counts = TokenCounts(1, 2, 3)
        assert counts.cache_creation_tokens == 0 and counts.reasoning_tokens == 0

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(None, 0), ("", 0), ("12", 12), ("bad", 0), (7.9, 7), ([], 0)],
    )
    def test_safe_int_never_raises(self, value: object, expected: int) -> None:
        assert safe_int(value, 0) == expected


class TestSSETokenCountsAnthropic:
    def test_usage_from_message_start_and_delta_is_reported_exactly(self) -> None:
        stream = _sse(
            {
                "type": "message_start",
                "message": {
                    "usage": {
                        "input_tokens": 100,
                        "cache_read_input_tokens": 40,
                        "cache_creation_input_tokens": 10,
                    }
                },
            },
            {"type": "content_block_delta", "delta": {"text": "abcd" * 10}},
            {"type": "message_delta", "usage": {"output_tokens": 7, "thinking_tokens": 3}},
        )

        counts = extract_sse_token_counts(stream, {}, "anthropic")

        # input_tokens is the documented sum of fresh + cache-read + cache-creation tokens
        assert tuple(counts) == (150, 7, 40)
        assert counts.cache_creation_tokens == 10
        assert counts.reasoning_tokens == 3

    def test_missing_usage_falls_back_to_the_chars_over_four_heuristic(self) -> None:
        """No usage frame must still produce a number, and it must be the documented heuristic."""
        req = {"messages": [{"role": "user", "content": "hello there"}]}
        stream = _sse(
            {"type": "content_block_delta", "delta": {"text": "abcd" * 10}},
            {"type": "content_block_delta", "delta": {"thinking": "thi" * 40}},
        )

        counts = extract_sse_token_counts(stream, req, "anthropic")

        # thinking is added to the output estimate as well as being reported as reasoning tokens, so
        # the output heuristic covers text + thinking rather than text alone.
        assert counts.output_tokens == (len("abcd" * 10) + len("thi" * 40)) // 4
        assert counts.input_tokens == max(1, estimate_chars(req) // 4)
        assert counts.reasoning_tokens == len("thi" * 40) // 4

    def test_partial_json_counts_as_output_content(self) -> None:
        stream = _sse({"type": "content_block_delta", "delta": {"partial_json": '{"a": 1}'}})
        counts = extract_sse_token_counts(stream, {}, "anthropic")
        assert counts.output_tokens == len('{"a": 1}') // 4

    def test_extract_sse_cache_read_tokens_delegates(self) -> None:
        stream = _sse(
            {"type": "message_start", "message": {"usage": {"input_tokens": 1, "cache_read_input_tokens": 40}}},
        )
        assert extract_sse_cache_read_tokens(stream) == 40
        assert extract_sse_cache_read_tokens("") == 0


class TestSSETokenCountsOpenAI:
    def test_usage_frame_reports_input_output_cache_and_reasoning(self) -> None:
        stream = _sse(
            {"choices": [{"delta": {"content": "Hel"}}]},
            {
                "choices": [{"delta": {"content": "lo"}}],
                "usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 30,
                    "prompt_tokens_details": {"cached_tokens": 15},
                    "completion_tokens_details": {"reasoning_tokens": 9},
                },
            },
            "[DONE]",
        )

        counts = extract_sse_token_counts(stream, {}, "openai")

        assert tuple(counts) == (120, 30, 15)
        assert counts.reasoning_tokens == 9

    def test_usage_arriving_only_in_the_final_frame_is_still_counted(self) -> None:
        """Streaming puts usage last; a parser that stops at the first frame reports zero."""
        frames = [{"choices": [{"delta": {"content": f"tok{i} "}}]} for i in range(5)]
        frames.append(
            {
                "choices": [],
                "usage": {"prompt_tokens": 77, "completion_tokens": 21, "prompt_tokens_details": {"cached_tokens": 7}},
            }
        )

        counts = extract_sse_token_counts(_sse(*frames), {}, "openai")

        assert tuple(counts) == (77, 21, 7)

    def test_flat_cached_tokens_is_used_when_there_are_no_details(self) -> None:
        stream = _sse({"usage": {"prompt_tokens": 50, "completion_tokens": 5, "cached_tokens": 12}})
        assert extract_sse_token_counts(stream, {}, "openai") == (50, 5, 12)

    def test_missing_usage_estimates_from_content_and_request(self) -> None:
        req = {"messages": [{"role": "user", "content": "x" * 40}]}
        stream = _sse({"choices": [{"delta": {"content": "abcd" * 8}}]})

        counts = extract_sse_token_counts(stream, req, "openai")

        assert counts.output_tokens == len("abcd" * 8) // 4
        assert counts.input_tokens == max(1, estimate_chars(req) // 4)

    def test_tool_call_name_and_arguments_count_as_output(self) -> None:
        stream = _sse(
            {
                "choices": [
                    {"delta": {"tool_calls": [{"index": 0, "function": {"name": "shell", "arguments": "ls -al"}}]}}
                ]
            }
        )
        counts = extract_sse_token_counts(stream, {}, "openai")
        assert counts.output_tokens == (len("shell") + len("ls -al")) // 4


class TestSSETokenCountsGemini:
    def test_usage_metadata_reports_all_four_counters(self) -> None:
        stream = _sse(
            {
                "candidates": [{"content": {"parts": [{"text": "hi"}]}}],
                "usageMetadata": {
                    "promptTokenCount": 500,
                    "candidatesTokenCount": 120,
                    "cachedContentTokenCount": 88,
                    "reasoningTokenCount": 33,
                },
            }
        )

        counts = extract_sse_token_counts(stream, {}, "gemini")

        assert tuple(counts) == (500, 120, 88)
        assert counts.reasoning_tokens == 33

    def test_usage_key_alias_is_accepted(self) -> None:
        stream = _sse({"usage": {"promptTokenCount": 11, "candidatesTokenCount": 2}})
        assert tuple(extract_sse_token_counts(stream, {}, "gemini")) == (11, 2, 0)

    def test_function_call_arguments_count_toward_output_estimate(self) -> None:
        stream = _sse(
            {"candidates": [{"content": {"parts": [{"functionCall": {"name": "fetch", "args": {"u": "x"}}}]}}]}
        )
        counts = extract_sse_token_counts(stream, {}, "gemini")
        assert counts.output_tokens == (len("fetch") + len(json.dumps({"u": "x"}))) // 4


class TestDetailedCounts:
    def test_string_response_routes_through_the_sse_parser(self) -> None:
        stream = _sse(
            {"usage": {"prompt_tokens": 3, "completion_tokens": 4, "prompt_tokens_details": {"cached_tokens": 2}}}
        )

        detailed = extract_detailed_token_counts({}, stream, "openai")

        assert detailed == {
            "input_tokens": 3,
            "output_tokens": 4,
            "cache_read_input_tokens": 2,
            "cache_creation_input_tokens": 0,
            "reasoning_tokens": 0,
        }

    def test_anthropic_stream_carries_cache_creation_through_the_mapping(self) -> None:
        stream = _sse(
            {"type": "message_start", "message": {"usage": {"input_tokens": 1, "cache_creation_input_tokens": 9}}},
        )
        detailed = extract_detailed_token_counts({}, stream, "anthropic")
        assert detailed["cache_creation_input_tokens"] == 9
