import io
import os
import stat
import sys
import tempfile
from unittest.mock import patch

import pytest

from holon_coherence import (
    HybridCacheStore,
    JSONContextCleaner,
    OpenBrainMemory,
    RingerOrchestrator,
    generate_root_ca,
)


def _build_repetitive_anthropic_tool_messages(repeated_output: str) -> list[dict]:
    messages = [{"role": "user", "content": "Start session"}]
    for turn_index in range(1, 23, 2):
        messages.append({"role": "assistant", "content": f"Running step {turn_index}"})
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": f"tool_use_{turn_index}",
                        "content": repeated_output,
                    }
                ],
            }
        )
    messages.append({"role": "assistant", "content": "Final step"})
    return messages


def _assert_anthropic_tool_result_ids_preserved(cleaned_messages: list[dict]) -> None:
    for msg in cleaned_messages:
        if isinstance(msg.get("content"), list):
            for block in msg["content"]:
                if block.get("type") == "tool_result":
                    assert "tool_use_id" in block
                    assert block["tool_use_id"].startswith("tool_use_")


def _assert_gemini_function_response_names_preserved(
    cleaned_contents: list[dict],
    expected_name: str,
) -> None:
    for turn in cleaned_contents:
        for part in turn.get("parts", []):
            if "functionResponse" in part:
                assert part["functionResponse"]["name"] == expected_name


def test_ca_generator() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        ca_cert, ca_key = generate_root_ca(cert_dir=tmpdir)
        assert os.path.exists(ca_cert)
        assert os.path.exists(ca_key)
        assert os.path.exists(os.path.join(tmpdir, "mitmproxy-ca-cert.pem"))
        assert os.path.exists(os.path.join(tmpdir, "mitmproxy-ca.pem"))


def test_context_cleaner_deduplication() -> None:
    cleaner = JSONContextCleaner(enable_deduplication=True, max_turns=10)
    large_sample = "X" * 300
    payload = {
        "messages": [
            {"role": "user", "content": "Analyze code."},
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": large_sample}],
            },
            {"role": "assistant", "content": "Done."},
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "call_2", "content": large_sample}],
            },
            {"role": "assistant", "content": "Done turn 2."},
            {"role": "user", "content": "Next command."},
        ]
    }
    res = cleaner.process_payload_with_stats(payload, provider="anthropic")
    assert res.tool_outputs_omitted >= 1
    assert res.chars_saved > 0


def test_hybrid_cache_exact_and_normalize() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = HybridCacheStore(cache_dir=tmpdir, similarity_threshold=0.85)
        payload = {
            "model": "gemini-3.8-flash-high",
            "messages": [{"role": "user", "content": "Explain architecture."}],
        }
        cache.put(payload, "Architectural RFC details", provider="gemini")
        retrieved = cache.get(payload, provider="gemini")
        assert retrieved == "Architectural RFC details"


def test_openbrain_memory() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        ob = OpenBrainMemory(db_dir=tmpdir)
        mem_id = ob.store_memory(
            topic="test_topic",
            content="Always set DASHBOARD_DIR before running tests.",
            category="lesson_learned",
        )
        assert mem_id > 0
        memories = ob.retrieve_memories(topic="test_topic")
        assert len(memories) == 1
        assert "DASHBOARD_DIR" in memories[0]["content"]


def test_ringer_orchestrator() -> None:
    ringer = RingerOrchestrator(architect_model="model-t1", executor_model="model-t2")
    subtask = ringer.plan_subtask("task_01", "Compile assets", ["make build"])
    assert subtask["assigned_model"] == "model-t2"


def test_ringer_orchestrator_dynamic_env_resolution() -> None:
    with patch.dict(os.environ, {}, clear=True):
        ringer_default = RingerOrchestrator()
        assert ringer_default.architect_model == "claude-3-5-sonnet"
        assert ringer_default.executor_model == "gemini-3.5-flash"

    with patch.dict(
        os.environ,
        {
            "HOLON_ARCHITECT_MODEL": "custom-arch-model",
            "HOLON_EXECUTOR_MODEL": "custom-exec-model",
        },
    ):
        ringer_env = RingerOrchestrator()
        assert ringer_env.architect_model == "custom-arch-model"
        assert ringer_env.executor_model == "custom-exec-model"


def test_cli_parser_and_run() -> None:
    from holon_coherence.cli import is_in_container, main

    assert isinstance(is_in_container(), bool)

    orig_argv = sys.argv
    try:
        sys.argv = [
            "holon-coherence",
            "run",
            "--",
            sys.executable,
            "-c",
            "import os; assert os.environ['HTTP_PROXY'] == 'http://127.0.0.1:8080' and "
            "os.environ['http_proxy'] == 'http://127.0.0.1:8080'",
        ]
        with pytest.raises(SystemExit) as cm:
            main()
        assert cm.value.code == 0
    finally:
        sys.argv = orig_argv


def test_cli_init_ca() -> None:
    from holon_coherence.cli import main

    orig_argv = sys.argv
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            sys.argv = ["holon-coherence", "init-ca", "--output-dir", tmpdir]
            with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                main()
            output = mock_out.getvalue()
            assert "Certificate:" in output
            assert "Key:" in output
        finally:
            sys.argv = orig_argv


def test_cli_run_missing_ca_warning() -> None:
    from holon_coherence.cli import main

    orig_argv = sys.argv
    try:
        sys.argv = [
            "holon-coherence",
            "run",
            "--ca-cert",
            "/nonexistent/ca-cert.pem",
            "--",
            sys.executable,
            "-c",
            "exit(0)",
        ]
        with patch("sys.stderr", new_callable=io.StringIO) as mock_err:
            with pytest.raises(SystemExit) as cm:
                main()
            assert cm.value.code == 0
            assert "Warning: CA certificate not found" in mock_err.getvalue()
    finally:
        sys.argv = orig_argv


def test_ca_generator_permissions() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        _ca_cert, ca_key = generate_root_ca(cert_dir=tmpdir)
        dir_mode = stat.S_IMODE(os.stat(tmpdir).st_mode)
        key_mode = stat.S_IMODE(os.stat(ca_key).st_mode)
        mitm_pem = os.path.join(tmpdir, "mitmproxy-ca.pem")
        mitm_pem_mode = stat.S_IMODE(os.stat(mitm_pem).st_mode)

        assert dir_mode == 0o700
        assert key_mode == 0o600
        assert mitm_pem_mode == 0o600


def test_hybrid_cache_permissions() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = os.path.join(tmpdir, "cache_sub")
        store = HybridCacheStore(cache_dir=cache_dir)
        dir_mode = stat.S_IMODE(os.stat(cache_dir).st_mode)
        db_mode = stat.S_IMODE(os.stat(store.db_path).st_mode)

        assert dir_mode == 0o700
        assert db_mode == 0o600


def test_mitm_wire_log_permissions() -> None:
    from holon_coherence.mitm_addon import _write_transaction_sync

    with tempfile.TemporaryDirectory() as tmpdir:
        wire_dir = os.path.join(tmpdir, "wire_logs_sub")
        sample_record = {"turn_id": 1, "flow_id": "test_flow", "request": {"url": "https://api.openai.com"}}
        _write_transaction_sync(sample_record, wire_dir)

        dir_mode = stat.S_IMODE(os.stat(wire_dir).st_mode)
        assert dir_mode == 0o700

        turn_file = os.path.join(wire_dir, "turn_1_test_flow.json")
        assert os.path.exists(turn_file)
        assert stat.S_IMODE(os.stat(turn_file).st_mode) == 0o600

        jsonl_file = os.path.join(wire_dir, "transactions.jsonl")
        assert os.path.exists(jsonl_file)
        assert stat.S_IMODE(os.stat(jsonl_file).st_mode) == 0o600


def test_secret_redaction() -> None:
    from holon_coherence.mitm_addon import scrub_headers, scrub_payload

    payload_with_secrets = {
        "auth": "secret_auth_token_xyz",
        "credential": "secret_credential_val",
        "credentials": {"nested_key": "val123"},
        "client_secret": "my_client_secret_abc",
        "client-secret": "my_client_secret_dash",
        "refresh_token": "my_refresh_token_xyz",
        "refresh-token": "my_refresh_token_dash",
        "Client_Secret": "cased_secret",
        "REFRESH_TOKEN": "cased_refresh",
        "AUTH": "cased_auth",
        "author": "John Doe",
        "authenticity": "high",
        "nested": [
            {"role": "user", "content": "hello"},
            {"auth": "token_inside_list", "credential": "cred_inside_list"},
        ],
    }

    scrubbed = scrub_payload(payload_with_secrets)
    assert scrubbed["auth"] == "[REDACTED]"
    assert scrubbed["credential"] == "[REDACTED]"
    assert scrubbed["credentials"] == "[REDACTED]"
    assert scrubbed["client_secret"] == "[REDACTED]"
    assert scrubbed["client-secret"] == "[REDACTED]"
    assert scrubbed["refresh_token"] == "[REDACTED]"
    assert scrubbed["refresh-token"] == "[REDACTED]"
    assert scrubbed["Client_Secret"] == "[REDACTED]"
    assert scrubbed["REFRESH_TOKEN"] == "[REDACTED]"
    assert scrubbed["AUTH"] == "[REDACTED]"
    assert scrubbed["author"] == "John Doe"
    assert scrubbed["authenticity"] == "high"
    assert scrubbed["nested"][1]["auth"] == "[REDACTED]"
    assert scrubbed["nested"][1]["credential"] == "[REDACTED]"

    headers_with_secrets = {
        "Auth": "bearer_abc",
        "Credential": "cred_value",
        "Credentials": "creds_value",
        "Authorization": "Bearer 123",
        "Content-Type": "application/json",
    }
    scrubbed_headers = scrub_headers(headers_with_secrets)
    assert scrubbed_headers["auth"] == "[REDACTED]"
    assert scrubbed_headers["credential"] == "[REDACTED]"
    assert scrubbed_headers["credentials"] == "[REDACTED]"
    assert scrubbed_headers["authorization"] == "[REDACTED]"
    assert scrubbed_headers["content-type"] == "application/json"


def test_active_optimization_default() -> None:
    from holon_coherence.mitm_addon import is_passive_monitoring

    with patch.dict(os.environ, {}, clear=True):
        assert not is_passive_monitoring()

    with patch.dict(os.environ, {"HOLON_PASSIVE_MONITORING": "1"}, clear=True):
        assert is_passive_monitoring()

    with patch.dict(os.environ, {"COHERENCE_TOKEN_REDUCTION": "0"}, clear=True):
        assert is_passive_monitoring()

    with patch.dict(os.environ, {"COHERENCE_TOKEN_REDUCTION": "1", "HOLON_PASSIVE_MONITORING": "0"}, clear=True):
        assert not is_passive_monitoring()


def test_session_wide_tool_deduplication_anthropic() -> None:
    cleaner = JSONContextCleaner(enable_deduplication=True, max_turns=60)
    status_line = "On branch main\nYour branch is up to date with 'origin/main'.\nnothing to commit\n"
    large_status_output = status_line * 10
    messages = _build_repetitive_anthropic_tool_messages(large_status_output)

    payload = {"messages": messages}
    res = cleaner.process_payload_with_stats(payload, provider="anthropic")
    assert res.tool_outputs_omitted >= 5
    assert res.chars_saved > 1000
    _assert_anthropic_tool_result_ids_preserved(res.payload["messages"])


def test_session_wide_tool_deduplication_openai() -> None:
    cleaner = JSONContextCleaner(enable_deduplication=True, max_turns=60)
    build_line = "Compiling src/core.rs...\nFinished release [optimized] target(s) in 2.34s\n"
    build_log = build_line * 10
    messages = [{"role": "user", "content": "Execute build"}]

    for i in range(1, 21, 2):
        messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": f"call_{i}", "type": "function", "function": {"name": "run_build"}}],
            }
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": f"call_{i}",
                "content": build_log,
            }
        )
    messages.append({"role": "assistant", "content": "All builds complete."})

    payload = {"messages": messages}
    res = cleaner.process_payload_with_stats(payload, provider="openai")
    assert res.tool_outputs_omitted >= 5

    cleaned_msgs = res.payload["messages"]
    for msg in cleaned_msgs:
        if msg.get("role") == "tool":
            assert "tool_call_id" in msg
            assert msg["tool_call_id"].startswith("call_")


def test_session_wide_tool_deduplication_gemini() -> None:
    cleaner = JSONContextCleaner(enable_deduplication=True, max_turns=60)
    dir_listing = {"files": [f"file_{k}.py" for k in range(50)], "status": "ok"}
    contents = [{"role": "user", "parts": [{"text": "List files"}]}]

    for _i in range(1, 19, 2):
        contents.append({"role": "model", "parts": [{"functionCall": {"name": "list_files"}}]})
        contents.append(
            {
                "role": "function",
                "parts": [
                    {
                        "functionResponse": {
                            "name": "list_files",
                            "response": dir_listing,
                        }
                    }
                ],
            }
        )
    contents.append({"role": "model", "parts": [{"text": "Done."}]})

    payload = {"contents": contents}
    res = cleaner.process_payload_with_stats(payload, provider="gemini")
    assert res.tool_outputs_omitted >= 5
    _assert_gemini_function_response_names_preserved(res.payload["contents"], "list_files")


def test_deduplication_disabled_openai_and_gemini() -> None:
    cleaner = JSONContextCleaner(enable_deduplication=False, max_turns=60)

    build_line = "Compiling src/core.rs...\nFinished release [optimized] target(s) in 2.34s\n"
    build_log = build_line * 10
    openai_messages = [{"role": "user", "content": "Execute build"}]
    for i in range(1, 11, 2):
        openai_messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": f"call_{i}", "type": "function", "function": {"name": "run_build"}}],
            }
        )
        openai_messages.append(
            {
                "role": "tool",
                "tool_call_id": f"call_{i}",
                "content": build_log,
            }
        )
    openai_messages.append({"role": "assistant", "content": "All builds complete."})
    res_openai = cleaner.process_payload_with_stats({"messages": openai_messages}, provider="openai")
    assert res_openai.tool_outputs_omitted == 0
    for msg in res_openai.payload["messages"]:
        if msg.get("role") == "tool":
            assert msg["content"] == build_log

    dir_listing = {"files": [f"file_{k}.py" for k in range(50)], "status": "ok"}
    gemini_contents = [{"role": "user", "parts": [{"text": "List files"}]}]
    for _i in range(1, 11, 2):
        gemini_contents.append({"role": "model", "parts": [{"functionCall": {"name": "list_files"}}]})
        gemini_contents.append(
            {
                "role": "function",
                "parts": [
                    {
                        "functionResponse": {
                            "name": "list_files",
                            "response": dir_listing,
                        }
                    }
                ],
            }
        )
    gemini_contents.append({"role": "model", "parts": [{"text": "Done."}]})
    res_gemini = cleaner.process_payload_with_stats({"contents": gemini_contents}, provider="gemini")
    assert res_gemini.tool_outputs_omitted == 0
    for turn in res_gemini.payload["contents"]:
        for part in turn.get("parts", []):
            if "functionResponse" in part:
                assert part["functionResponse"]["response"] == dir_listing


def test_throughput_metric_aliases() -> None:
    from holon_coherence.metrics_math import (
        compute_decode_speed,
        compute_decode_throughput,
        compute_decode_tps,
        compute_prefill_throughput,
        compute_prefill_tps,
        compute_prompt_prefill_speed,
        compute_tail_prefill_speed,
        compute_tail_prefill_throughput,
        compute_tail_prefill_tps,
    )

    prefill_tps = compute_prefill_tps(1000, 2.0)
    prefill_throughput = compute_prefill_throughput(1000, 2.0)
    prompt_prefill_speed = compute_prompt_prefill_speed(1000, 2.0)
    assert prefill_tps == 500.0
    assert prefill_throughput == 500.0
    assert prompt_prefill_speed == 500.0

    tail_prefill_tps = compute_tail_prefill_tps(200, 1.0)
    tail_prefill_throughput = compute_tail_prefill_throughput(200, 1.0)
    tail_prefill_speed = compute_tail_prefill_speed(200, 1.0)
    assert tail_prefill_tps == 200.0
    assert tail_prefill_throughput == 200.0
    assert tail_prefill_speed == 200.0

    decode_tps = compute_decode_tps(120, 2.0, streaming=True)
    decode_throughput = compute_decode_throughput(120, 2.0, streaming=True)
    decode_speed = compute_decode_speed(120, 2.0, streaming=True)
    assert decode_tps == 60.0
    assert decode_throughput == 60.0
    assert decode_speed == 60.0
