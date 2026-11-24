import contextlib
import hashlib
import json
import logging
import os
import re
import sqlite3
import time
from collections.abc import Iterator
from typing import Any

logger = logging.getLogger(__name__)

_ISO_TIMESTAMP_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?")
_UUID_OR_HEX_HASH_PATTERN = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_TASK_OR_RUN_ID_PATTERN = re.compile(r"\b(?:task|run)[-_]\d+\b")


class HybridCacheStore:
    def __init__(  # noqa: PLR0913
        self,
        cache_dir: str | None = None,
        similarity_threshold: float = 0.85,
        candidate_limit: int = 100,
        ttl_seconds: float = 604_800.0,
        prune_interval_seconds: float = 300.0,
        prune_batch_size: int = 5_000,
    ) -> None:
        if cache_dir is None:
            cache_dir = os.path.expanduser("~/.holon/cache")
        os.makedirs(cache_dir, mode=0o700, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(cache_dir, 0o700)

        self.cache_dir = cache_dir
        self.similarity_threshold = similarity_threshold
        self.candidate_limit = candidate_limit
        self.ttl_seconds = float(ttl_seconds)
        self.prune_interval_seconds = float(prune_interval_seconds)
        self.prune_batch_size = int(prune_batch_size)
        self._next_prune_at = 0.0
        self._sweep_count = 0
        self.db_path = os.path.join(cache_dir, "llm_cache.db")
        self._init_db()

    @staticmethod
    def _ensure_shingle_columns_migrated(cursor: sqlite3.Cursor) -> None:
        existing = {row[1] for row in cursor.execute("PRAGMA table_info(prompt_cache)")}
        for column, declaration in (("user_tokens", "TEXT"), ("system_hash", "TEXT")):
            if column not in existing:
                cursor.execute(f"ALTER TABLE prompt_cache ADD COLUMN {column} {declaration}")

    def _init_db(self) -> None:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS prompt_cache (
                    key TEXT PRIMARY KEY,
                    provider TEXT,
                    prompt_normalized TEXT,
                    response_json TEXT,
                    created_at REAL,
                    hit_count INTEGER DEFAULT 0,
                    user_tokens TEXT,
                    system_hash TEXT
                )
                """
            )
            self._ensure_shingle_columns_migrated(cursor)
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_prompt_cache_provider_created "
                "ON prompt_cache (provider, created_at DESC)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_prompt_cache_provider_system_created "
                "ON prompt_cache (provider, system_hash, created_at DESC)"
            )
            conn.commit()
        with contextlib.suppress(OSError):
            os.chmod(self.db_path, 0o600)

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        try:
            conn.execute("PRAGMA busy_timeout=5000;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        return set(re.findall(r"\w+", text.lower()))

    @staticmethod
    def _system_hash(system_prompt: str) -> str:
        return hashlib.sha256(system_prompt.encode()).hexdigest()[:32]

    def _normalized_payload(self, payload: dict[str, Any], provider: str) -> dict[str, Any]:
        try:
            return json.loads(self.normalize_payload(payload, provider))
        except Exception:
            return payload

    @staticmethod
    def _backfill_shingles(conn: sqlite3.Connection, key: str, tokens: str, system_hash: str) -> None:
        conn.execute(
            "UPDATE prompt_cache SET user_tokens = ?, system_hash = ? WHERE key = ?",
            (tokens, system_hash, key),
        )

    def _freshness_clause(self) -> tuple[str, list[float]]:
        if self.ttl_seconds > 0:
            return " AND created_at >= ?", [time.time() - self.ttl_seconds]
        return "", []

    def _prune_expired(self, *, force: bool = False) -> int:
        if self.ttl_seconds <= 0:
            return 0
        monotonic_now = time.monotonic()
        if not force and monotonic_now < self._next_prune_at:
            return 0
        self._next_prune_at = monotonic_now + self.prune_interval_seconds
        self._sweep_count += 1
        wall_clock_cutoff = time.time() - self.ttl_seconds
        removed = 0

        with self._connect() as conn:
            while True:
                keys = [
                    row[0]
                    for row in conn.execute(
                        "SELECT key FROM prompt_cache WHERE created_at < ? LIMIT ?",
                        (wall_clock_cutoff, self.prune_batch_size),
                    )
                ]
                if not keys:
                    break
                placeholders = ",".join("?" * len(keys))
                cursor = conn.execute(f"DELETE FROM prompt_cache WHERE key IN ({placeholders})", keys)
                removed += cursor.rowcount
                conn.commit()
                if len(keys) < self.prune_batch_size:
                    break

        if removed:
            logger.info("Cache TTL sweep removed %d expired entries from %s", removed, self.db_path)
        return removed

    def generate_prefix_key(self, payload: dict[str, Any], provider: str = "anthropic") -> str:
        normalized_str = self.normalize_payload(payload, provider)
        return hashlib.sha256(f"{provider}:{normalized_str}".encode()).hexdigest()

    def normalize_payload(self, payload: dict[str, Any], provider: str = "anthropic") -> str:
        try:
            raw_json = json.dumps(payload, sort_keys=True, default=str)
        except Exception:
            raw_json = str(payload)
        norm = _ISO_TIMESTAMP_PATTERN.sub("<TIMESTAMP>", raw_json)
        norm = _UUID_OR_HEX_HASH_PATTERN.sub("<UUID>", norm)
        return _TASK_OR_RUN_ID_PATTERN.sub("task-<ID>", norm)

    def _extract_cache_key_parts(self, payload: dict[str, Any], max_recent_turns: int = 2) -> tuple[str, str]:
        if not isinstance(payload, dict):
            return str(payload) if payload else "", ""
        cached = getattr(self, "_last_key_parts", None)
        if cached is not None and cached[0] is payload and cached[1] == max_recent_turns:
            return cached[2]
        from holon_coherence.providers import resolve_provider

        provider_format = resolve_provider("", payload)
        result = provider_format.extract_cache_key_parts(payload, max_recent_turns)
        self._last_key_parts = (payload, max_recent_turns, result)
        return result

    def _extract_user_content(self, payload: dict[str, Any], max_recent_turns: int = 2) -> str:
        user_content, _ = self._extract_cache_key_parts(payload, max_recent_turns)
        return user_content

    def _extract_system_prompt(self, payload: dict[str, Any]) -> str:
        _, system_prompt = self._extract_cache_key_parts(payload)
        return system_prompt

    def _lookup_exact_prefix_match(
        self,
        prefix_key: str,
        provider: str,
        fresh_sql: str,
        fresh_args: list[float],
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT response_json FROM prompt_cache WHERE key = ? AND provider = ?{fresh_sql}",
                (prefix_key, provider, *fresh_args),
            )
            row = cursor.fetchone()
            if not row:
                return None
            (resp_json,) = row
            cursor.execute(
                "UPDATE prompt_cache SET hit_count = hit_count + 1 WHERE key = ? AND provider = ?",
                (prefix_key, provider),
            )
            conn.commit()
            logger.info("Exact cache hit for key %s", prefix_key[:10])
            return json.loads(resp_json)

    def _resolve_candidate_shingles(
        self,
        conn: sqlite3.Connection,
        candidate_row: tuple[str, str, str | None, str | None],
    ) -> tuple[set[str], str] | None:
        key, stored_norm, stored_tokens, stored_system_hash = candidate_row
        if stored_tokens is not None and stored_system_hash is not None:
            return set(stored_tokens.split()), stored_system_hash
        try:
            stored_payload = json.loads(stored_norm)
        except Exception:
            return None
        stored_user, stored_sys = self._extract_cache_key_parts(stored_payload)
        stored_token_set = self._tokenize(stored_user)
        resolved_system_hash = self._system_hash(stored_sys)
        self._backfill_shingles(conn, key, " ".join(sorted(stored_token_set)), resolved_system_hash)
        return stored_token_set, resolved_system_hash

    def _lookup_semantic_similarity_match(
        self,
        payload: dict[str, Any],
        provider: str,
        fresh_sql: str,
        fresh_args: list[float],
    ) -> dict[str, Any] | None:
        target_payload = self._normalized_payload(payload, provider)
        target_tokens = self._tokenize(self._extract_user_content(target_payload))
        if not target_tokens:
            return None

        target_system_hash = self._system_hash(self._extract_system_prompt(target_payload))

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT key, prompt_normalized, response_json, user_tokens, system_hash
                FROM prompt_cache
                WHERE provider = ?{fresh_sql}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (provider, *fresh_args, self.candidate_limit),
            )
            rows = cursor.fetchall()

            for key, stored_norm, resp_json, stored_tokens, stored_system_hash in rows:
                resolved = self._resolve_candidate_shingles(
                    conn,
                    (key, stored_norm, stored_tokens, stored_system_hash),
                )
                if resolved is None:
                    continue
                stored_token_set, resolved_system_hash = resolved
                if resolved_system_hash != target_system_hash or not stored_token_set:
                    continue

                intersection = len(target_tokens & stored_token_set)
                union = len(target_tokens | stored_token_set)
                similarity = intersection / union if union > 0 else 0.0

                if similarity >= self.similarity_threshold:
                    cursor.execute(
                        "UPDATE prompt_cache SET hit_count = hit_count + 1 WHERE key = ?",
                        (key,),
                    )
                    conn.commit()
                    logger.info(
                        "Semantic cache hit (similarity=%.2f) for key %s",
                        similarity,
                        key[:10],
                    )
                    return json.loads(resp_json)

        return None

    def get(self, payload: dict[str, Any], provider: str = "anthropic") -> dict[str, Any] | None:
        prefix_key = self.generate_prefix_key(payload, provider)
        fresh_sql, fresh_args = self._freshness_clause()

        exact_match = self._lookup_exact_prefix_match(prefix_key, provider, fresh_sql, fresh_args)
        if exact_match is not None:
            return exact_match

        return self._lookup_semantic_similarity_match(payload, provider, fresh_sql, fresh_args)

    def put(self, payload: dict[str, Any], response: dict[str, Any], provider: str = "anthropic") -> None:
        prefix_key = self.generate_prefix_key(payload, provider)
        norm_prompt = self.normalize_payload(payload, provider)
        normalized = self._normalized_payload(payload, provider)
        user_content, system_prompt = self._extract_cache_key_parts(normalized)
        user_tokens = " ".join(sorted(self._tokenize(user_content)))
        system_hash = self._system_hash(system_prompt)
        resp_json = json.dumps(response, default=str)
        now = time.time()
        self._prune_expired()

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO prompt_cache
                (key, provider, prompt_normalized, response_json, created_at, hit_count,
                 user_tokens, system_hash)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    response_json = excluded.response_json,
                    created_at = excluded.created_at,
                    user_tokens = excluded.user_tokens,
                    system_hash = excluded.system_hash
                """,
                (prefix_key, provider, norm_prompt, resp_json, now, user_tokens, system_hash),
            )
            conn.commit()
            logger.info("Stored response in cache for key %s", prefix_key[:10])

    def clear(self) -> None:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM prompt_cache")
            conn.commit()
