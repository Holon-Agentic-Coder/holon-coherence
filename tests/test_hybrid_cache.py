"""Tests for HybridCacheStore shingle storage, migration and concurrency (Bean 0072)."""

import json
import sqlite3
import threading

import pytest

from holon_coherence import hybrid_cache
from holon_coherence.hybrid_cache import HybridCacheStore


def _payload(text: str, system: str = "You are a coding agent.") -> dict:
    return {"system": system, "messages": [{"role": "user", "content": text}]}


def test_put_stores_precomputed_shingles(tmp_path) -> None:
    """A write must record the tokens and system hash the next miss will compare against."""
    store = HybridCacheStore(cache_dir=str(tmp_path))
    store.put(_payload("refactor the parser to use a state machine"), {"content": "ok"}, provider="openai")

    with sqlite3.connect(store.db_path) as conn:
        row = conn.execute("SELECT user_tokens, system_hash FROM prompt_cache").fetchone()

    assert row is not None and row[0] and row[1], "shingles must be written on put"
    assert "refactor" in row[0].split()


def test_semantic_miss_does_not_deserialize_candidates(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PERF-01: a miss used to re-parse and re-tokenize up to `candidate_limit` stored payloads.

    Instrumenting the extractor is the honest way to pin this: with shingles present the scan may
    touch the extractor exactly once (for the incoming payload) no matter how many rows are stored.
    """
    store = HybridCacheStore(cache_dir=str(tmp_path), candidate_limit=100)
    for i in range(40):
        store.put(_payload(f"unrelated cached transaction {i} alpha beta"), {"content": str(i)}, provider="openai")

    calls = []
    original = HybridCacheStore._extract_user_content

    def counting(self, payload, *args, **kwargs):
        calls.append(payload)
        return original(self, payload, *args, **kwargs)

    monkeypatch.setattr(HybridCacheStore, "_extract_user_content", counting)
    assert store.get(_payload("completely different question zeta eta theta"), provider="openai") is None
    monkeypatch.undo()

    assert len(calls) == 1, f"semantic scan re-derived {len(calls) - 1} stored payloads; expected 0"


def test_semantic_hit_still_works_with_shingles(tmp_path) -> None:
    store = HybridCacheStore(cache_dir=str(tmp_path))
    store.put(_payload("refactor the parser to use a state machine"), {"content": "cached"}, provider="openai")

    hit = store.get(_payload("refactor the parser to use a state machine please"), provider="openai")

    assert hit == {"content": "cached"}


def test_semantic_hit_requires_same_system_prompt(tmp_path) -> None:
    store = HybridCacheStore(cache_dir=str(tmp_path))
    store.put(_payload("refactor the parser", system="You are a pirate."), {"content": "arr"}, provider="openai")

    assert store.get(_payload("refactor the parser", system="You are a reviewer."), provider="openai") is None


LEGACY_SCHEMA = """
CREATE TABLE prompt_cache (
    key TEXT PRIMARY KEY, provider TEXT, prompt_normalized TEXT,
    response_json TEXT, created_at REAL, hit_count INTEGER DEFAULT 0
)
"""


def _write_legacy_database(cache_dir, rows: list[tuple[str, str, str]]) -> None:
    """Write a pre-shingles cache file so the store's own migration is what we exercise."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(cache_dir / "llm_cache.db")) as conn:
        conn.execute(LEGACY_SCHEMA)
        conn.executemany(
            "INSERT INTO prompt_cache (key, provider, prompt_normalized, response_json, created_at, hit_count)"
            " VALUES (?, ?, ?, ?, 1.0, 0)",
            rows,
        )
        conn.commit()


def test_legacy_database_gains_the_shingle_columns_on_open(tmp_path) -> None:
    """Migration has to run against an existing file, not only a freshly created one."""
    _write_legacy_database(tmp_path, [("legacykey1", "openai", json.dumps(_payload("placeholder")), "{}")])

    store = HybridCacheStore(cache_dir=str(tmp_path))

    with sqlite3.connect(store.db_path) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(prompt_cache)")}
    assert {"user_tokens", "system_hash"} <= cols, f"migration did not run: {sorted(cols)}"
    assert store.get(_payload("nothing like the legacy row"), provider="openai") is None


def test_legacy_rows_without_shingles_still_hit_and_are_backfilled(tmp_path) -> None:
    """An old row must still produce a semantic hit, and must gain shingles on the way."""
    payload = _payload("refactor the parser to use a state machine")
    _write_legacy_database(
        tmp_path,
        [("legacykey1", "openai", json.dumps(payload), json.dumps({"content": "legacy"}))],
    )
    store = HybridCacheStore(cache_dir=str(tmp_path))

    assert store.get(payload, provider="openai") == {"content": "legacy"}

    with sqlite3.connect(store.db_path) as conn:
        tokens = conn.execute("SELECT user_tokens FROM prompt_cache WHERE key = 'legacykey1'").fetchone()[0]
    assert tokens and "parser" in tokens.split(), "legacy row should be backfilled on read"


def test_concurrent_writers_and_readers_do_not_error(tmp_path) -> None:
    """WAL plus an explicit busy_timeout must absorb parallel agent workloads without OperationalError."""
    store = HybridCacheStore(cache_dir=str(tmp_path))
    errors: list[BaseException] = []

    def worker(worker_id: int) -> None:
        try:
            for i in range(10):
                store.put(
                    _payload(f"worker {worker_id} request {i} shared token pool"),
                    {"content": str(i)},
                    provider="openai",
                )
                store.get(_payload(f"worker {worker_id} request {i} shared token pool"), provider="openai")
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, f"concurrent cache access raised: {errors[:3]}"
    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM prompt_cache").fetchone()[0] == 80


def test_connections_are_closed_after_each_operation(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`with sqlite3.connect(...)` commits but never closes; a leaked handle pins a WAL snapshot."""
    opened: list[sqlite3.Connection] = []
    real_connect = sqlite3.connect

    def tracking_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        opened.append(conn)
        return conn

    monkeypatch.setattr(hybrid_cache.sqlite3, "connect", tracking_connect)
    store = HybridCacheStore(cache_dir=str(tmp_path))
    store.put(_payload("some prompt"), {"content": "x"}, provider="openai")
    store.get(_payload("some prompt"), provider="openai")

    assert opened, "expected the store to open connections"
    for conn in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")
