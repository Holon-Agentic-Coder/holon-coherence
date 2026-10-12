"""Tests for SSE stream parsing in mitm_addon (Bean 0074).

These cover the aggregation the token-reduction accounting is built on: content reassembled from
stream fragments, for each supported provider, including the cases where a naive parser silently
loses text. Every test uses wire-shaped SSE text rather than mocks, because the behaviour under
test is exactly how byte lines are turned back into content.
"""

from __future__ import annotations

import json
import sqlite3
import time

import pytest

from holon_coherence.mitm_addon import (
    _MAX_SSE_BUFFER_BYTES,
    MitmproxyAddon,
    MITMProxyInterceptor,
    TokenCounts,
    _get_wire_log_executor,
    _write_transaction_sync,
    derive_turn_id,
    dump_wire_transaction,
    estimate_chars,
    extract_detailed_token_counts,
    extract_sse_cache_read_tokens,
    extract_sse_content,
    extract_sse_token_counts,
    extract_token_counts,
    find_nested_key,
    flush_wire_logs,
    get_header_case_insensitive,
    is_passive_monitoring,
    is_wire_logging_enabled,
    log_telemetry,
    safe_int,
    scrub_headers,
    scrub_payload,
    scrub_string,
    shutdown_wire_logs,
)
from holon_coherence.payload_cleaner import CleaningResult


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


class TestScrubbing:
    """Credential redaction for wire logs, using real key shapes rather than the word 'secret'."""

    @pytest.mark.parametrize(
        "secret",
        [
            "sk-ant-" + "A" * 30,  # Anthropic
            "sk-" + "a" * 24,  # OpenAI
            "sk-proj-" + "a" * 24,  # OpenAI project key
            "AIza" + "a" * 35,  # Google API key
            "ghp_" + "a" * 36,  # GitHub PAT
            "github_pat_" + "a" * 24,  # GitHub fine-grained PAT
            "AKIA" + "ABCDEFGHIJKLMNOP",  # AWS access key id
            "ASIA" + "ABCDEFGHIJKLMNOP",  # AWS temporary access key id
            "hf_" + "a" * 34,  # Hugging Face
            "eyJ" + "a" * 22 + "." + "b" * 22 + "." + "c" * 22,  # JWT
            "-----BEGIN PRIVATE KEY-----\nMIIBVw\n-----END PRIVATE KEY-----",  # PEM
        ],
    )
    def test_recognised_credential_shapes_are_redacted(self, secret: str) -> None:
        assert secret not in scrub_string(f"authorization: Bearer {secret}")
        assert "[REDACTED_SECRET]" in scrub_string(f"authorization: Bearer {secret}")

    def test_url_query_credentials_are_scrubbed_but_other_parameters_survive(self) -> None:
        out = scrub_string("https://example.com/v1?api_key=SUPERSECRETVALUE&model=gemini-3")
        assert "SUPERSECRETVALUE" not in out
        assert "[REDACTED]" in out
        assert "model=gemini-3" in out

    @pytest.mark.parametrize(
        "param", ["key", "api_key", "apiKey", "api-key", "apikey", "token", "access_token", "secret"]
    )
    def test_every_documented_query_parameter_name_is_covered(self, param: str) -> None:
        assert "TOPSECRET" not in scrub_string(f"https://host/x?{param}=TOPSECRET")

    def test_aws_secret_assignment_form_is_scrubbed(self) -> None:
        line = 'aws_secret_access_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"'
        assert "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY" not in scrub_string(line)

    def test_ordinary_text_is_left_alone(self) -> None:
        text = "refactor the parser in src/app.py; 4 items remaining"
        assert scrub_string(text) == text

    @pytest.mark.parametrize("value", ["", None, 42])
    def test_non_string_and_empty_pass_through(self, value: object) -> None:
        assert scrub_string(value) == value


class TestScrubHeaders:
    @pytest.mark.parametrize(
        "name",
        ["authorization", "Authorization", "x-api-key", "api-key", "x-auth-token", "set-cookie", "proxy-authorization"],
    )
    def test_sensitive_header_names_are_fully_replaced(self, name: str) -> None:
        cleaned = scrub_headers({name: "Bearer sk-" + "a" * 24})
        assert cleaned[name.lower()] == "[REDACTED]"

    def test_unknown_header_name_still_scrubs_a_secret_value(self) -> None:
        """The closed name list is not the only defence: values are scanned regardless of key."""
        cleaned = scrub_headers({"x-upstream-assertion": "Bearer sk-" + "b" * 24})
        assert "bbbbb" not in cleaned["x-upstream-assertion"]

    def test_header_names_are_normalised_to_lowercase(self) -> None:
        cleaned = scrub_headers({"Content-Type": "application/json"})
        assert list(cleaned) == ["content-type"]

    def test_list_and_tuple_header_forms_are_accepted(self) -> None:
        pairs = [("Authorization", "Bearer zzz"), ("accept", "application/json")]
        assert scrub_headers(pairs)["authorization"] == "[REDACTED]"
        assert scrub_headers(tuple(pairs))["accept"] == "application/json"

    def test_header_objects_with_items_are_accepted(self) -> None:
        class FakeHeaders:
            def items(self):
                return [("X-Session-Token", "abc"), ("accept", "text/plain")]

        cleaned = scrub_headers(FakeHeaders())
        assert cleaned["x-session-token"] == "[REDACTED]"
        assert cleaned["accept"] == "text/plain"

    def test_unrecognised_shape_yields_empty_dict(self) -> None:
        assert scrub_headers(None) == {}
        assert scrub_headers(42) == {}


def _estimate_tokens(payload: object) -> int:
    """Mirror the documented chars//4 heuristic, including the zero-content case."""
    chars = estimate_chars(payload)
    return max(1, chars // 4) if chars > 0 else 0


class TestNonStreamingTokenCounts:
    """`extract_token_counts` for ordinary JSON responses, where the reduction ratio is reported from."""

    def test_string_response_is_routed_to_the_stream_parser(self) -> None:
        stream = _sse({"usage": {"prompt_tokens": 4, "completion_tokens": 6}})
        assert tuple(extract_token_counts({}, stream, "openai")) == (4, 6, 0)

    def test_anthropic_prompt_caching_sums_into_input_tokens(self) -> None:
        resp = {
            "usage": {
                "input_tokens": 200,
                "cache_read_input_tokens": 120,
                "cache_creation_input_tokens": 20,
                "output_tokens": 35,
            }
        }

        counts = extract_token_counts({}, resp, "anthropic")

        assert tuple(counts) == (340, 35, 120)
        assert counts.cache_creation_tokens == 20

    def test_anthropic_reasoning_falls_back_to_thinking_tokens(self) -> None:
        resp = {"usage": {"input_tokens": 1, "output_tokens": 2, "thinking_tokens": 9}}
        assert extract_token_counts({}, resp, "anthropic").reasoning_tokens == 9

    def test_openai_reads_cached_and_reasoning_from_details(self) -> None:
        resp = {
            "usage": {
                "prompt_tokens": 90,
                "completion_tokens": 11,
                "prompt_tokens_details": {"cached_tokens": 60},
                "completion_tokens_details": {"reasoning_tokens": 4},
            }
        }
        counts = extract_token_counts({}, resp, "openai")
        assert tuple(counts) == (90, 11, 60)
        assert counts.reasoning_tokens == 4

    def test_openai_flat_cached_tokens_is_the_fallback(self) -> None:
        resp = {"usage": {"prompt_tokens": 30, "completion_tokens": 3, "cached_tokens": 10}}
        assert extract_token_counts({}, resp, "openai") == (30, 3, 10)

    def test_gemini_accepts_usage_metadata_and_the_usage_alias(self) -> None:
        with_meta = {"usageMetadata": {"promptTokenCount": 60, "candidatesTokenCount": 7, "cachedContentTokenCount": 5}}
        with_alias = {"usage": {"promptTokenCount": 60, "candidatesTokenCount": 7, "reasoningTokenCount": 2}}

        assert tuple(extract_token_counts({}, with_meta, "gemini")) == (60, 7, 5)
        assert extract_token_counts({}, with_alias, "gemini").reasoning_tokens == 2

    def test_incomplete_usage_block_falls_back_instead_of_trusting_partial_data(self) -> None:
        """Usage missing one required key is treated as no usage at all."""
        req = {"messages": [{"role": "user", "content": "x" * 40}]}
        resp = {"usage": {"input_tokens": 9999, "output_tokens": 9999}}

        counts = extract_token_counts(req, resp, "openai")

        assert tuple(counts) != (9999, 9999, 0)
        assert counts.input_tokens == _estimate_tokens(req)
        assert counts.output_tokens == _estimate_tokens(resp)

    def test_estimation_yields_zero_rather_than_one_for_a_content_free_payload(self) -> None:
        """The floor of 1 applies to a non-empty payload; an empty one must not invent a token.

        Reading `max(1, chars // 4)` alone suggests a bare integer response still costs a token.
        The guard is `if chars > 0 else 0`, and estimate_chars counts strings, not numbers, so a
        usage-only body estimates to zero.
        """
        counts = extract_token_counts({}, {"usage": {"input_tokens": 9999, "output_tokens": 9999}}, "openai")

        assert estimate_chars({"usage": {"input_tokens": 9999}}) == 0
        assert counts.output_tokens == 0

    def test_estimation_counts_string_content_of_a_response_without_usage(self) -> None:
        resp = {"content": [{"type": "text", "text": "y" * 80}]}

        counts = extract_token_counts({}, resp, "openai")

        assert counts.output_tokens == 80 // 4

    def test_unparseable_response_never_raises(self) -> None:
        for resp in ({"usage": "not-a-dict"}, {"usage": [1, 2]}, [], None):
            counts = extract_token_counts({}, resp, "anthropic")
            assert len(tuple(counts)) == 3

    def test_non_streaming_and_stream_paths_agree_on_the_same_numbers(self) -> None:
        """The two parsers must not disagree about one exchange depending on transport."""
        req = {}
        json_resp = {
            "usage": {"prompt_tokens": 55, "completion_tokens": 17, "prompt_tokens_details": {"cached_tokens": 5}}
        }
        stream = _sse(
            {
                "usage": {
                    "prompt_tokens": 55,
                    "completion_tokens": 17,
                    "prompt_tokens_details": {"cached_tokens": 5},
                }
            }
        )

        assert tuple(extract_token_counts(req, json_resp, "openai")) == tuple(
            extract_token_counts(req, stream, "openai")
        )


class _FakeServer:
    def __init__(self, address: tuple[str, int] | None) -> None:
        self.address = address
        self.error: str | None = None


class _FakeHookData:
    def __init__(self, address: tuple[str, int] | None) -> None:
        self.server = _FakeServer(address)


class MockRequest:
    def __init__(
        self,
        url: str = "https://api.openai.com/v1/chat/completions",
        headers: dict[str, str] | None = None,
        text: str = "",
    ) -> None:
        self.pretty_url = url
        self.headers = headers if headers is not None else {"Content-Type": "application/json"}
        self._text = text

    def get_text(self) -> str:
        return self._text

    def set_text(self, text: str) -> None:
        self._text = text


class MockResponse:
    def __init__(
        self,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        text: str = "",
        stream: object = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers if headers is not None else {"Content-Type": "application/json"}
        self._text = text
        self.stream = stream

    def get_text(self) -> str:
        return self._text

    def set_text(self, text: str) -> None:
        self._text = text

    @classmethod
    def make(cls, status_code: int = 200, content: bytes = b"", headers: dict[str, str] | None = None) -> MockResponse:
        return cls(status_code=status_code, headers=headers or {}, text=content.decode("utf-8"))


class MockFlow:
    def __init__(
        self,
        request: MockRequest | None = None,
        response: MockResponse | None = None,
    ) -> None:
        self.id = "mock-flow-1"
        self.request = request or MockRequest()
        self.response = response or MockResponse()
        self.Response = MockResponse
        self.provider = "unknown"
        self.raw_request_data = None
        self.req_data = None
        self.cleaner_result = None
        self.request_start_time = None
        self.response_headers_time = None
        self.first_chunk_time = None
        self.sse_chunks = None
        self.sse_bytes = 0
        self.is_cached = False


class TestMitmAddonLifecycle:
    def test_addon_done_shuts_down_wire_logs(self) -> None:
        addon = MitmproxyAddon()
        addon.done()

    def test_proxy_own_ports(self, monkeypatch: pytest.MonkeyPatch) -> None:
        addon = MitmproxyAddon()

        # In container mode without HOLON_PROXY_PORT
        monkeypatch.setattr("holon_coherence.mitm_addon.in_container", lambda: True)
        monkeypatch.delenv("HOLON_PROXY_PORT", raising=False)
        assert addon._proxy_own_ports() == (8080,)

        # In container mode with HOLON_PROXY_PORT
        monkeypatch.setenv("HOLON_PROXY_PORT", "8085")
        assert addon._proxy_own_ports() == (8085,)

        # In container mode with invalid port
        monkeypatch.setenv("HOLON_PROXY_PORT", "invalid")
        assert addon._proxy_own_ports() == (8080,)

        # Non-container mode with ctx options
        monkeypatch.setattr("holon_coherence.mitm_addon.in_container", lambda: False)
        monkeypatch.delenv("HOLON_PROXY_PORT", raising=False)

        class FakeOptions:
            listen_port = 9090
            web_port = 9091

        class FakeCtx:
            options = FakeOptions()

        monkeypatch.setattr("holon_coherence.mitm_addon.ctx", FakeCtx())
        assert addon._proxy_own_ports() == (9090, 9091)

    def test_resolve_gateway(self, monkeypatch: pytest.MonkeyPatch) -> None:
        addon = MitmproxyAddon()
        addon._gateway_ip = "192.168.65.254"
        assert addon._resolve_gateway() == "192.168.65.254"

        addon._gateway_ip = None
        monkeypatch.setattr("holon_coherence.mitm_addon.resolve_gateway_address", lambda: "10.0.0.1")
        assert addon._resolve_gateway() == "10.0.0.1"
        assert addon._gateway_ip == "10.0.0.1"

    def test_server_connect_not_in_container(self, monkeypatch: pytest.MonkeyPatch) -> None:
        addon = MitmproxyAddon()
        monkeypatch.setattr("holon_coherence.mitm_addon.in_container", lambda: False)
        data = _FakeHookData(("localhost", 11434))
        addon.server_connect(data)
        assert data.server.address == ("localhost", 11434)

    def test_server_connect_no_targets(self, monkeypatch: pytest.MonkeyPatch) -> None:
        addon = MitmproxyAddon()
        monkeypatch.setattr("holon_coherence.mitm_addon.in_container", lambda: True)
        monkeypatch.delenv("HOLON_HOST_LOCAL_HOSTS", raising=False)
        data = _FakeHookData(("localhost", 11434))
        addon.server_connect(data)
        assert data.server.address == ("localhost", 11434)

    def test_server_connect_in_container_rewrites(self, monkeypatch: pytest.MonkeyPatch) -> None:
        addon = MitmproxyAddon()
        monkeypatch.setattr("holon_coherence.mitm_addon.in_container", lambda: True)
        monkeypatch.setenv("HOLON_HOST_LOCAL_HOSTS", "localhost:11434")
        monkeypatch.setattr(addon, "_resolve_gateway", lambda: "192.168.65.254")

        data = _FakeHookData(("localhost", 11434))
        addon.server_connect(data)
        assert data.server.address == ("192.168.65.254", 11434)

    def test_server_connect_proxy_own_port_blocked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        addon = MitmproxyAddon()
        monkeypatch.setattr("holon_coherence.mitm_addon.in_container", lambda: True)
        monkeypatch.setenv("HOLON_HOST_LOCAL_HOSTS", "localhost:8080")
        monkeypatch.setenv("HOLON_PROXY_PORT", "8080")
        monkeypatch.setattr(addon, "_resolve_gateway", lambda: "192.168.65.254")

        data = _FakeHookData(("127.0.0.1", 8080))
        addon.server_connect(data)
        assert data.server.error == "Connection to proxy's own port blocked"

    def test_server_connect_gateway_unresolved_warns_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        addon = MitmproxyAddon()
        monkeypatch.setattr("holon_coherence.mitm_addon.in_container", lambda: True)
        monkeypatch.setenv("HOLON_HOST_LOCAL_HOSTS", "localhost:11434")
        monkeypatch.setattr(addon, "_resolve_gateway", lambda: None)

        data = _FakeHookData(("localhost", 11434))
        addon.server_connect(data)
        assert addon._warned_gateway is True

    def test_request_missing_request(self) -> None:
        addon = MitmproxyAddon()
        flow = MockFlow()
        flow.request = None
        addon.request(flow)
        assert addon.total_requests == 0

    def test_request_unknown_provider(self) -> None:
        addon = MitmproxyAddon()
        flow = MockFlow(request=MockRequest(url="https://api.github.com/repos", text="{}"))
        addon.request(flow)
        assert flow.provider == "unknown"
        assert addon.total_requests == 0

    def test_request_non_json_body(self) -> None:
        addon = MitmproxyAddon()
        flow = MockFlow(request=MockRequest(url="https://api.openai.com/v1/chat/completions", text="not a json body"))
        addon.request(flow)
        assert flow.provider == "openai"
        assert addon.total_requests == 1

    def test_request_passive_monitoring(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_PASSIVE_MONITORING", "1")
        addon = MitmproxyAddon()
        req_payload = {"messages": [{"role": "user", "content": "hi"}]}
        flow = MockFlow(
            request=MockRequest(url="https://api.openai.com/v1/chat/completions", text=json.dumps(req_payload))
        )
        addon.request(flow)
        assert flow.provider == "openai"
        assert flow.cleaner_result is None
        assert flow.req_data == req_payload
        assert not flow.is_cached

    def test_request_cache_miss_cleans_and_forwards(self, tmp_path) -> None:
        addon = MitmproxyAddon(cache_dir=str(tmp_path), wire_log_dir=str(tmp_path / "logs"))
        req_payload = {
            "model": "gpt-4",
            "messages": [
                {"role": "user", "content": "hello world"},
                {"role": "assistant", "content": "hi", "tool_calls": [{"id": "1", "function": {"name": "test"}}]},
                {"role": "tool", "tool_call_id": "1", "content": "tool output result"},
            ],
        }
        flow = MockFlow(
            request=MockRequest(url="https://api.openai.com/v1/chat/completions", text=json.dumps(req_payload))
        )
        addon.request(flow)
        assert flow.provider == "openai"
        assert flow.req_data is not None
        assert flow.is_cached is False
        assert flow.cleaner_result is not None

    def test_request_cache_hit_synthesizes_response(self, tmp_path) -> None:
        addon = MitmproxyAddon(cache_dir=str(tmp_path), wire_log_dir=str(tmp_path / "logs"))
        req_payload = {"model": "gpt-4", "messages": [{"role": "user", "content": "hello cached"}]}
        addon.interceptor.cache_store.put(
            req_payload, {"choices": [{"message": {"content": "I am cached"}}]}, provider="openai"
        )

        flow = MockFlow(
            request=MockRequest(url="https://api.openai.com/v1/chat/completions", text=json.dumps(req_payload))
        )
        addon.request(flow)
        assert flow.is_cached is True
        assert addon.cache_hits == 1
        assert flow.response is not None
        assert flow.response.status_code == 200
        assert flow.response.headers["X-Holon-Cache-Hit-Rate"] == "1.0000"
        assert flow.response.headers["X-Holon-TTFT-Ms"] == "0.00"
        flush_wire_logs()

    def test_request_custom_intercept_request_fallback(self) -> None:
        addon = MitmproxyAddon()

        def custom_intercept(endpoint, request_json):
            return {"custom": True}, None

        addon.interceptor.intercept_request = custom_intercept
        req_payload = {"messages": [{"role": "user", "content": "hi"}]}
        flow = MockFlow(
            request=MockRequest(url="https://api.openai.com/v1/chat/completions", text=json.dumps(req_payload))
        )
        addon.request(flow)
        assert flow.req_data == {"custom": True}

    def test_responseheaders_unknown_provider(self) -> None:
        addon = MitmproxyAddon()
        flow = MockFlow()
        flow.provider = "unknown"
        addon.responseheaders(flow)
        assert flow.response_headers_time is None

    def test_responseheaders_non_sse(self) -> None:
        addon = MitmproxyAddon()
        flow = MockFlow(response=MockResponse(headers={"Content-Type": "application/json"}))
        flow.provider = "openai"
        addon.responseheaders(flow)
        assert flow.response_headers_time is not None
        assert flow.sse_chunks is None

    def test_responseheaders_sse_stream_wrapper_and_limit(self) -> None:
        addon = MitmproxyAddon()
        existing_calls = []

        def existing_stream(chunk: bytes) -> bytes:
            existing_calls.append(chunk)
            return chunk

        flow = MockFlow(
            response=MockResponse(headers={"Content-Type": "text/event-stream; charset=utf-8"}, stream=existing_stream)
        )
        flow.provider = "openai"
        addon.responseheaders(flow)
        assert flow.sse_chunks == []
        assert callable(flow.response.stream)

        c1 = b"data: 1\n\n"
        out1 = flow.response.stream(c1)
        assert out1 == c1
        assert flow.first_chunk_time is not None
        assert flow.sse_chunks == [c1]
        assert existing_calls == [c1]

        # Call with chunk exceeding _MAX_SSE_BUFFER_BYTES
        flow.sse_bytes = _MAX_SSE_BUFFER_BYTES + 1
        flow.response.stream(b"overflow")
        assert len(flow.sse_chunks) == 1

    def test_responseheaders_with_dict_headers(self) -> None:
        addon = MitmproxyAddon()
        flow = MockFlow()
        flow.provider = "gemini"
        flow.response = MockResponse()
        flow.response.headers = {"content-type": "text/event-stream"}
        addon.responseheaders(flow)
        assert flow.sse_chunks == []

    def test_response_early_return_conditions(self) -> None:
        addon = MitmproxyAddon()
        flow1 = MockFlow()
        flow1.request = None
        addon.response(flow1)

        flow2 = MockFlow()
        flow2.response = None
        addon.response(flow2)

        flow3 = MockFlow()
        flow3.provider = "unknown"
        addon.response(flow3)

        flow4 = MockFlow()
        flow4.provider = "openai"
        flow4.is_cached = True
        addon.response(flow4)

    def test_response_200_json(self, tmp_path) -> None:
        addon = MitmproxyAddon(cache_dir=str(tmp_path), wire_log_dir=str(tmp_path / "logs"))
        req_payload = {"messages": [{"role": "user", "content": "testing 200"}]}
        resp_payload = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        flow = MockFlow(
            request=MockRequest(url="https://api.openai.com/v1/chat/completions", text=json.dumps(req_payload)),
            response=MockResponse(status_code=200, text=json.dumps(resp_payload)),
        )
        flow.provider = "openai"
        flow.request_start_time = time.perf_counter() - 0.1
        flow.response_headers_time = time.perf_counter() - 0.05
        addon.response(flow)

        assert flow.response.headers["X-Holon-Cache-Hit-Rate"] == "0.0000"
        assert "X-Holon-TTFT-Ms" in flow.response.headers
        flush_wire_logs()

    def test_response_200_sse(self, tmp_path) -> None:
        addon = MitmproxyAddon(cache_dir=str(tmp_path), wire_log_dir=str(tmp_path / "logs"))
        req_payload = {"messages": [{"role": "user", "content": "stream test"}]}
        sse_text = _sse(
            {"choices": [{"delta": {"content": "hello "}}]},
            {"choices": [{"delta": {"content": "stream"}}], "usage": {"prompt_tokens": 8, "completion_tokens": 4}},
        )
        flow = MockFlow(
            request=MockRequest(url="https://api.openai.com/v1/chat/completions", text=json.dumps(req_payload)),
            response=MockResponse(status_code=200, headers={"Content-Type": "text/event-stream"}),
        )
        flow.provider = "openai"
        flow.sse_chunks = [sse_text.encode("utf-8")]
        flow.request_start_time = time.perf_counter() - 0.2
        flow.response_headers_time = time.perf_counter() - 0.15
        flow.first_chunk_time = time.perf_counter() - 0.1
        addon.response(flow)

        assert "X-Holon-Prefill-TPS" in flow.response.headers
        assert "X-Holon-Output-TPS" in flow.response.headers
        flush_wire_logs()

    def test_response_non_200(self, tmp_path) -> None:
        addon = MitmproxyAddon(cache_dir=str(tmp_path), wire_log_dir=str(tmp_path / "logs"))
        flow = MockFlow(
            request=MockRequest(url="https://api.openai.com/v1/chat/completions", text='{"prompt":"fail"}'),
            response=MockResponse(status_code=429, text='{"error":"rate_limited"}'),
        )
        flow.provider = "openai"
        flow.request_start_time = time.perf_counter() - 0.05
        addon.response(flow)
        flush_wire_logs()

    def test_dump_flow_transaction_disabled(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        monkeypatch.setenv("ENABLE_WIRE_LOGGING", "0")
        addon = MitmproxyAddon(wire_log_dir=str(tmp_path / "logs"))
        flow = MockFlow()
        addon._dump_flow_transaction(flow, resp_data={"test": 1})
        assert not (tmp_path / "logs").exists()

    def test_dump_flow_transaction_structure(self, tmp_path) -> None:
        log_dir = str(tmp_path / "wire_logs")
        addon = MitmproxyAddon(wire_log_dir=log_dir)
        flow = MockFlow(
            request=MockRequest(
                url="https://api.anthropic.com/v1/messages?api_key=SECRET123",
                headers={"x-holon-agent-id": "agent-007", "x-holon-turn-id": "42", "authorization": "Bearer sk-1234"},
                text=json.dumps({"messages": [{"role": "user", "content": "test"}]}),
            ),
            response=MockResponse(status_code=200, text=json.dumps({"content": [{"type": "text", "text": "resp"}]})),
        )
        flow.provider = "anthropic"
        flow.cleaner_result = CleaningResult(
            payload={}, chars_saved=100, tool_outputs_omitted=2, turns_summarized=1, cache_control_injected=1
        )
        addon._dump_flow_transaction(
            flow, resp_data={"content": "test"}, status_code=200, is_hit=False, ttft=0.05, total_time=0.2
        )
        flush_wire_logs()

        jsonl_file = tmp_path / "wire_logs" / "transactions.jsonl"
        assert jsonl_file.exists()
        line = json.loads(jsonl_file.read_text().strip())
        assert line["agent_id"] == "agent-007"
        assert line["turn_id"] == 42
        assert line["provider"] == "anthropic"
        assert line["delta"]["chars_saved"] == 100
        assert line["headers"]["authorization"] == "[REDACTED]"
        assert "SECRET123" not in line["endpoint"]


class TestInterceptorCore:
    def test_cache_store_property(self, tmp_path) -> None:
        interceptor = MITMProxyInterceptor(cache_dir=str(tmp_path))
        assert interceptor.cache_store is not None
        assert interceptor.cache_store is interceptor.cache_store

    def test_detect_provider_all_variants(self) -> None:
        interceptor = MITMProxyInterceptor()
        assert interceptor.detect_provider("https://api.anthropic.com/v1/messages") == "anthropic"
        assert interceptor.detect_provider("https://proxy/v1/messages") == "anthropic"
        assert interceptor.detect_provider("https://proxy", {"anthropic-version": "2023-06-01"}) == "anthropic"
        assert interceptor.detect_provider("https://proxy", {"anthropic_version": "2023-06-01"}) == "anthropic"
        assert interceptor.detect_provider("https://proxy", {"system": "you are helpful"}) == "anthropic"

        assert interceptor.detect_provider("https://generativelanguage.googleapis.com/v1/models") == "gemini"
        assert interceptor.detect_provider("https://test.generativelanguage.googleapis.com") == "gemini"
        assert interceptor.detect_provider("https://proxy/v1/gemini-pro") == "gemini"
        assert interceptor.detect_provider("https://proxy/v1/models/gemini:generateContent") == "gemini"
        assert interceptor.detect_provider("https://proxy/v1/models/gemini:streamGenerateContent") == "gemini"
        assert interceptor.detect_provider("https://proxy", {"contents": []}) == "gemini"

        for prov in [
            "openai",
            "openrouter",
            "deepseek",
            "groq",
            "together",
            "mistral",
            "fireworks",
            "ollama",
            "vllm",
            "lmstudio",
            "chat/completions",
            "v1/completions",
        ]:
            assert interceptor.detect_provider(f"https://api.{prov}.com") == "openai"
        assert interceptor.detect_provider("https://proxy", {"messages": []}) == "openai"
        assert interceptor.detect_provider("https://proxy", {"prompt": "test"}) == "openai"

        assert interceptor.detect_provider("https://custom.api/run", {}) == "unknown"

    def test_intercept_request_with_stats_streaming_bypasses(self, tmp_path) -> None:
        interceptor = MITMProxyInterceptor(cache_dir=str(tmp_path))
        req = {"messages": [{"role": "user", "content": "hi"}], "stream": True}
        _cleaned, cached, stats = interceptor.intercept_request_with_stats(
            "https://api.openai.com/v1/chat/completions", req
        )
        assert cached is None
        assert stats is not None

    def test_intercept_request_with_stats_cache_exception_bypasses(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        interceptor = MITMProxyInterceptor(cache_dir=str(tmp_path))
        req = {"messages": [{"role": "user", "content": "hi"}]}
        monkeypatch.setattr(
            interceptor.cache_store,
            "get",
            lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("db locked")),
        )
        _cleaned, cached, stats = interceptor.intercept_request_with_stats(
            "https://api.openai.com/v1/chat/completions", req
        )
        assert cached is None
        assert stats is not None

    def test_intercept_response_conditions(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        interceptor = MITMProxyInterceptor(cache_dir=str(tmp_path))
        req = {"messages": [{"role": "user", "content": "hi"}]}
        resp = {"choices": [{"message": {"content": "ok"}}]}

        interceptor.enable_caching = False
        interceptor.intercept_response("https://api.openai.com/v1/chat/completions", req, resp, 200)

        interceptor.enable_caching = True
        interceptor.intercept_response("https://api.openai.com/v1/chat/completions", {"stream": True}, resp, 200)
        interceptor.intercept_response("https://api.openai.com/v1/chat/completions", req, resp, 500)
        interceptor.intercept_response("https://api.openai.com/v1/chat/completions", req, {"error": "bad"}, 200)
        interceptor.intercept_response("https://api.openai.com/v1/chat/completions", req, {"type": "error"}, 200)

        monkeypatch.setattr(
            interceptor.cache_store,
            "put",
            lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("db locked")),
        )
        interceptor.intercept_response("https://api.openai.com/v1/chat/completions", req, resp, 200)


class TestScrubPayload:
    def test_nested_structures_and_secret_keys(self) -> None:
        payload = {
            "api_key": "sk-real12345678901234567890",
            "password": "mypassword",
            "nested": {
                "token": "tok123",
                "normal": "hello",
                "items": [
                    {"client_secret": "secretvalue", "data": "clean"},
                    ("refresh_token", "refreshtok"),
                ],
            },
        }
        scrubbed = scrub_payload(payload)
        assert scrubbed["api_key"] == "[REDACTED]"
        assert scrubbed["password"] == "[REDACTED]"
        assert scrubbed["nested"]["token"] == "[REDACTED]"
        assert scrubbed["nested"]["normal"] == "hello"
        assert scrubbed["nested"]["items"][0]["client_secret"] == "[REDACTED]"
        assert scrubbed["nested"]["items"][0]["data"] == "clean"

    def test_secret_string_values_in_payload(self) -> None:
        jwt_part = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.doNotLeakThisSignature"
        payload = {
            "prompt": f"Here is key sk-ant-api03-abcdef12345678901234567890 and Bearer {jwt_part}",
        }
        scrubbed = scrub_payload(payload)
        assert "sk-ant-" not in scrubbed["prompt"]
        assert "[REDACTED_SECRET]" in scrubbed["prompt"]

    def test_max_depth_guard(self) -> None:
        deep = {"a": {"b": {"c": 1}}}
        assert scrub_payload(deep, max_depth=0) == deep

    def test_primitive_and_empty_types(self) -> None:
        assert scrub_payload(123) == 123
        assert scrub_payload(None) is None
        assert scrub_payload(True) is True


class TestWireLoggingAndUtilities:
    @pytest.mark.parametrize(
        ("val", "expected"),
        [("0", False), ("false", False), ("no", False), ("off", False), ("1", True), ("true", True), ("yes", True)],
    )
    def test_is_wire_logging_enabled(self, monkeypatch: pytest.MonkeyPatch, val: str, expected: bool) -> None:
        monkeypatch.setenv("ENABLE_WIRE_LOGGING", val)
        assert is_wire_logging_enabled() == expected

    @pytest.mark.parametrize(
        ("val", "expected"),
        [("1", True), ("true", True), ("yes", True), ("on", True), ("0", False), ("false", False)],
    )
    def test_is_passive_monitoring(self, monkeypatch: pytest.MonkeyPatch, val: str, expected: bool) -> None:
        monkeypatch.setenv("HOLON_PASSIVE_MONITORING", val)
        assert is_passive_monitoring() == expected

    def test_get_wire_log_executor_and_shutdown(self) -> None:
        shutdown_wire_logs()
        exec1 = _get_wire_log_executor()
        assert exec1 is not None
        exec2 = _get_wire_log_executor()
        assert exec1 is exec2
        shutdown_wire_logs()

    def test_write_transaction_sync_and_atomic_replace(self, tmp_path) -> None:
        log_dir = str(tmp_path / "sync_logs")
        record = {"turn_id": "test_turn", "flow_id": "flow1", "status": 200}
        _write_transaction_sync(record, log_dir)
        assert (tmp_path / "sync_logs" / "turn_test_turn_flow1.json").exists()
        assert (tmp_path / "sync_logs" / "transactions.jsonl").exists()

    def test_dump_wire_transaction_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENABLE_WIRE_LOGGING", "0")
        fut = dump_wire_transaction({"test": 1})
        assert fut.done()
        assert fut.result() is None

    def test_get_header_case_insensitive(self) -> None:
        assert get_header_case_insensitive(None, "X-Test") is None
        assert get_header_case_insensitive({"x-test": "found"}, "X-Test") == "found"
        assert get_header_case_insensitive({"Other": "val"}, "X-Test") is None

        class FakeHeaders:
            def items(self):
                return [("X-Special", "special_value")]

        assert get_header_case_insensitive(FakeHeaders(), "x-special") == "special_value"

    def test_derive_turn_id_precedence(self) -> None:
        assert derive_turn_id({"x-holon-turn-id": "5"}, None) == 5
        assert derive_turn_id({"x-holon-turn-id": "five"}, None) == "five"

        payload_messages = {
            "messages": [
                {"role": "user", "content": "1"},
                {"role": "assistant", "content": "2"},
                {"role": "user", "content": "3"},
                {"role": "assistant", "content": "4"},
            ]
        }
        assert derive_turn_id({}, payload_messages) == 3

        payload_contents = {
            "contents": [
                {"role": "user", "parts": []},
                {"role": "model", "parts": []},
            ]
        }
        assert derive_turn_id({}, payload_contents) == 2

        assert derive_turn_id({}, {}, fallback_id=99) == 99

    def test_find_nested_key_edge_cases(self) -> None:
        assert find_nested_key("string", "key") is None
        assert find_nested_key({}, "key") is None
        assert find_nested_key({"a": 1}, "key", max_depth=0) is None
        assert find_nested_key({"a": {"b": {"target": "hit"}}}, "target") == "hit"
        assert find_nested_key([{"target": "list_hit"}], "target") == "list_hit"
        assert find_nested_key({"a": [{"b": 1}]}, "b") == 1

    def test_log_telemetry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        log_telemetry("testing info log")

        class FakeLog:
            def __init__(self):
                self.messages = []

            def info(self, msg):
                self.messages.append(msg)

        class FakeCtx:
            log = FakeLog()

        monkeypatch.setattr("holon_coherence.mitm_addon.ctx", FakeCtx())
        log_telemetry("ctx log test")
        assert "ctx log test" in FakeCtx.log.messages

    def test_estimate_chars_deep(self) -> None:
        assert estimate_chars(None, max_depth=0) == 0
        assert estimate_chars(42) == 0
        assert estimate_chars("hello") == 5
        assert estimate_chars(["a", "bc"]) == 3
        assert estimate_chars({"system": "sys", "messages": ["m1", "m2"]}) == 3 + 2 + 2


class TestSSEReassemblyEdgeCases:
    def test_gemini_candidate_string_and_parts(self) -> None:
        stream = _sse(
            {"candidates": ["string_candidate"]},
            {"candidates": [{"content": "string_content"}]},
            {"candidates": [{"content": {"parts": ["string_part"]}}]},
        )
        counts = extract_sse_token_counts(stream, {}, "gemini")
        assert counts.output_tokens > 0

    def test_token_counts_exception_fallback(self) -> None:
        counts = extract_token_counts({"prompt": "req"}, {"usage": 12345}, "anthropic")
        assert counts.input_tokens > 0

    def test_openai_tool_calls_consecutive_and_unclosed(self) -> None:
        stream = _sse(
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "f1", "arguments": "1"}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 1, "function": {"name": "f2", "arguments": "2"}}]}}]},
        )
        content = extract_sse_content(stream, "openai")
        assert "f1(1)" in content
        assert "f2(2)" in content

    def test_gemini_function_call_str_args(self) -> None:
        stream = _sse({"candidates": [{"content": {"parts": [{"functionCall": {"name": "run", "args": "raw_str"}}]}}]})
        counts = extract_sse_token_counts(stream, {}, "gemini")
        assert counts.output_tokens > 0

    def test_sse_token_counts_malformed_lines_and_non_dicts(self) -> None:
        stream = "\n".join(["data: 123", "data: not_json", "not_data_line", ""])
        counts = extract_sse_token_counts(stream, {}, "openai")
        assert counts.output_tokens == 0

    def test_intercept_request_stats_unknown_provider_warning(self) -> None:
        interceptor = MITMProxyInterceptor()
        res = interceptor.intercept_request_with_stats("https://unknown.host/api", {"data": 1})
        assert res == ({"data": 1}, None, None)

    def test_intercept_request_backward_compatible_2tuple(self) -> None:
        interceptor = MITMProxyInterceptor()
        res = interceptor.intercept_request("https://api.openai.com/v1/chat/completions", {"messages": []})
        assert isinstance(res, tuple)
        assert len(res) == 2

    def test_get_header_case_insensitive_get_only(self) -> None:
        class OnlyGet:
            def get(self, key: str) -> str | None:
                return "get_val" if key == "X-Target" else None

        assert get_header_case_insensitive(OnlyGet(), "X-Target") == "get_val"

    def test_log_telemetry_ctx_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class ThrowingLog:
            def info(self, msg: str) -> None:
                raise RuntimeError("ctx error")

        class FakeCtx:
            log = ThrowingLog()

        monkeypatch.setattr("holon_coherence.mitm_addon.ctx", FakeCtx())
        log_telemetry("should fall back")

    def test_shutdown_wire_logs_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        executor = _get_wire_log_executor()
        monkeypatch.setattr(executor, "shutdown", lambda **kw: (_ for _ in ()).throw(RuntimeError("shutdown error")))
        shutdown_wire_logs()

    def test_write_transaction_sync_failure(self) -> None:
        _write_transaction_sync({"turn_id": 1}, "/nonexistent/directory/that/cannot/be/created/root")

    def test_dump_flow_transaction_exception_logged(self, tmp_path) -> None:
        addon = MitmproxyAddon(wire_log_dir=str(tmp_path / "logs"))
        flow = MockFlow()
        flow.request = None
        addon._dump_flow_transaction(flow, resp_data={})

    def test_request_cleaner_log_branch(self, tmp_path) -> None:
        addon = MitmproxyAddon(cache_dir=str(tmp_path), wire_log_dir=str(tmp_path / "logs"))
        req = {
            "messages": [
                {"role": "user", "content": "run task"},
                {"role": "assistant", "content": "ok", "tool_calls": [{"id": "c1", "function": {"name": "f"}}]},
                {"role": "tool", "tool_call_id": "c1", "content": "output"},
                {"role": "assistant", "content": "ok2", "tool_calls": [{"id": "c2", "function": {"name": "f"}}]},
                {"role": "tool", "tool_call_id": "c2", "content": "output"},
            ]
        }
        flow = MockFlow(request=MockRequest(url="https://api.openai.com/v1/chat/completions", text=json.dumps(req)))
        addon.request(flow)
        assert flow.cleaner_result is not None

    def test_request_exception_handling(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        addon = MitmproxyAddon(cache_dir=str(tmp_path), wire_log_dir=str(tmp_path / "logs"))
        flow = MockFlow(request=MockRequest(url="https://api.openai.com/v1/chat/completions", text='{"test": 1}'))
        monkeypatch.setattr(
            addon.interceptor,
            "intercept_request_with_stats",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        addon.request(flow)

    def test_responseheaders_no_callable_existing_stream(self) -> None:
        addon = MitmproxyAddon()
        flow = MockFlow(response=MockResponse(headers={"Content-Type": "text/event-stream"}, stream="not_callable"))
        flow.provider = "openai"
        addon.responseheaders(flow)
        out = flow.response.stream(b"chunk")
        assert out == b"chunk"

    def test_response_exception_handling(self, monkeypatch: pytest.MonkeyPatch) -> None:
        addon = MitmproxyAddon()
        flow = MockFlow(request=MockRequest(), response=MockResponse())
        flow.provider = "openai"
        monkeypatch.setattr(flow.response, "get_text", lambda: (_ for _ in ()).throw(RuntimeError("response error")))
        addon.response(flow)

    def test_response_non_200_unparseable(self, tmp_path) -> None:
        addon = MitmproxyAddon(cache_dir=str(tmp_path), wire_log_dir=str(tmp_path / "logs"))
        flow = MockFlow(
            request=MockRequest(url="https://api.openai.com/v1/chat/completions", text="raw text not json"),
            response=MockResponse(status_code=500, text="raw error text"),
        )
        flow.provider = "openai"
        addon.response(flow)
        flush_wire_logs()
