from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import Optional
import json


class CacheService:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self._init()

    def _init(self) -> None:
        c = self.conn.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS file_cache (
                path TEXT PRIMARY KEY,
                mtime REAL,
                metadata TEXT
            )
            """
        )
        self.conn.commit()

    def get(self, path: str) -> Optional[dict]:
        c = self.conn.cursor()
        c.execute("SELECT metadata FROM file_cache WHERE path = ?", (path,))
        row = c.fetchone()
        if not row:
            return None
        return json.loads(row[0])

    def set(self, path: str, mtime: float, metadata: dict) -> None:
        c = self.conn.cursor()
        c.execute(
            "REPLACE INTO file_cache(path, mtime, metadata) VALUES (?, ?, ?)",
            (path, mtime, json.dumps(metadata)),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


__all__ = ["CacheService"]
