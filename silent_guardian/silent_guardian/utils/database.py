"""
SQLite persistence layer for detected incidents across all three
detection modes (video, audio, image).

Uses the standard library sqlite3 module only — no external database
dependency to configure for the Render deployment.
"""

import sqlite3
import threading
from contextlib import contextmanager

VALID_STATUSES = ("Pending Review", "Verified", "False Alarm")
VALID_SOURCES = ("video", "audio", "image")


class IncidentDB:
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self):
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _connection(self):
        """Close connections deterministically (important on Windows)."""
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    def _init_schema(self):
        with self._lock, self._connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    source TEXT NOT NULL,
                    score REAL NOT NULL,
                    classification TEXT NOT NULL,
                    evidence_file TEXT,
                    detail TEXT,
                    status TEXT DEFAULT 'Pending Review'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS analyses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    source TEXT NOT NULL,
                    score REAL NOT NULL,
                    classification TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def add_analysis(self, timestamp, source, score, classification):
        """Store every completed analysis, including LOW/MODERATE results."""
        if source not in VALID_SOURCES:
            raise ValueError(f"Invalid source: {source}")
        with self._lock, self._connection() as conn:
            conn.execute(
                """INSERT INTO analyses (timestamp, source, score, classification)
                   VALUES (?, ?, ?, ?)""",
                (timestamp, source, score, classification),
            )
            conn.commit()

    def add_incident(self, timestamp, source, score, classification,
                      evidence_file=None, detail=None):
        if source not in VALID_SOURCES:
            raise ValueError(f"Invalid source: {source}")

        with self._lock, self._connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO incidents
                    (timestamp, source, score, classification, evidence_file, detail, status)
                VALUES (?, ?, ?, ?, ?, ?, 'Pending Review')
                """,
                (timestamp, source, score, classification, evidence_file, detail),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM incidents WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
            return dict(row)

    def list_incidents(self, source=None, classification=None, status=None,
                        date_from=None, date_to=None):
        query = "SELECT * FROM incidents WHERE 1=1"
        params = []

        if source:
            query += " AND source = ?"
            params.append(source)
        if classification:
            query += " AND classification = ?"
            params.append(classification)
        if status:
            query += " AND status = ?"
            params.append(status)
        if date_from:
            query += " AND timestamp >= ?"
            params.append(date_from)
        if date_to:
            query += " AND timestamp <= ?"
            params.append(date_to)

        query += " ORDER BY id DESC"

        with self._lock, self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def update_status(self, incident_id, status):
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}")
        with self._lock, self._connection() as conn:
            conn.execute(
                "UPDATE incidents SET status = ? WHERE id = ?", (status, incident_id)
            )
            conn.commit()

    def get_stats(self):
        with self._lock, self._connection() as conn:
            analyses = conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
            total = conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
            high_risk = conn.execute(
                "SELECT COUNT(*) FROM incidents WHERE classification IN ('HIGH', 'CRITICAL')"
            ).fetchone()[0]
            critical = conn.execute(
                "SELECT COUNT(*) FROM incidents WHERE classification = 'CRITICAL'"
            ).fetchone()[0]
            pending = conn.execute(
                "SELECT COUNT(*) FROM incidents WHERE status = 'Pending Review'"
            ).fetchone()[0]
            verified = conn.execute(
                "SELECT COUNT(*) FROM incidents WHERE status = 'Verified'"
            ).fetchone()[0]
            by_source = {}
            for src in VALID_SOURCES:
                by_source[src] = conn.execute(
                    "SELECT COUNT(*) FROM incidents WHERE source = ?", (src,)
                ).fetchone()[0]
            return {
                "analyses": analyses,
                "total": total,
                "high_risk": high_risk,
                "critical": critical,
                "pending": pending,
                "verified": verified,
                "by_source": by_source,
            }
