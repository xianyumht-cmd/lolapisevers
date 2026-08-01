from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from fastapi import HTTPException
from services.groupguard_protocol import validate_request_id


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "contact_risk.db"


def _json_array(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item or "").strip() for item in value if str(item or "").strip()]
    try:
        parsed = json.loads(str(value or "[]"))
    except Exception:
        return []
    return _json_array(parsed)


class ContactRiskStore:
    def __init__(self, path: Optional[Path] = None) -> None:
        configured = str(os.getenv("CONTACT_RISK_DB_PATH") or "").strip()
        self.path = Path(path or configured or DEFAULT_DB_PATH).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.path), timeout=10.0)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("PRAGMA foreign_keys=ON")
            yield connection
        finally:
            connection.close()

    def _init_schema(self) -> None:
        with self._lock, self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS contact_risk_records (
                    category TEXT NOT NULL,
                    identifier_type TEXT NOT NULL,
                    identifier_value TEXT NOT NULL,
                    report_count INTEGER NOT NULL DEFAULT 0,
                    last_report_content TEXT NOT NULL DEFAULT '',
                    recent_reports_json TEXT NOT NULL DEFAULT '[]',
                    sources_json TEXT NOT NULL DEFAULT '[]',
                    first_reported_at INTEGER NOT NULL DEFAULT 0,
                    last_reported_at INTEGER NOT NULL DEFAULT 0,
                    last_checked_at INTEGER NOT NULL DEFAULT 0,
                    updated_at INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (category, identifier_type, identifier_value)
                );
                CREATE TABLE IF NOT EXISTS contact_risk_report_events (
                    request_id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    identifier_type TEXT NOT NULL,
                    identifier_value TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT '',
                    actor_id TEXT NOT NULL DEFAULT '',
                    group_id TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_contact_risk_updated
                    ON contact_risk_records(category, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_contact_risk_identifier
                    ON contact_risk_records(identifier_type, identifier_value);
                CREATE INDEX IF NOT EXISTS idx_contact_risk_event_created
                    ON contact_risk_report_events(created_at DESC);
                """
            )
            connection.commit()

    @staticmethod
    def _record(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        return {
            "category": str(row["category"]),
            "identifier_type": str(row["identifier_type"]),
            "identifier_value": str(row["identifier_value"]),
            "report_count": int(row["report_count"] or 0),
            "last_report_content": str(row["last_report_content"] or ""),
            "recent_reports": _json_array(row["recent_reports_json"])[:10],
            "sources": _json_array(row["sources_json"])[:20],
            "first_reported_at": int(row["first_reported_at"] or 0),
            "last_reported_at": int(row["last_reported_at"] or 0),
            "last_checked_at": int(row["last_checked_at"] or 0),
            "updated_at": int(row["updated_at"] or 0),
        }

    def get(
        self,
        category: str,
        identifier_type: str,
        identifier_value: str,
        *,
        touch: bool = True,
    ) -> Optional[Dict[str, Any]]:
        now = int(time.time() * 1000)
        with self._lock, self._connection() as connection:
            row = connection.execute(
                """SELECT category, identifier_type, identifier_value, report_count,
                    last_report_content, recent_reports_json, sources_json,
                    first_reported_at, last_reported_at, last_checked_at, updated_at
                    FROM contact_risk_records
                    WHERE category=? AND identifier_type=? AND identifier_value=?""",
                (category, identifier_type, identifier_value),
            ).fetchone()
            if row is not None and touch:
                connection.execute(
                    """UPDATE contact_risk_records SET last_checked_at=?
                    WHERE category=? AND identifier_type=? AND identifier_value=?""",
                    (now, category, identifier_type, identifier_value),
                )
                connection.commit()
            record = self._record(row)
            if record is not None and touch:
                record["last_checked_at"] = now
            return record

    def report(
        self,
        *,
        request_id: str,
        category: str,
        identifier_type: str,
        identifier_value: str,
        content: str,
        source: str,
        actor_id: str = "",
        group_id: str = "",
    ) -> Tuple[Dict[str, Any], bool]:
        try:
            normalized_request_id = validate_request_id(request_id, required=True)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        now = int(time.time() * 1000)
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        safe_source = str(source or "client").strip()[:64] or "client"
        safe_actor_id = str(actor_id or "").strip()[:64]
        safe_group_id = str(group_id or "").strip()[:64]
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing_event = connection.execute(
                    """SELECT request_id, category, identifier_type, identifier_value,
                        content_sha256, source, actor_id, group_id
                        FROM contact_risk_report_events WHERE request_id=?""",
                    (normalized_request_id,),
                ).fetchone()
                if existing_event is not None:
                    expected = (
                        category,
                        identifier_type,
                        identifier_value,
                        content_hash,
                        safe_source,
                        safe_actor_id,
                        safe_group_id,
                    )
                    actual = (
                        str(existing_event["category"]),
                        str(existing_event["identifier_type"]),
                        str(existing_event["identifier_value"]),
                        str(existing_event["content_sha256"]),
                        str(existing_event["source"]),
                        str(existing_event["actor_id"]),
                        str(existing_event["group_id"]),
                    )
                    if actual != expected:
                        raise HTTPException(status_code=409, detail="同一 request_id 已用于另一条举报")
                    row = connection.execute(
                        """SELECT category, identifier_type, identifier_value, report_count,
                            last_report_content, recent_reports_json, sources_json,
                            first_reported_at, last_reported_at, last_checked_at, updated_at
                            FROM contact_risk_records
                            WHERE category=? AND identifier_type=? AND identifier_value=?""",
                        (actual[0], actual[1], actual[2]),
                    ).fetchone()
                    connection.commit()
                    record = self._record(row)
                    if record is None:
                        raise HTTPException(status_code=409, detail="举报幂等记录与风险记录不一致")
                    return record, True

                current_row = connection.execute(
                    """SELECT category, identifier_type, identifier_value, report_count,
                        last_report_content, recent_reports_json, sources_json,
                        first_reported_at, last_reported_at, last_checked_at, updated_at
                        FROM contact_risk_records
                        WHERE category=? AND identifier_type=? AND identifier_value=?""",
                    (category, identifier_type, identifier_value),
                ).fetchone()
                current = self._record(current_row) or {}
                reports = [content] + [item for item in current.get("recent_reports", []) if item != content]
                sources = [safe_source] + [item for item in current.get("sources", []) if item != safe_source]
                next_record = {
                    "category": category,
                    "identifier_type": identifier_type,
                    "identifier_value": identifier_value,
                    "report_count": int(current.get("report_count") or 0) + 1,
                    "last_report_content": content,
                    "recent_reports": reports[:10],
                    "sources": sources[:20],
                    "first_reported_at": int(current.get("first_reported_at") or now),
                    "last_reported_at": now,
                    "last_checked_at": int(current.get("last_checked_at") or 0),
                    "updated_at": now,
                }
                connection.execute(
                    """INSERT INTO contact_risk_records(
                        category, identifier_type, identifier_value, report_count,
                        last_report_content, recent_reports_json, sources_json,
                        first_reported_at, last_reported_at, last_checked_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(category, identifier_type, identifier_value) DO UPDATE SET
                        report_count=excluded.report_count,
                        last_report_content=excluded.last_report_content,
                        recent_reports_json=excluded.recent_reports_json,
                        sources_json=excluded.sources_json,
                        first_reported_at=excluded.first_reported_at,
                        last_reported_at=excluded.last_reported_at,
                        last_checked_at=excluded.last_checked_at,
                        updated_at=excluded.updated_at""",
                    (
                        category,
                        identifier_type,
                        identifier_value,
                        next_record["report_count"],
                        content,
                        json.dumps(next_record["recent_reports"], ensure_ascii=False),
                        json.dumps(next_record["sources"], ensure_ascii=False),
                        next_record["first_reported_at"],
                        now,
                        next_record["last_checked_at"],
                        now,
                    ),
                )
                connection.execute(
                    """INSERT INTO contact_risk_report_events(
                        request_id, category, identifier_type, identifier_value,
                        content_sha256, source, actor_id, group_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        normalized_request_id,
                        category,
                        identifier_type,
                        identifier_value,
                        content_hash,
                        safe_source,
                        safe_actor_id,
                        safe_group_id,
                        now,
                    ),
                )
                connection.commit()
                return next_record, False
            except Exception:
                connection.rollback()
                raise
