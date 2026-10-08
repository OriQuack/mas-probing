"""SQLite store for tool results and paid-backend credits, shared by all runs and processes.

Results are keyed by exact query/URL and **frozen on first success**: a later fetch of the same key never
overwrites it, so every run that restores a checkpoint sees identical search results and page text.
Failures are never cached (the next call retries live).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS results (
    kind TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, backend TEXT, created_at REAL NOT NULL,
    PRIMARY KEY (kind, key)
);
CREATE TABLE IF NOT EXISTS leases (
    token TEXT PRIMARY KEY, backend TEXT NOT NULL, started REAL NOT NULL, expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS starts (backend TEXT NOT NULL, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS credits (
    backend TEXT PRIMARY KEY, remaining INTEGER NOT NULL, synced_at REAL NOT NULL, used_since_sync INTEGER NOT NULL
);
"""


class ToolCache:
    def __init__(self, path: Path | str):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False, timeout=60, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)

    # -- results -----------------------------------------------------------------------------
    def get(self, kind: str, key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT value FROM results WHERE kind=? AND key=?", (kind, key)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, kind: str, key: str, value: dict[str, Any], backend: str | None = None) -> dict[str, Any]:
        """Insert unless present; return the stored value (the first writer wins a race)."""
        with self._lock:
            self._db.execute(
                "INSERT OR IGNORE INTO results (kind, key, value, backend, created_at) VALUES (?, ?, ?, ?, ?)",
                (kind, key, json.dumps(value), backend, time.time()),
            )
            row = self._db.execute("SELECT value FROM results WHERE kind=? AND key=?", (kind, key)).fetchone()
        return json.loads(row[0])

    # -- credits -----------------------------------------------------------------------------
    def credits(self, backend: str) -> tuple[int, float, int] | None:
        """(remaining at last sync, sync time, calls charged since) or None if never synced."""
        with self._lock:
            return self._db.execute(
                "SELECT remaining, synced_at, used_since_sync FROM credits WHERE backend=?", (backend,)
            ).fetchone()

    def sync_credits(self, backend: str, remaining: int) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO credits (backend, remaining, synced_at, used_since_sync) VALUES (?, ?, ?, 0)",
                (backend, remaining, time.time()),
            )

    def charge(self, backend: str, n: int = 1) -> None:
        with self._lock:
            self._db.execute("UPDATE credits SET used_since_sync = used_since_sync + ? WHERE backend=?", (n, backend))

    # -- cross-process rate limits -----------------------------------------------------------
    def acquire(self, backend: str, concurrent: int, per_min: int, max_wait_s: float,
                lease_s: float) -> tuple[str | None, float]:
        """Wait (up to max_wait_s) for a slot: fewer than `concurrent` leases in flight AND fewer than `per_min`
        starts in the last 60 s, counted across every process using this database. Returns (token, waited_s);
        token None means no slot in time. Leases expire after lease_s, so a crashed process cannot hold one."""
        import uuid

        t0 = time.monotonic()
        while True:
            now = time.time()
            with self._lock:
                try:
                    self._db.execute("BEGIN IMMEDIATE")
                    self._db.execute("DELETE FROM leases WHERE expires < ?", (now,))
                    self._db.execute("DELETE FROM starts WHERE ts < ?", (now - 60,))
                    active = self._db.execute("SELECT COUNT(*) FROM leases WHERE backend=?", (backend,)).fetchone()[0]
                    recent = self._db.execute("SELECT COUNT(*) FROM starts WHERE backend=?", (backend,)).fetchone()[0]
                    token = None
                    if active < concurrent and recent < per_min:
                        token = uuid.uuid4().hex
                        self._db.execute("INSERT INTO leases VALUES (?, ?, ?, ?)", (token, backend, now, now + lease_s))
                        self._db.execute("INSERT INTO starts VALUES (?, ?)", (backend, now))
                    self._db.execute("COMMIT")
                except Exception:
                    self._db.execute("ROLLBACK")
                    raise
            if token is not None:
                return token, time.monotonic() - t0
            if time.monotonic() - t0 >= max_wait_s:
                return None, time.monotonic() - t0
            time.sleep(0.5)

    def release(self, token: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM leases WHERE token=?", (token,))

    def close(self) -> None:
        self._db.close()
