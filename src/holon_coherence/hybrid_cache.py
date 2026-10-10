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

    def __init__(
        self,
        cache_dir: str | None = None,
        similarity_threshold: float = 0.85,
        candidate_limit: int = 100,
    ) -> None:
        """Initialize HybridCacheStore.

        Args:
            cache_dir: Directory path for SQLite storage. Defaults to ~/.holon/cache.
            similarity_threshold: Jaccard similarity score threshold (0.0 to 1.0) required for a semantic match hit.
            candidate_limit: Maximum number of recent candidate cache entries to consider for semantic search.
        """
        if cache_dir is None:
            cache_dir = os.path.expanduser("~/.holon/cache")
        os.makedirs(cache_dir, mode=0o700, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(cache_dir, 0o700)

        self.cache_dir = cache_dir
        self.similarity_threshold = similarity_threshold
        self.candidate_limit = candidate_limit
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

    def generate_prefix_key(self, payload: dict[str, Any], provider: str = "anthropic") -> str:
        """Generates a stable prefix-tree hash key from the payload system and message turns."""
        normalized_str = self.normalize_payload(payload, provider)
        return hashlib.sha256(f"{provider}:{normalized_str}".encode()).hexdigest()

    def normalize_payload(self, payload: dict[str, Any], provider: str = "anthropic") -> str:
        """Normalizes payload by stripping transient variables like timestamps, run IDs, and temporary tokens."""
        raw_json = json.dumps(payload, sort_keys=True)
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

    def _extract_user_content(self, payload: dict[str, Any], max_recent_turns: int = 2) -> str:
        """Extracts user message content specifically to avoid system prompt and JSON key token pollution.
        Prioritizes the most recent user turns to prevent long conversation history token dilution.
        """

        def _extract_item_text(item: Any) -> list[str]:
            texts: list[str] = []
            if isinstance(item, str):
                texts.append(item)
            elif isinstance(item, dict):
                if "text" in item and isinstance(item["text"], str):
                    texts.append(item["text"])
                if item.get("type") == "tool_result":
                    tr_content = item.get("content")
                    if isinstance(tr_content, str):
                        texts.append(tr_content)
                    elif isinstance(tr_content, list):
                        for sub in tr_content:
                            texts.extend(_extract_item_text(sub))
                    elif isinstance(tr_content, dict):
                        texts.extend(_extract_item_text(tr_content))
            return texts

        user_texts = []
        messages = payload.get("messages")
        if isinstance(messages, list):
            user_msgs = [msg for msg in messages if isinstance(msg, dict) and msg.get("role") == "user"]
            recent_msgs = user_msgs[-max_recent_turns:] if max_recent_turns > 0 else user_msgs
            for msg in recent_msgs:
                content = msg.get("content")
                if isinstance(content, str):
                    user_texts.append(content)
                elif isinstance(content, list):
                    for item in content:
                        extracted = _extract_item_text(item)
                        if extracted:
                            user_texts.extend(extracted)
                        elif isinstance(item, str):
                            user_texts.append(item)
                elif isinstance(content, dict):
                    extracted = _extract_item_text(content)
                    if extracted:
                        user_texts.extend(extracted)
                elif content is not None:
                    user_texts.append(json.dumps(content))
        contents = payload.get("contents")
        if isinstance(contents, list):
            user_turns = [
                turn for turn in contents if isinstance(turn, dict) and turn.get("role") in ("user", None, "")
            ]
            recent_turns = user_turns[-max_recent_turns:] if max_recent_turns > 0 else user_turns
            for turn in recent_turns:
                parts = turn.get("parts")
                if isinstance(parts, list):
                    for part in parts:
                        extracted = _extract_item_text(part)
                        if extracted:
                            user_texts.extend(extracted)
                        elif isinstance(part, str):
                            user_texts.append(part)
        if not user_texts and "prompt" in payload and isinstance(payload["prompt"], str):
            user_texts.append(payload["prompt"])
        return " ".join(user_texts)

    def _extract_system_prompt(self, payload: dict[str, Any]) -> str:
        """Extracts normalized system instructions from Anthropic/Gemini/OpenAI payload schemas."""
        system_texts: list[str] = []

        # 1. Top-level 'system' or 'system_instruction' field (Anthropic/Gemini)
        system_val = payload.get("system") or payload.get("system_instruction")
        if system_val is not None:
            if isinstance(system_val, str):
                system_texts.append(system_val)
            elif isinstance(system_val, list):
                for item in system_val:
                    if isinstance(item, str):
                        system_texts.append(item)
                    elif isinstance(item, dict) and "text" in item and isinstance(item["text"], str):
                        system_texts.append(item["text"])
            elif isinstance(system_val, dict):
                if "text" in system_val and isinstance(system_val["text"], str):
                    system_texts.append(system_val["text"])
                elif "parts" in system_val and isinstance(system_val["parts"], list):
                    for part in system_val["parts"]:
                        if isinstance(part, dict) and "text" in part and isinstance(part["text"], str):
                            system_texts.append(part["text"])

        # 2. System messages in 'messages' array (OpenAI schema)
        messages = payload.get("messages")
        if isinstance(messages, list):
            for msg in messages:
                if isinstance(msg, dict) and msg.get("role") == "system":
                    content = msg.get("content")
                    if isinstance(content, str):
                        system_texts.append(content)
                    elif isinstance(content, list):
                        for item in content:
                            if isinstance(item, str):
                                system_texts.append(item)
                            elif isinstance(item, dict) and "text" in item and isinstance(item["text"], str):
                                system_texts.append(item["text"])

        return " ".join(system_texts).strip()

    def get(self, payload: dict[str, Any], provider: str = "anthropic") -> dict[str, Any] | None:
        """Looks up cached response by exact prefix match or semantic similarity match.

        Returns:
            dict[str, Any] | None: Cached response JSON payload if match found, else None.
        """
        prefix_key = self.generate_prefix_key(payload, provider)

        # 1. Exact Prefix Matching
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT response_json FROM prompt_cache WHERE key = ? AND provider = ?",
                (prefix_key, provider),
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
                """
                SELECT key, prompt_normalized, response_json, user_tokens, system_hash
                FROM prompt_cache
                WHERE provider = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (provider, self.candidate_limit),
            )
            rows = cursor.fetchall()

            for key, stored_norm, resp_json, stored_tokens, stored_system_hash in rows:
                if stored_tokens is None or stored_system_hash is None:
                    # Rows written before shingles existed: derive once, backfill, then evaluate.
                    try:
                        stored_payload = json.loads(stored_norm)
                    except Exception:
                        continue
                    stored_token_set = self._tokenize(self._extract_user_content(stored_payload))
                    stored_system_hash = self._system_hash(self._extract_system_prompt(stored_payload))
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
        user_tokens = " ".join(sorted(self._tokenize(self._extract_user_content(normalized))))
        system_hash = self._system_hash(self._extract_system_prompt(normalized))
        resp_json = json.dumps(response)
        now = time.time()

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
