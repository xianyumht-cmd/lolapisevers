from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
from urllib.parse import quote, urlsplit

from fastapi import HTTPException


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "contact_risk.db"
_VALID_QQ = re.compile(r"^\d{5,13}$")
_VALID_WECHAT = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{2,63}$")
_NO_RECORD_PATTERNS = re.compile(r"未发现|未查询到|无记录|暂无记录|not\s*found|no\s*record", re.I)
_RISK_PATTERNS = re.compile(r"骗子|诈骗|风险|黑名单|举报|scam|fraud|blacklist", re.I)


def normalize_category(value: Any) -> str:
    return "peer" if str(value or "").strip().lower() == "peer" else "scammer"


def normalize_identifier_type(value: Any) -> str:
    return "wechat" if str(value or "").strip().lower() in {"wechat", "wx", "weixin"} else "qq"


def normalize_identifier(identifier_type: str, value: Any) -> str:
    text = str(value or "").strip()
    if identifier_type == "qq":
        if not _VALID_QQ.fullmatch(text):
            raise HTTPException(status_code=400, detail="请输入有效的QQ号（5-13位数字）")
        return text
    if not _VALID_WECHAT.fullmatch(text):
        raise HTTPException(status_code=400, detail="请输入有效的微信号")
    return text


def normalize_evidence(value: Any, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        raise HTTPException(status_code=400, detail="请提供举报说明")
    return text[: max(50, min(int(limit), 5000))]


def _json_array(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item or "").strip() for item in value if str(item or "").strip()]
    try:
        parsed = json.loads(str(value or "[]"))
    except Exception:
        return []
    return _json_array(parsed)


@dataclass(frozen=True)
class ProviderTemplate:
    key: str
    url: str


class ContactRiskStore:
    def __init__(self, path: Optional[Path] = None) -> None:
        configured = str(os.getenv("CONTACT_RISK_DB_PATH") or "").strip()
        self.path = Path(path or configured or DEFAULT_DB_PATH).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

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

    def get(self, category: str, identifier_type: str, identifier_value: str, *, touch: bool = True) -> Optional[Dict[str, Any]]:
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
                    """UPDATE contact_risk_records SET last_checked_at=?, updated_at=?
                    WHERE category=? AND identifier_type=? AND identifier_value=?""",
                    (now, now, category, identifier_type, identifier_value),
                )
            record = self._record(row)
            if record is not None and touch:
                record["last_checked_at"] = now
                record["updated_at"] = now
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
        normalized_request_id = str(request_id or "").strip()[:128]
        if not normalized_request_id:
            raise HTTPException(status_code=400, detail="举报请求缺少 request_id")
        now = int(time.time() * 1000)
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        safe_source = str(source or "client").strip()[:64] or "client"
        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing_event = connection.execute(
                    "SELECT request_id FROM contact_risk_report_events WHERE request_id=?",
                    (normalized_request_id,),
                ).fetchone()
                if existing_event is not None:
                    row = connection.execute(
                        """SELECT category, identifier_type, identifier_value, report_count,
                            last_report_content, recent_reports_json, sources_json,
                            first_reported_at, last_reported_at, last_checked_at, updated_at
                            FROM contact_risk_records
                            WHERE category=? AND identifier_type=? AND identifier_value=?""",
                        (category, identifier_type, identifier_value),
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
                        str(actor_id or "")[:64],
                        str(group_id or "")[:64],
                        now,
                    ),
                )
                connection.commit()
                return next_record, False
            except Exception:
                connection.rollback()
                raise


def _provider_env(category: str) -> str:
    return "QUERY_PEER_PROVIDERS_JSON" if category == "peer" else "QUERY_SCAMMER_PROVIDERS_JSON"


def load_provider_templates(category: str) -> List[ProviderTemplate]:
    raw = str(os.getenv(_provider_env(category)) or "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=503, detail="风险查询 Provider 配置不是有效 JSON") from exc
    items: Iterable[Tuple[Any, Any]]
    if isinstance(parsed, Mapping):
        items = parsed.items()
    elif isinstance(parsed, list):
        items = ((f"provider-{index + 1}", value) for index, value in enumerate(parsed))
    else:
        raise HTTPException(status_code=503, detail="风险查询 Provider 配置必须是对象或数组")
    result: List[ProviderTemplate] = []
    for key, value in items:
        provider_key = str(key or "").strip()[:64]
        template = str(value.get("url") if isinstance(value, Mapping) else value or "").strip()
        sample = template
        for marker, replacement in {
            "{qq}": "123456",
            "{wechat}": "wx_test",
            "{wx}": "wx_test",
            "{account}": "123456",
            "{identifier}": "123456",
            "{type}": "qq",
        }.items():
            sample = sample.replace(marker, replacement)
        parts = urlsplit(sample)
        if not provider_key or parts.scheme not in {"http", "https"} or not parts.netloc:
            raise HTTPException(status_code=503, detail="风险查询 Provider 配置无效")
        result.append(ProviderTemplate(provider_key, template))
    return result[:10]


def build_provider_url(template: str, identifier_type: str, identifier_value: str) -> str:
    encoded = quote(identifier_value, safe="")
    replacements = {
        "{qq}": encoded if identifier_type == "qq" else "",
        "{wechat}": encoded if identifier_type == "wechat" else "",
        "{wx}": encoded if identifier_type == "wechat" else "",
        "{account}": encoded,
        "{identifier}": encoded,
        "{type}": identifier_type,
    }
    result = template
    changed = False
    for marker, value in replacements.items():
        if marker in result:
            result = result.replace(marker, value)
            changed = True
    if "%s" in result:
        result = result.replace("%s", encoded)
        changed = True
    if not changed:
        separator = "&" if "?" in result else "?"
        result = f"{result}{separator}{'qq' if identifier_type == 'qq' else 'wechat'}={encoded}&type={identifier_type}"
    return result


def _first_text(data: Any) -> str:
    if isinstance(data, str):
        return data.strip()[:500]
    if not isinstance(data, Mapping):
        return ""
    for key in ("message", "msg", "detail", "content", "reason", "result"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:500]
    nested = data.get("data")
    return _first_text(nested) if nested is not data else ""


def _provider_hit(data: Any, text: str) -> Optional[bool]:
    if isinstance(data, Mapping):
        for key in ("hit", "found", "exists", "is_scammer", "scammer", "risk", "blacklisted"):
            value = data.get(key)
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)) and value in {0, 1}:
                return bool(value)
        nested = data.get("data")
        if isinstance(nested, Mapping):
            nested_hit = _provider_hit(nested, text)
            if nested_hit is not None:
                return nested_hit
    if _NO_RECORD_PATTERNS.search(text):
        return False
    if _RISK_PATTERNS.search(text):
        return True
    return None


async def _query_provider(ctx: Any, template: ProviderTemplate, identifier_type: str, identifier_value: str) -> Dict[str, Any]:
    url = build_provider_url(template.url, identifier_type, identifier_value)
    source_id = "risk_provider_" + hashlib.sha256(template.key.encode("utf-8")).hexdigest()[:16]
    response = await asyncio.to_thread(
        ctx.upstream_http_client.request,
        source_id,
        url,
        parse_json=False,
        attempts=2,
        read_timeout=8.0,
        singleflight=True,
    )
    if not response.ok:
        return {"provider": template.key, "status": "unavailable", "hit": None, "message": ""}
    raw = str(response.text or "").strip()
    try:
        data: Any = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        data = raw
    message = _first_text(data) or raw[:500]
    return {
        "provider": template.key,
        "status": "ok",
        "hit": _provider_hit(data, message),
        "message": message,
    }


async def query_contact_risk(ctx: Any, category: str, identifier_type: str, identifier_value: str) -> Dict[str, Any]:
    normalized_category = normalize_category(category)
    normalized_type = normalize_identifier_type(identifier_type)
    normalized_value = normalize_identifier(normalized_type, identifier_value)
    local = await asyncio.to_thread(
        ctx.contact_risk_store.get,
        normalized_category,
        normalized_type,
        normalized_value,
    )
    templates = load_provider_templates(normalized_category)
    providers = await asyncio.gather(
        *[_query_provider(ctx, template, normalized_type, normalized_value) for template in templates]
    ) if templates else []
    local_hit = bool(local and int(local.get("report_count") or 0) > 0)
    provider_hit = any(item.get("hit") is True for item in providers)
    provider_clear = bool(providers) and all(item.get("hit") is False for item in providers if item.get("status") == "ok")
    if local_hit or provider_hit:
        status = "reported"
    elif provider_clear:
        status = "no_record"
    elif providers and all(item.get("status") != "ok" for item in providers):
        status = "provider_unavailable"
    else:
        status = "no_record"
    return {
        "category": normalized_category,
        "identifier_type": normalized_type,
        "identifier_value": normalized_value,
        "status": status,
        "local": local,
        "providers": providers,
        "checked_at": int(time.time() * 1000),
    }


async def report_contact_risk(
    ctx: Any,
    *,
    request_id: str,
    category: str,
    identifier_type: str,
    identifier_value: str,
    content: str,
    source: str,
    actor_id: str = "",
    group_id: str = "",
) -> Dict[str, Any]:
    normalized_category = normalize_category(category)
    normalized_type = normalize_identifier_type(identifier_type)
    normalized_value = normalize_identifier(normalized_type, identifier_value)
    evidence = normalize_evidence(content)
    record, duplicate = await asyncio.to_thread(
        ctx.contact_risk_store.report,
        request_id=request_id,
        category=normalized_category,
        identifier_type=normalized_type,
        identifier_value=normalized_value,
        content=evidence,
        source=source,
        actor_id=actor_id,
        group_id=group_id,
    )
    return {
        "category": normalized_category,
        "identifier_type": normalized_type,
        "identifier_value": normalized_value,
        "duplicate": duplicate,
        "record": record,
    }


def _identifier_label(payload: Mapping[str, Any]) -> str:
    kind = "QQ" if payload.get("identifier_type") == "qq" else "微信"
    return f"{kind} {payload.get('identifier_value') or '-'}"


def format_contact_risk_text(payload: Mapping[str, Any]) -> str:
    title = "同行" if payload.get("category") == "peer" else "骗子"
    lines = [f"🔎 {title}查询", f"账号：{_identifier_label(payload)}"]
    status = str(payload.get("status") or "")
    if status == "reported":
        lines.append("结果：发现已收录或外部风险记录")
    elif status == "provider_unavailable":
        lines.append("结果：本地未收录；外部查询暂不可用")
    else:
        lines.append("结果：暂未发现已收录风险记录")
    local = payload.get("local") if isinstance(payload.get("local"), Mapping) else None
    if local:
        lines.append(f"本地举报次数：{int(local.get('report_count') or 0)}")
        detail = str(local.get("last_report_content") or "").strip()
        if detail:
            lines.append(f"最近说明：{detail[:300]}")
    providers = payload.get("providers") if isinstance(payload.get("providers"), list) else []
    visible = [item for item in providers if isinstance(item, Mapping) and item.get("status") == "ok"]
    if visible:
        lines.append("")
        lines.append("外部来源：")
        for item in visible[:5]:
            state = "命中" if item.get("hit") is True else "未命中" if item.get("hit") is False else "状态不明"
            message = str(item.get("message") or "").strip()
            lines.append(f"- {item.get('provider') or 'provider'}：{state}{('；' + message[:200]) if message else ''}")
    lines.append("")
    lines.append("说明：未发现记录不等于绝对安全，请结合实际交易证据判断。")
    return "\n".join(lines).strip()


def format_contact_risk_report_text(payload: Mapping[str, Any]) -> str:
    title = "同行" if payload.get("category") == "peer" else "骗子"
    duplicate = bool(payload.get("duplicate"))
    record = payload.get("record") if isinstance(payload.get("record"), Mapping) else {}
    return "\n".join(
        [
            f"✅ {title}举报{'已确认' if duplicate else '已收录'}",
            f"账号：{_identifier_label(payload)}",
            f"累计举报次数：{int(record.get('report_count') or 0)}",
            "本次请求未重复计数。" if duplicate else "记录已保存到 Windows 内网接口。",
        ]
    )


def contact_risk_meta(payload: Mapping[str, Any]) -> Dict[str, Any]:
    local = payload.get("local") if isinstance(payload.get("local"), Mapping) else {}
    providers = payload.get("providers") if isinstance(payload.get("providers"), list) else []
    return {
        "category": str(payload.get("category") or ""),
        "identifier_type": str(payload.get("identifier_type") or ""),
        "identifier_value": str(payload.get("identifier_value") or ""),
        "status": str(payload.get("status") or ""),
        "local_report_count": int(local.get("report_count") or 0),
        "provider_count": len(providers),
    }
