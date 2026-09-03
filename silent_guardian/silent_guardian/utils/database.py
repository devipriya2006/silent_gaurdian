"""
Lightweight SQLite persistence layer for detected incidents.

Uses the standard library sqlite3 module only, so there is no external
database dependency to configure for the Render deployment.
"""

import sqlite3
import threading


class IncidentDB:
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self):
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self):
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    severity TEXT NOT NULL,
                    source TEXT,
                    evidence_file TEXT,
                    status TEXT DEFAULT 'unreviewed'
                )
                """
            )
            conn.commit()

    def add_incident(self, timestamp, confidence, severity, evidence_file, source=None):
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO incidents (timestamp, confidence, severity, source, evidence_file, status)
                VALUES (?, ?, ?, ?, ?, 'unreviewed')
                """,
                (timestamp, confidence, severity, source, evidence_file),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM incidents WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
            return dict(row)

    def list_incidents(self):
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM incidents ORDER BY id DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def update_status(self, incident_id, status):
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE incidents SET status = ? WHERE id = ?", (status, incident_id)
            )
            conn.commit()

    def get_stats(self):
        with self._lock, self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
            high = conn.execute(
                "SELECT COUNT(*) FROM incidents WHERE severity = 'High'"
            ).fetchone()[0]
            unreviewed = conn.execute(
                "SELECT COUNT(*) FROM incidents WHERE status = 'unreviewed'"
            ).fetchone()[0]
            confirmed = conn.execute(
                "SELECT COUNT(*) FROM incidents WHERE status = 'confirmed'"
            ).fetchone()[0]
            return {
                "total": total,
                "high_severity": high,
                "unreviewed": unreviewed,
                "confirmed": confirmed,
            }
