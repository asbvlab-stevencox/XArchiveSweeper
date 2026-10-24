"""Resumable SQLite state: which posts are done, failed or skipped."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts(
  id TEXT PRIMARY KEY, status TEXT NOT NULL, detail TEXT, updated REAL);
CREATE TABLE IF NOT EXISTS daily(day TEXT PRIMARY KEY, count INTEGER NOT NULL);
"""


class State:
    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(str(path))
        self.db.executescript(SCHEMA)

    def status(self, pid: str) -> str | None:
        r = self.db.execute("SELECT status FROM posts WHERE id=?", (pid,)).fetchone()
        return r[0] if r else None

    def mark(self, pid: str, status: str, detail: str = "") -> None:
        self.db.execute(
            "INSERT INTO posts VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "status=excluded.status, detail=excluded.detail, updated=excluded.updated",
            (pid, status, detail, time.time()))
        self.db.commit()

    def counts(self) -> dict[str, int]:
        return dict(self.db.execute("SELECT status, COUNT(*) FROM posts GROUP BY status"))

    def today(self) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime())

    def used_today(self) -> int:
        r = self.db.execute("SELECT count FROM daily WHERE day=?", (self.today(),)).fetchone()
        return r[0] if r else 0

    def bump_today(self) -> None:
        self.db.execute(
            "INSERT INTO daily VALUES(?,1) ON CONFLICT(day) DO UPDATE SET count=count+1",
            (self.today(),))
        self.db.commit()

    def close(self) -> None:
        self.db.close()
