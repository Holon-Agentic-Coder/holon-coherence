"""Disk-backed hybrid & semantic caching layer for LLM prompts."""

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


class HybridCacheStore:
    """Hybrid exact prefix tree and semantic local cache store for LLM responses."""

    def __init__(  # noqa: PLR0913
        self,
        cache_dir: str | None = None,
        similarity_threshold: float = 0.85,
        candidate_limit: int = 100,
        ttl_seconds: float = 604_800.0,
        prune_interval_seconds: float = 300.0,
        prune_batch_size: int = 5_000,
    ) -> None:
        """Initialize HybridCacheStore.

        Args:
            cache_dir: Directory path for SQLite storage. Defaults to ~/.holon/cache.
            similarity_threshold: Jaccard similarity score threshold (0.0 to 1.0) required for a semantic match hit.
            candidate_limit: Maximum number of recent candidate cache entries to consider for semantic search.
            ttl_seconds: Age after which an entry is expired and swept. ``0`` disables expiry.
            prune_interval_seconds: Minimum interval between TTL sweeps, so writes do not each pay
                for a scan of the table.
            prune_batch_size: Rows deleted per DELETE, bounding the length of a write lock.
        """
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
            # Migrate first: the index below references system_hash, which does not exist on a
            # database written before the shingle columns were introduced.
            existing = {row[1] for row in cursor.execute("PRAGMA table_info(prompt_cache)")}
            for column, declaration in (("user_tokens", "TEXT"), ("system_hash", "TEXT")):
                if column not in existing:
                    cursor.execute(f"ALTER TABLE prompt_cache ADD COLUMN {column} {declaration}")
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
        """Open a connection carrying the pragmas every reader and writer needs.

        ``with sqlite3.connect(...)`` commits on exit but never *closes*, so every cache call left a
        connection holding a WAL read snapshot. It is closed here, and ``busy_timeout`` is set on the
        connection rather than relying on the connect() timeout argument alone.
        """
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
        """Lowercase word tokens, the same set the similarity score has always used."""
        return set(re.findall(r"\w+", text.lower()))

    @staticmethod
    def _system_hash(system_prompt: str) -> str:
        """Stable digest of the system prompt, so candidate rows are compared without parsing payloads."""
        return hashlib.sha256(system_prompt.encode()).hexdigest()[:32]

    def _normalized_payload(self, payload: dict[str, Any], provider: str) -> dict[str, Any]:
        """Transient-stripped payload as a dict, falling back to the original on a bad round-trip."""
        try:
            return json.loads(self.normalize_payload(payload, provider))
        except Exception:
            return payload

    @staticmethod
    def _backfill_shingles(conn: sqlite3.Connection, key: str, tokens: str, system_hash: str) -> None:
        """Write derived shingles onto a legacy row so the next miss skips the expensive path."""
        conn.execute(
            "UPDATE prompt_cache SET user_tokens = ?, system_hash = ? WHERE key = ?",
            (tokens, system_hash, key),
        )

    def _freshness_clause(self) -> tuple[str, list[float]]:
        """SQL fragment and argument excluding entries past their TTL.

        Reading through the sweep matters as much as running it: between sweeps an expired entry is
        still physically present, and serving it would make the TTL advisory rather than a bound.
        """
        if self.ttl_seconds > 0:
            return " AND created_at >= ?", [time.time() - self.ttl_seconds]
        return "", []

    def _prune_expired(self, *, force: bool = False) -> int:
        """Delete expired entries in bounded batches, at most once per ``prune_interval_seconds``.

        The sweep is time-gated rather than per-write: a proxy run performs many writes, and a full
        scan on each one is the write amplification this cache should not have. Batching selects the
        keys first and deletes by id, because ``DELETE ... WHERE key IN (SELECT ... LIMIT n)`` needs
        a SQLite build with update/delete limits enabled.

        Returns:
            int: Rows removed; ``0`` when expiry is disabled or no sweep was due.
        """
        if self.ttl_seconds <= 0:
            return 0
        # The sweep gate is an in-process interval, so it runs on the monotonic clock; the cutoff is
        # compared with persisted epoch ``created_at`` values, so it stays on wall-clock time.
        tick = time.monotonic()
        if not force and tick < self._next_prune_at:
            return 0
        self._next_prune_at = tick + self.prune_interval_seconds
        self._sweep_count += 1
        cutoff = time.time() - self.ttl_seconds
        removed = 0

        with self._connect() as conn:
            while True:
                keys = [
                    row[0]
                    for row in conn.execute(
                        "SELECT key FROM prompt_cache WHERE created_at < ? LIMIT ?",
                        (cutoff, self.prune_batch_size),
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
        """Generates a stable prefix-tree hash key from the payload system and message turns."""
        normalized_str = self.normalize_payload(payload, provider)
        return hashlib.sha256(f"{provider}:{normalized_str}".encode()).hexdigest()

    def normalize_payload(self, payload: dict[str, Any], provider: str = "anthropic") -> str:
        """Normalizes payload by stripping transient variables like timestamps, run IDs, and temporary tokens."""
        try:
            raw_json = json.dumps(payload, sort_keys=True, default=str)
        except Exception:
            raw_json = str(payload)
        # Strip ISO timestamps
        norm = re.sub(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?",
            "<TIMESTAMP>",
            raw_json,
        )
        # Strip UUIDs / hexadecimal run hashes
        norm = re.sub(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
            "<UUID>",
            norm,
        )
        # Strip random digits in task IDs / run IDs
        norm = re.sub(r"\b(?:task|run)[-_]\d+\b", "task-<ID>", norm)
        return norm

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
        """Extracts user message content specifically to avoid system prompt and JSON key token pollution.
        Prioritizes the most recent user turns to prevent long conversation history token dilution.
        """
        user_content, _ = self._extract_cache_key_parts(payload, max_recent_turns)
        return user_content

    def _extract_system_prompt(self, payload: dict[str, Any]) -> str:
        """Extracts normalized system instructions from Anthropic/Gemini/OpenAI payload schemas."""
        _, system_prompt = self._extract_cache_key_parts(payload)
        return system_prompt

    def get(self, payload: dict[str, Any], provider: str = "anthropic") -> dict[str, Any] | None:
        """Looks up cached response by exact prefix match or semantic similarity match.

        Returns:
            dict[str, Any] | None: Cached response JSON payload if match found, else None.
        """
        prefix_key = self.generate_prefix_key(payload, provider)

        # 1. Exact Prefix Matching
        fresh_sql, fresh_args = self._freshness_clause()
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT response_json FROM prompt_cache WHERE key = ? AND provider = ?{fresh_sql}",
                (prefix_key, provider, *fresh_args),
            )
            row = cursor.fetchone()
            if row:
                (resp_json,) = row
                cursor.execute(
                    "UPDATE prompt_cache SET hit_count = hit_count + 1 WHERE key = ? AND provider = ?",
                    (prefix_key, provider),
                )
                conn.commit()
                logger.info("Exact cache hit for key %s", prefix_key[:10])
                return json.loads(resp_json)

        # 2. Semantic Similarity Matching
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
                if stored_tokens is None or stored_system_hash is None:
                    # Rows written before shingles existed: derive once, backfill, then evaluate.
                    try:
                        stored_payload = json.loads(stored_norm)
                    except Exception:
                        continue
                    stored_user, stored_sys = self._extract_cache_key_parts(stored_payload)
                    stored_token_set = self._tokenize(stored_user)
                    stored_system_hash = self._system_hash(stored_sys)
                    self._backfill_shingles(conn, key, " ".join(sorted(stored_token_set)), stored_system_hash)
                else:
                    stored_token_set = set(stored_tokens.split())

                # Require exact match on system prompt before evaluating user turn similarity
                if stored_system_hash != target_system_hash or not stored_token_set:
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

    def put(self, payload: dict[str, Any], response: dict[str, Any], provider: str = "anthropic") -> None:
        """Stores a prompt payload and LLM response in the cache store."""
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
        """Clears all entries from the cache store."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM prompt_cache")
            conn.commit()
