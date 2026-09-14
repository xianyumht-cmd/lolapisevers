from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Mapping, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "contact_risk.db"


class ContactRiskRetryQueue:
    """Persistent queue for failed third-party report submissions.

    Queue rows contain only the provider id and report parameters. Provider
    URLs, headers and secrets remain in the parser-center config/environment.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        configured = str(os.getenv("CONTACT_RISK_DB_PATH") or "").strip()
        self.path = Path(path or configured or DEFAULT_DB_PATH).expanduser().resolve()
        self._lock = threading.RLock()
        self._schema_ready = False

    def start(self) -> None:
        """Create the SQLite directory/schema explicitly and idempotently."""
        if self._schema_ready:
            return
        with self._lock:
            if self._schema_ready:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._init_schema()
            self._schema_ready = True

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.path), timeout=10.0)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            yield connection
        finally:
            connection.close()

    def _init_schema(self) -> None:
        with self._lock, self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS contact_risk_submission_queue (
                    queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    feature TEXT NOT NULL,
                    provider_id TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at INTEGER NOT NULL DEFAULT 0,
                    last_error_class TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    UNIQUE(request_id, feature, provider_id)
                );
                CREATE INDEX IF NOT EXISTS idx_contact_risk_submission_due
                    ON contact_risk_submission_queue(state, next_attempt_at, queue_id);
                """
            )
            connection.commit()

    @staticmethod
    def _row(row: sqlite3.Row) -> Dict[str, Any]:
        try:
            parameters = json.loads(str(row["parameters_json"] or "{}"))
        except json.JSONDecodeError:
            parameters = {}
        return {
            "queue_id": int(row["queue_id"]),
            "request_id": str(row["request_id"]),
            "feature": str(row["feature"]),
            "provider_id": str(row["provider_id"]),
            "parameters": parameters if isinstance(parameters, dict) else {},
            "state": str(row["state"]),
            "attempts": int(row["attempts"] or 0),
            "next_attempt_at": int(row["next_attempt_at"] or 0),
            "last_error_class": str(row["last_error_class"] or ""),
            "created_at": int(row["created_at"] or 0),
            "updated_at": int(row["updated_at"] or 0),
        }

    def enqueue(
        self,
        *,
        request_id: str,
        feature: str,
        provider_id: str,
        parameters: Mapping[str, Any],
        error_class: str = "",
        delay_seconds: int = 60,
    ) -> Dict[str, Any]:
        self.start()
        now = int(time.time() * 1000)
        next_at = now + max(0, min(int(delay_seconds), 86400)) * 1000
        payload = json.dumps(dict(parameters), ensure_ascii=False, separators=(",", ":"))
        with self._lock, self._connection() as connection:
            connection.execute(
                """INSERT INTO contact_risk_submission_queue(
                    request_id, feature, provider_id, parameters_json, state,
                    attempts, next_attempt_at, last_error_class, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'pending', 0, ?, ?, ?, ?)
                ON CONFLICT(request_id, feature, provider_id) DO UPDATE SET
                    parameters_json=excluded.parameters_json,
                    state='pending',
                    next_attempt_at=MIN(contact_risk_submission_queue.next_attempt_at, excluded.next_attempt_at),
                    last_error_class=excluded.last_error_class,
                    updated_at=excluded.updated_at""",
                (
                    str(request_id)[:128],
                    str(feature)[:96],
                    str(provider_id)[:96],
                    payload,
                    next_at,
                    str(error_class or "")[:128],
                    now,
                    now,
                ),
            )
            connection.commit()
            row = connection.execute(
                """SELECT * FROM contact_risk_submission_queue
                    WHERE request_id=? AND feature=? AND provider_id=?""",
                (str(request_id)[:128], str(feature)[:96], str(provider_id)[:96]),
            ).fetchone()
        return self._row(row)

    def list(self, *, state: str = "", limit: int = 100) -> list[Dict[str, Any]]:
        self.start()
        capped = max(1, min(int(limit), 1000))
        query = "SELECT * FROM contact_risk_submission_queue"
        parameters: tuple[Any, ...] = ()
        if state:
            query += " WHERE state=?"
            parameters = (str(state),)
        query += " ORDER BY queue_id DESC LIMIT ?"
        parameters = (*parameters, capped)
        with self._lock, self._connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._row(row) for row in rows]

    def due(self, *, limit: int = 20, queue_id: int = 0) -> list[Dict[str, Any]]:
        self.start()
        capped = max(1, min(int(limit), 100))
        now = int(time.time() * 1000)
        with self._lock, self._connection() as connection:
            if queue_id > 0:
                rows = connection.execute(
                    "SELECT * FROM contact_risk_submission_queue WHERE queue_id=? AND state='pending'",
                    (int(queue_id),),
                ).fetchall()
            else:
                rows = connection.execute(
                    """SELECT * FROM contact_risk_submission_queue
                       WHERE state='pending' AND next_attempt_at<=?
                       ORDER BY next_attempt_at, queue_id LIMIT ?""",
                    (now, capped),
                ).fetchall()
        return [self._row(row) for row in rows]

    def mark_success(self, queue_id: int) -> None:
        self.start()
        now = int(time.time() * 1000)
        with self._lock, self._connection() as connection:
            connection.execute(
                "UPDATE contact_risk_submission_queue SET state='completed', updated_at=? WHERE queue_id=?",
                (now, int(queue_id)),
            )
            connection.commit()

    def mark_rejected(self, queue_id: int) -> None:
        self.start()
        now = int(time.time() * 1000)
        with self._lock, self._connection() as connection:
            connection.execute(
                "UPDATE contact_risk_submission_queue SET state='rejected', updated_at=? WHERE queue_id=?",
                (now, int(queue_id)),
            )
            connection.commit()

    def mark_failed(
        self,
        queue_id: int,
        *,
        error_class: str,
        max_attempts: int = 8,
    ) -> Dict[str, Any]:
        self.start()
        now = int(time.time() * 1000)
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT attempts FROM contact_risk_submission_queue WHERE queue_id=?",
                (int(queue_id),),
            ).fetchone()
            attempts = int(row["attempts"] or 0) + 1 if row is not None else 1
            state = "failed" if attempts >= max(1, int(max_attempts)) else "pending"
            delay_seconds = min(3600, 60 * (2 ** min(attempts - 1, 6)))
            connection.execute(
                """UPDATE contact_risk_submission_queue
                   SET state=?, attempts=?, next_attempt_at=?, last_error_class=?, updated_at=?
                   WHERE queue_id=?""",
                (
                    state,
                    attempts,
                    now + delay_seconds * 1000,
                    str(error_class or "failed")[:128],
                    now,
                    int(queue_id),
                ),
            )
            connection.commit()
            updated = connection.execute(
                "SELECT * FROM contact_risk_submission_queue WHERE queue_id=?",
                (int(queue_id),),
            ).fetchone()
        return self._row(updated)

    def remove(self, queue_id: int) -> bool:
        self.start()
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM contact_risk_submission_queue WHERE queue_id=?",
                (int(queue_id),),
            )
            connection.commit()
            return cursor.rowcount > 0


_default_queue: ContactRiskRetryQueue | None = None
_default_lock = threading.Lock()


def get_contact_risk_retry_queue() -> ContactRiskRetryQueue:
    global _default_queue
    with _default_lock:
        configured = str(os.getenv("CONTACT_RISK_DB_PATH") or "").strip()
        target = Path(configured or DEFAULT_DB_PATH).expanduser().resolve()
        if _default_queue is None or _default_queue.path != target:
            _default_queue = ContactRiskRetryQueue(target)
        return _default_queue
