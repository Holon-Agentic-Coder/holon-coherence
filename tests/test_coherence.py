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


if __name__ == "__main__":
    unittest.main()
