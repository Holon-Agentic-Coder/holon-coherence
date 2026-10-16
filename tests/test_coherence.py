"""Unit tests for holon-coherence components."""

import os
import tempfile
import unittest

from holon_coherence import (
    HybridCacheStore,
    JSONContextCleaner,
    OpenBrainMemory,
    RingerOrchestrator,
    generate_root_ca,
)


class TestHolonCoherence(unittest.TestCase):
    def test_ca_generator(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ca_cert, ca_key = generate_root_ca(cert_dir=tmpdir)
            self.assertTrue(os.path.exists(ca_cert))
            self.assertTrue(os.path.exists(ca_key))
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "mitmproxy-ca-cert.pem")))
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "mitmproxy-ca.pem")))

    def test_context_cleaner_deduplication(self):
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
        self.assertGreaterEqual(res.tool_outputs_omitted, 1)
        self.assertGreater(res.chars_saved, 0)

    def test_hybrid_cache_exact_and_normalize(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = HybridCacheStore(cache_dir=tmpdir, similarity_threshold=0.85)
            payload = {
                "model": "gemini-3.8-flash-high",
                "messages": [{"role": "user", "content": "Explain architecture."}],
            }
            # Put entry
            cache.put(payload, "Architectural RFC details", provider="gemini")
            # Retrieve entry
            retrieved = cache.get(payload, provider="gemini")
            self.assertEqual(retrieved, "Architectural RFC details")

    def test_openbrain_memory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ob = OpenBrainMemory(db_dir=tmpdir)
            mem_id = ob.store_memory(
                topic="test_topic",
                content="Always set DASHBOARD_DIR before running tests.",
                category="lesson_learned",
            )
            self.assertGreater(mem_id, 0)
            memories = ob.retrieve_memories(topic="test_topic")
            self.assertEqual(len(memories), 1)
            self.assertIn("DASHBOARD_DIR", memories[0]["content"])

    def test_ringer_orchestrator(self):
        ringer = RingerOrchestrator(architect_model="model-t1", executor_model="model-t2")
        subtask = ringer.plan_subtask("task_01", "Compile assets", ["make build"])
        self.assertEqual(subtask["assigned_model"], "model-t2")

    def test_ringer_orchestrator_dynamic_env_resolution(self):
        from unittest.mock import patch

        # 1. Default fallback without env vars
        with patch.dict(os.environ, {}, clear=True):
            ringer_default = RingerOrchestrator()
            self.assertEqual(ringer_default.architect_model, "claude-3-5-sonnet")
            self.assertEqual(ringer_default.executor_model, "gemini-3.5-flash")

        # 2. Dynamic environment variable overrides
        with patch.dict(
            os.environ,
            {
                "HOLON_ARCHITECT_MODEL": "custom-arch-model",
                "HOLON_EXECUTOR_MODEL": "custom-exec-model",
            },
        ):
            ringer_env = RingerOrchestrator()
            self.assertEqual(ringer_env.architect_model, "custom-arch-model")
            self.assertEqual(ringer_env.executor_model, "custom-exec-model")

    def test_cli_parser_and_run(self):
        import sys

        from holon_coherence.cli import is_in_container, main

        self.assertIsInstance(is_in_container(), bool)

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
            with self.assertRaises(SystemExit) as cm:
                main()
            self.assertEqual(cm.exception.code, 0)
        finally:
            sys.argv = orig_argv

    def test_cli_init_ca(self):
        import io
        import sys
        from unittest.mock import patch

        from holon_coherence.cli import main

        orig_argv = sys.argv
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                sys.argv = ["holon-coherence", "init-ca", "--output-dir", tmpdir]
                with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
                    main()
                output = mock_out.getvalue()
                self.assertIn("Certificate:", output)
                self.assertIn("Key:", output)
            finally:
                sys.argv = orig_argv

    def test_cli_run_missing_ca_warning(self):
        import io
        import sys
        from unittest.mock import patch

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
                with self.assertRaises(SystemExit) as cm:
                    main()
                self.assertEqual(cm.exception.code, 0)
                self.assertIn("Warning: CA certificate not found", mock_err.getvalue())
        finally:
            sys.argv = orig_argv

    def test_ca_generator_permissions(self):
        import stat

        with tempfile.TemporaryDirectory() as tmpdir:
            _ca_cert, ca_key = generate_root_ca(cert_dir=tmpdir)
            dir_mode = stat.S_IMODE(os.stat(tmpdir).st_mode)
            key_mode = stat.S_IMODE(os.stat(ca_key).st_mode)
            mitm_pem = os.path.join(tmpdir, "mitmproxy-ca.pem")
            mitm_pem_mode = stat.S_IMODE(os.stat(mitm_pem).st_mode)

            self.assertEqual(dir_mode, 0o700)
            self.assertEqual(key_mode, 0o600)
            self.assertEqual(mitm_pem_mode, 0o600)

    def test_hybrid_cache_permissions(self):
        import stat

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = os.path.join(tmpdir, "cache_sub")
            store = HybridCacheStore(cache_dir=cache_dir)
            dir_mode = stat.S_IMODE(os.stat(cache_dir).st_mode)
            db_mode = stat.S_IMODE(os.stat(store.db_path).st_mode)

            self.assertEqual(dir_mode, 0o700)
            self.assertEqual(db_mode, 0o600)

    def test_mitm_wire_log_permissions(self):
        import stat

        from holon_coherence.mitm_addon import _write_transaction_sync

        with tempfile.TemporaryDirectory() as tmpdir:
            wire_dir = os.path.join(tmpdir, "wire_logs_sub")
            sample_record = {"turn_id": 1, "flow_id": "test_flow", "request": {"url": "https://api.openai.com"}}
            _write_transaction_sync(sample_record, wire_dir)

            dir_mode = stat.S_IMODE(os.stat(wire_dir).st_mode)
            self.assertEqual(dir_mode, 0o700)

            turn_file = os.path.join(wire_dir, "turn_1_test_flow.json")
            self.assertTrue(os.path.exists(turn_file))
            self.assertEqual(stat.S_IMODE(os.stat(turn_file).st_mode), 0o600)

            jsonl_file = os.path.join(wire_dir, "transactions.jsonl")
            self.assertTrue(os.path.exists(jsonl_file))
            self.assertEqual(stat.S_IMODE(os.stat(jsonl_file).st_mode), 0o600)

    def test_secret_redaction(self):
        from holon_coherence.mitm_addon import scrub_headers, scrub_payload

        # Standalone auth, credential, credentials, client_secret, refresh_token
        test_payload = {
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

        scrubbed = scrub_payload(test_payload)
        self.assertEqual(scrubbed["auth"], "[REDACTED]")
        self.assertEqual(scrubbed["credential"], "[REDACTED]")
        self.assertEqual(scrubbed["credentials"], "[REDACTED]")
        self.assertEqual(scrubbed["client_secret"], "[REDACTED]")
        self.assertEqual(scrubbed["client-secret"], "[REDACTED]")
        self.assertEqual(scrubbed["refresh_token"], "[REDACTED]")
        self.assertEqual(scrubbed["refresh-token"], "[REDACTED]")
        self.assertEqual(scrubbed["Client_Secret"], "[REDACTED]")
        self.assertEqual(scrubbed["REFRESH_TOKEN"], "[REDACTED]")
        self.assertEqual(scrubbed["AUTH"], "[REDACTED]")
        # Non-credential keys must not be redacted
        self.assertEqual(scrubbed["author"], "John Doe")
        self.assertEqual(scrubbed["authenticity"], "high")
        # Nested list dictionary
        self.assertEqual(scrubbed["nested"][1]["auth"], "[REDACTED]")
        self.assertEqual(scrubbed["nested"][1]["credential"], "[REDACTED]")

        # Headers scrubbing
        test_headers = {
            "Auth": "bearer_abc",
            "Credential": "cred_value",
            "Credentials": "creds_value",
            "Authorization": "Bearer 123",
            "Content-Type": "application/json",
        }
        scrubbed_h = scrub_headers(test_headers)
        self.assertEqual(scrubbed_h["auth"], "[REDACTED]")
        self.assertEqual(scrubbed_h["credential"], "[REDACTED]")
        self.assertEqual(scrubbed_h["credentials"], "[REDACTED]")
        self.assertEqual(scrubbed_h["authorization"], "[REDACTED]")
        self.assertEqual(scrubbed_h["content-type"], "application/json")

    def test_active_optimization_default(self):
        from unittest.mock import patch

        from holon_coherence.mitm_addon import is_passive_monitoring

        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(is_passive_monitoring())

        with patch.dict(os.environ, {"HOLON_PASSIVE_MONITORING": "1"}, clear=True):
            self.assertTrue(is_passive_monitoring())

        with patch.dict(os.environ, {"COHERENCE_TOKEN_REDUCTION": "0"}, clear=True):
            self.assertTrue(is_passive_monitoring())

        with patch.dict(os.environ, {"COHERENCE_TOKEN_REDUCTION": "1", "HOLON_PASSIVE_MONITORING": "0"}, clear=True):
            self.assertFalse(is_passive_monitoring())

    def test_session_wide_tool_deduplication_anthropic(self):
        cleaner = JSONContextCleaner(enable_deduplication=True, max_turns=60)
        status_line = "On branch main\nYour branch is up to date with 'origin/main'.\nnothing to commit\n"
        large_status_output = status_line * 10
        messages = [{"role": "user", "content": "Start session"}]

        # Create a 24-turn conversation simulating repetitive git status runs across turns
        for i in range(1, 23, 2):
            messages.append({"role": "assistant", "content": f"Running step {i}"})
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": f"tool_use_{i}",
                            "content": large_status_output,
                        }
                    ],
                }
            )
        messages.append({"role": "assistant", "content": "Final step"})

        payload = {"messages": messages}
        res = cleaner.process_payload_with_stats(payload, provider="anthropic")
        # Tool outputs in older turns (from turn 4 onwards up to turn 20) should be deduplicated
        self.assertGreaterEqual(res.tool_outputs_omitted, 5)
        self.assertGreater(res.chars_saved, 1000)

        # Invariant: tool_use_id and tool_result structure must be preserved
        cleaned_msgs = res.payload["messages"]
        for msg in cleaned_msgs:
            if isinstance(msg.get("content"), list):
                for block in msg["content"]:
                    if block.get("type") == "tool_result":
                        self.assertIn("tool_use_id", block)
                        self.assertTrue(block["tool_use_id"].startswith("tool_use_"))

    def test_session_wide_tool_deduplication_openai(self):
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
        self.assertGreaterEqual(res.tool_outputs_omitted, 5)

        cleaned_msgs = res.payload["messages"]
        for msg in cleaned_msgs:
            if msg.get("role") == "tool":
                self.assertIn("tool_call_id", msg)
                self.assertTrue(msg["tool_call_id"].startswith("call_"))

    def test_session_wide_tool_deduplication_gemini(self):
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
        self.assertGreaterEqual(res.tool_outputs_omitted, 5)

        # Invariant: functionResponse name is preserved
        cleaned_contents = res.payload["contents"]
        for turn in cleaned_contents:
            for part in turn.get("parts", []):
                if "functionResponse" in part:
                    self.assertEqual(part["functionResponse"]["name"], "list_files")

    def test_throughput_metric_aliases(self):
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

        # Prefill throughput
        val1 = compute_prefill_tps(1000, 2.0)
        val2 = compute_prefill_throughput(1000, 2.0)
        val3 = compute_prompt_prefill_speed(1000, 2.0)
        self.assertEqual(val1, 500.0)
        self.assertEqual(val2, 500.0)
        self.assertEqual(val3, 500.0)

        # Tail prefill throughput
        tval1 = compute_tail_prefill_tps(200, 1.0)
        tval2 = compute_tail_prefill_throughput(200, 1.0)
        tval3 = compute_tail_prefill_speed(200, 1.0)
        self.assertEqual(tval1, 200.0)
        self.assertEqual(tval2, 200.0)
        self.assertEqual(tval3, 200.0)

        # Decode throughput
        dval1 = compute_decode_tps(120, 2.0, streaming=True)
        dval2 = compute_decode_throughput(120, 2.0, streaming=True)
        dval3 = compute_decode_speed(120, 2.0, streaming=True)
        self.assertEqual(dval1, 60.0)
        self.assertEqual(dval2, 60.0)
        self.assertEqual(dval3, 60.0)


if __name__ == "__main__":
    unittest.main()
