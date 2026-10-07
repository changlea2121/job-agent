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
);
CREATE TABLE IF NOT EXISTS runs (
    id         INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL        -- ISO 8601 UTC, recorded before fetching
);
"""


def utc_iso(dt: datetime | None = None) -> str:
    """Fixed-width UTC timestamp, so stored values compare as strings."""
    dt = dt or datetime.now(timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds")


class JobStore:
    def __init__(self, path: str | Path = "jobs.db"):
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def insert_new(self, jobs: Iterable[Job], now: datetime | None = None) -> int:
        """Insert jobs not already stored; return how many were new."""
        seen_at = utc_iso(now)
        rows = [
            (
                j.source, j.company, j.source_id, j.title, j.location, j.url,
                j.description, j.category,
                j.first_published.isoformat() if j.first_published else None,
                seen_at,
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

    def record_run(self, now: datetime | None = None) -> str:
        """Record the start of a fetch run; return its timestamp."""
        started_at = utc_iso(now)
        with self.conn:
            self.conn.execute("INSERT INTO runs (started_at) VALUES (?)", (started_at,))
        return started_at

    def latest_run(self) -> str | None:
        row = self.conn.execute(
            "SELECT started_at FROM runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else None

    def jobs_since(self, since: str) -> list[Job]:
        """Jobs first seen at or after `since` (a `utc_iso` timestamp)."""
        rows = self.conn.execute(
            "SELECT source, company, source_id, title, location, url, description,"
            " category, first_published FROM jobs WHERE first_seen_at >= ?"
            " ORDER BY company, title",
            (since,),
        )
        return [
            Job(*row[:8], first_published=datetime.fromisoformat(row[8]) if row[8] else None)
            for row in rows
        ]

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

    def close(self) -> None:
        self.conn.close()
