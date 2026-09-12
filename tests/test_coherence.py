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
                "import os; assert os.environ['HTTP_PROXY'] == 'http://127.0.0.1:8080'",
            ]
            with self.assertRaises(SystemExit) as cm:
                main()
            self.assertEqual(cm.exception.code, 0)
        finally:
            sys.argv = orig_argv


if __name__ == "__main__":
    unittest.main()
