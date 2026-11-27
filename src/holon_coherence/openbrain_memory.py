import contextlib
import json
import logging
import os
import sqlite3
import time
from typing import Any

logger = logging.getLogger(__name__)


class OpenBrainMemory:
    def __init__(self, db_dir: str | None = None):
        if db_dir is None:
            db_dir = os.path.expanduser("~/.holon/openbrain")
        os.makedirs(db_dir, exist_ok=True)

        self.db_path = os.path.join(db_dir, "openbrain.db")
        self._init_db()

    def _init_db(self) -> None:
        with contextlib.closing(sqlite3.connect(self.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT,
                    category TEXT,
                    content TEXT,
                    metadata_json TEXT,
                    created_at REAL
                )
                """
            )
            conn.commit()

    def store_memory(
        self,
        topic: str,
        content: str,
        category: str = "lesson_learned",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        meta_str = json.dumps(metadata or {}, default=str)
        now = time.time()

        try:
            with contextlib.closing(sqlite3.connect(self.db_path)) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO memories (topic, category, content, metadata_json, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (topic, category, content, meta_str, now),
                )
                conn.commit()
                return cursor.lastrowid or 0
        except sqlite3.Error as exc:
            logger.error("Failed to store memory in OpenBrain database: %s", exc)
            return -1

    def fetch_memories(
        self, topic: str | None = None, category: str | None = None, limit: int = 10
    ) -> list[dict[str, Any]]:
        query = "SELECT id, topic, category, content, metadata_json, created_at FROM memories WHERE 1=1"
        params: list[Any] = []

        if topic:
            query += " AND topic LIKE ?"
            params.append(f"%{topic}%")

        if category:
            query += " AND category = ?"
            params.append(category)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        results = []
        with contextlib.closing(sqlite3.connect(self.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()

            for mem_id, top, cat, cont, meta_str, created_at in rows:
                results.append(
                    {
                        "id": mem_id,
                        "topic": top,
                        "category": cat,
                        "content": cont,
                        "metadata": json.loads(meta_str or "{}"),
                        "created_at": created_at,
                    }
                )

        return results

    retrieve_memories = fetch_memories

    def format_memory_context(self, topic: str | None = None, limit: int = 5) -> str:
        memories = self.fetch_memories(topic=topic, limit=limit)
        if not memories:
            return ""

        lines = ["### 🧠 OpenBrain Episodic Memories & Rules\n"]
        for m in memories:
            lines.append(f"- **[{m['category'].upper()}] ({m['topic']})**: {m['content']}")

        return "\n".join(lines)
