import json
import os
import sqlite3
import stat
import threading
import time
from unittest.mock import patch

import pytest

from holon_coherence import hybrid_cache
from holon_coherence.hybrid_cache import HybridCacheStore


def _payload(text: str, system: str = "You are a coding agent.") -> dict:
    return {"system": system, "messages": [{"role": "user", "content": text}]}


def test_put_stores_precomputed_shingles(tmp_path) -> None:
    store = HybridCacheStore(cache_dir=str(tmp_path))
    store.put(_payload("refactor the parser to use a state machine"), {"content": "ok"}, provider="openai")

    with sqlite3.connect(store.db_path) as conn:
        row = conn.execute("SELECT user_tokens, system_hash FROM prompt_cache").fetchone()

    assert row is not None and row[0] and row[1], "shingles must be written on put"
    assert "refactor" in row[0].split()


def test_semantic_miss_does_not_deserialize_candidates(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    cache_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(cache_dir / "llm_cache.db")) as conn:
        conn.execute(LEGACY_SCHEMA)
        conn.executemany(
            "INSERT INTO prompt_cache (key, provider, prompt_normalized, response_json, created_at, hit_count)"
            " VALUES (?, ?, ?, ?, ?, 0)",
            [(key, provider, norm, resp, time.time()) for key, provider, norm, resp in rows],
        )
        conn.commit()


def test_legacy_database_gains_the_shingle_columns_on_open(tmp_path) -> None:
    _write_legacy_database(tmp_path, [("legacykey1", "openai", json.dumps(_payload("placeholder")), "{}")])

    store = HybridCacheStore(cache_dir=str(tmp_path))

    with sqlite3.connect(store.db_path) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(prompt_cache)")}
    assert {"user_tokens", "system_hash"} <= cols, f"migration did not run: {sorted(cols)}"
    assert store.get(_payload("nothing like the legacy row"), provider="openai") is None


def test_legacy_rows_without_shingles_still_hit_and_are_backfilled(tmp_path) -> None:
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
    store = HybridCacheStore(cache_dir=str(tmp_path))
    errors: list[BaseException] = []
    providers = ["openai", "anthropic", "gemini"]

    def worker(worker_id: int) -> None:
        try:
            prov = providers[worker_id % len(providers)]
            for i in range(10):
                payload = _payload(f"worker {worker_id} request {i} shared token pool")
                store.put(payload, {"content": str(i)}, provider=prov)
                hit = store.get(payload, provider=prov)
                assert hit == {"content": str(i)}
                if i % 3 == 0:
                    store._prune_expired()
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5.0)
        assert not thread.is_alive(), f"thread timed out: {thread}"

    assert not errors, f"concurrent cache access raised: {errors[:3]}"
    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM prompt_cache").fetchone()[0] == 120


def test_sqlite_pragmas_applied_on_every_connection(tmp_path) -> None:
    expected_busy_timeout_ms = 5000
    expected_synchronous_normal = 1
    store = HybridCacheStore(cache_dir=str(tmp_path))
    with store._connect() as conn:
        busy_timeout = conn.execute("PRAGMA busy_timeout;").fetchone()[0]
        journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0].lower()
        synchronous = conn.execute("PRAGMA synchronous;").fetchone()[0]

    assert busy_timeout == expected_busy_timeout_ms
    assert journal_mode == "wal"
    assert synchronous == expected_synchronous_normal


def test_concurrent_prune_and_read_write_interleaving(tmp_path) -> None:  # noqa: C901
    store = HybridCacheStore(cache_dir=str(tmp_path), ttl_seconds=1.0, prune_interval_seconds=0.01, prune_batch_size=5)
    for i in range(20):
        store.put(_payload(f"initial item {i}"), {"val": i}, provider="openai")
    _age_entries(store, 10.0)

    errors: list[BaseException] = []
    stop_event = threading.Event()

    def pruner() -> None:
        try:
            while not stop_event.is_set():
                store._prune_expired(force=True)
                time.sleep(0.005)
        except BaseException as exc:
            errors.append(exc)

    def writer_reader(worker_id: int) -> None:
        try:
            for i in range(15):
                p = _payload(f"worker_{worker_id}_dynamic_{i}")
                store.put(p, {"result": i}, provider="anthropic" if worker_id % 2 == 0 else "gemini")
                store.get(p, provider="anthropic" if worker_id % 2 == 0 else "gemini")
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=pruner) for _ in range(2)]
    threads += [threading.Thread(target=writer_reader, args=(i,)) for i in range(6)]

    for t in threads:
        t.start()
    for t in threads[2:]:
        t.join(timeout=5.0)
        assert not t.is_alive()

    stop_event.set()
    for t in threads[:2]:
        t.join(timeout=5.0)
        assert not t.is_alive()

    assert not errors, f"Errors during concurrent prune/read/write: {errors}"


def test_malformed_payload_normalization_does_not_corrupt_cache(tmp_path) -> None:
    store = HybridCacheStore(cache_dir=str(tmp_path))
    malformed_payloads = [
        {"messages": "not-a-list", "system": 12345},
        {"messages": [None, 42, "string-not-dict", {"role": "invalid"}]},
        {"contents": "not-a-list"},
        {"prompt": None},
        {},
    ]
    for i, p in enumerate(malformed_payloads):
        store.put(p, {"ans": i}, provider="openai")
        res = store.get(p, provider="openai")
        assert res == {"ans": i}

    norm = store.normalize_payload("bare string payload")
    assert isinstance(norm, str)
    assert store._extract_user_content("string") == "string"
    assert store._extract_system_prompt("string") == ""
    assert store.get({"messages": [{"role": "user", "content": "completely different"}]}, provider="openai") is None


def test_connections_are_closed_after_each_operation(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
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


def _age_entries(store: HybridCacheStore, seconds: float) -> None:
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("UPDATE prompt_cache SET created_at = created_at - ?", (seconds,))
        conn.commit()


def test_expired_entry_is_not_served_even_before_a_sweep(tmp_path) -> None:
    store = HybridCacheStore(cache_dir=str(tmp_path), ttl_seconds=60, prune_interval_seconds=10_000)
    store.put(_payload("refactor the parser"), {"content": "stale"}, provider="openai")
    _age_entries(store, 120)

    assert store.get(_payload("refactor the parser"), provider="openai") is None


def test_sweep_removes_expired_rows_and_keeps_fresh_ones(tmp_path) -> None:
    store = HybridCacheStore(cache_dir=str(tmp_path), ttl_seconds=60)
    store.put(_payload("old entry alpha"), {"content": "old"}, provider="openai")
    _age_entries(store, 120)
    store.put(_payload("fresh entry beta"), {"content": "new"}, provider="openai")

    assert store._prune_expired(force=True) == 1

    with sqlite3.connect(store.db_path) as conn:
        remaining = [row[0] for row in conn.execute("SELECT response_json FROM prompt_cache")]
    assert remaining == [json.dumps({"content": "new"})]


def test_sweep_is_time_gated_rather_than_per_write(tmp_path) -> None:
    store = HybridCacheStore(cache_dir=str(tmp_path), ttl_seconds=60, prune_interval_seconds=600)

    for i in range(10):
        store.put(_payload(f"prompt {i} shared words"), {"content": str(i)}, provider="openai")

    assert store._sweep_count == 1, f"expected one gated sweep across 10 writes, saw {store._sweep_count}"


def test_sweep_deletes_in_batches_larger_than_the_batch_size(tmp_path) -> None:
    store = HybridCacheStore(cache_dir=str(tmp_path), ttl_seconds=60, prune_batch_size=3)
    for i in range(10):
        store.put(_payload(f"bulk entry {i} token set"), {"content": str(i)}, provider="openai")
    _age_entries(store, 120)

    assert store._prune_expired(force=True) == 10
    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM prompt_cache").fetchone()[0] == 0


def test_ttl_zero_disables_expiry_entirely(tmp_path) -> None:
    store = HybridCacheStore(cache_dir=str(tmp_path), ttl_seconds=0)
    store.put(_payload("refactor the parser"), {"content": "kept"}, provider="openai")
    _age_entries(store, 10**9)

    assert store.get(_payload("refactor the parser"), provider="openai") == {"content": "kept"}
    assert store._prune_expired(force=True) == 0


def test_sweep_gate_ignores_wall_clock_steps(tmp_path) -> None:
    forward_wall_clock_jump_seconds = 86_400.0
    store = HybridCacheStore(cache_dir=str(tmp_path), ttl_seconds=60, prune_interval_seconds=600)
    store.put(_payload("first shared words"), {"content": "1"}, provider="openai")
    assert store._sweep_count == 1

    real_time = time.time
    with patch(
        "holon_coherence.hybrid_cache.time.time",
        side_effect=lambda: real_time() + forward_wall_clock_jump_seconds,
    ):
        store.put(_payload("second shared words"), {"content": "2"}, provider="openai")

    assert store._sweep_count == 1, "a wall-clock step must not reopen the monotonic sweep gate"


def test_cache_dir_and_sqlite_files_enforce_restrictive_permissions(tmp_path) -> None:
    cache_dir = tmp_path / "private_cache"
    cache_dir.mkdir(mode=0o755)
    os.chmod(cache_dir, 0o755)
    db_file = cache_dir / "llm_cache.db"
    db_file.touch()
    os.chmod(db_file, 0o644)
    for suffix in ("-wal", "-shm"):
        sidecar_path = cache_dir / f"llm_cache.db{suffix}"
        sidecar_path.touch()
        os.chmod(sidecar_path, 0o644)

    store = HybridCacheStore(cache_dir=str(cache_dir))
    store.put(_payload("check permissions on db and sidecars"), {"content": "ok"}, provider="openai")

    assert stat.S_IMODE(os.stat(cache_dir).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(store.db_path).st_mode) == 0o600
    for suffix in ("-wal", "-shm"):
        sidecar = f"{store.db_path}{suffix}"
        if os.path.exists(sidecar):
            assert stat.S_IMODE(os.stat(sidecar).st_mode) == 0o600


def test_put_scrubs_sensitive_credentials_and_headers_before_persisting(tmp_path) -> None:
    store = HybridCacheStore(cache_dir=str(tmp_path))
    anthropic_key = "sk-ant-api03-1234567890abcdefghijklmnop"
    openai_key = "sk-proj-1234567890abcdefghijklmnop"
    resp_key = "sk-proj-responsekey1234567890abcdef"
    payload = {
        "system": "You are a coding agent.",
        "api_key": "raw-api-key-val",
        "headers": {
            "Authorization": "Bearer secret-bearer-val",
            "X-Api-Key": "raw-header-key",
            "Cookie": "session=raw-cookie",
        },
        "messages": [
            {
                "role": "user",
                "content": (f"Use {anthropic_key} and {openai_key} on https://example.test/?token=supersecretval"),
            }
        ],
    }
    response = {
        "content": f"Echoing key {resp_key}",
        "headers": {"Set-Cookie": "sid=raw-sid", "Content-Type": "application/json"},
    }

    store.put(payload, response, provider="anthropic")

    with sqlite3.connect(store.db_path) as conn:
        row = conn.execute("SELECT prompt_normalized, response_json, user_tokens FROM prompt_cache").fetchone()
    assert row is not None
    prompt_normalized, response_json, user_tokens = row
    persisted = f"{prompt_normalized}\n{response_json}\n{user_tokens}"

    for secret in (
        anthropic_key,
        openai_key,
        resp_key,
        "supersecretval",
        "raw-api-key-val",
        "secret-bearer-val",
        "raw-header-key",
        "raw-cookie",
        "raw-sid",
    ):
        assert secret not in persisted

    assert "[REDACTED]" in prompt_normalized
    assert "[REDACTED_SECRET]" in prompt_normalized
    assert "[REDACTED]" in response_json
    assert "[REDACTED_SECRET]" in response_json

    hit = store.get(payload, provider="anthropic")
    assert hit is not None
    assert hit["headers"]["set-cookie"] == "[REDACTED]"
    assert "[REDACTED_SECRET]" in hit["content"]
    assert resp_key not in json.dumps(hit)


def test_unused_provider_system_created_index_is_dropped(tmp_path) -> None:
    fresh_store = HybridCacheStore(cache_dir=str(tmp_path / "fresh"))
    with sqlite3.connect(fresh_store.db_path) as conn:
        fresh_indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert "idx_prompt_cache_provider_created" in fresh_indexes
    assert "idx_prompt_cache_provider_system_created" not in fresh_indexes

    migrated_dir = tmp_path / "migrated"
    migrated_dir.mkdir()
    db_path = migrated_dir / "llm_cache.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE prompt_cache (
                key TEXT PRIMARY KEY, provider TEXT, prompt_normalized TEXT,
                response_json TEXT, created_at REAL, hit_count INTEGER DEFAULT 0,
                user_tokens TEXT, system_hash TEXT
            )
            """
        )
        conn.execute(
            "CREATE INDEX idx_prompt_cache_provider_system_created "
            "ON prompt_cache (provider, system_hash, created_at DESC)"
        )
        conn.commit()

    migrated_store = HybridCacheStore(cache_dir=str(migrated_dir))
    with sqlite3.connect(migrated_store.db_path) as conn:
        migrated_indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert "idx_prompt_cache_provider_created" in migrated_indexes
    assert "idx_prompt_cache_provider_system_created" not in migrated_indexes


def test_put_normalizes_payload_only_once(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = HybridCacheStore(cache_dir=str(tmp_path))
    calls = 0
    original = HybridCacheStore.normalize_payload

    def counting(self, payload, provider="anthropic"):
        nonlocal calls
        calls += 1
        return original(self, payload, provider)

    monkeypatch.setattr(HybridCacheStore, "normalize_payload", counting)
    store.put(_payload("single normalization check"), {"content": "ok"}, provider="openai")

    assert calls == 1
