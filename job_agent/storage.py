import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from .models import Job

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    source          TEXT NOT NULL,
    company         TEXT NOT NULL,
    source_id       TEXT NOT NULL,
    title           TEXT NOT NULL,
    location        TEXT NOT NULL,
    url             TEXT NOT NULL,
    description     TEXT NOT NULL,
    category        TEXT,
    first_published TEXT,           -- ISO 8601 from the source
    first_seen_at   TEXT NOT NULL,  -- ISO 8601 UTC, set when we first insert
    PRIMARY KEY (source, company, source_id)
)
"""


class JobStore:
    def __init__(self, path: str | Path = "jobs.db"):
        self.conn = sqlite3.connect(path)
        self.conn.execute(SCHEMA)
        self.conn.commit()

    def insert_new(self, jobs: Iterable[Job]) -> int:
        """Insert jobs not already stored; return how many were new."""
        now = datetime.now(timezone.utc).isoformat()
        rows = [
            (
                j.source, j.company, j.source_id, j.title, j.location, j.url,
                j.description, j.category,
                j.first_published.isoformat() if j.first_published else None,
                now,
            )
            for j in jobs
        ]
        before = self.conn.total_changes
        with self.conn:
            self.conn.executemany(
                "INSERT OR IGNORE INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        return self.conn.total_changes - before

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

    def close(self) -> None:
        self.conn.close()
