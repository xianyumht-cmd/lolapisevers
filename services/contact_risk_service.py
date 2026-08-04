from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
from urllib.parse import quote, urlsplit

from fastapi import HTTPException

from services.api_parser_center import (
    ParserCenterError,
    enabled_providers,
    execute_request,
    parse_response,
    prepare_request,
)


_VALID_QQ = re.compile(r"^\d{5,13}$")
_VALID_WECHAT = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{2,63}$")
_NO_RECORD_PATTERNS = re.compile(r"未发现|未查询到|无记录|暂无记录|not\s*found|no\s*record", re.I)
_RISK_PATTERNS = re.compile(r"骗子|诈骗|风险|黑名单|举报|scam|fraud|blacklist", re.I)
_PUBLIC_SOURCE_PATTERNS = re.compile(
    r"https?://|www\.|接口来源|数据来源|provider|\bby\s*[:：]",
    re.I,
)
_RISK_OUTCOMES = {"hit", "reported", "risk", "found", "blacklisted", "accepted"}
_CLEAR_OUTCOMES = {"clear", "no_record", "not_found", "safe", "normal"}
_RECORD_TEXT_KEYS = (
    "reason",
    "原因",
    "report_content",
    "content",
    "举报内容",
    "description",
    "desc",
    "detail",
    "message",
)
_COUNT_KEYS = ("count", "total", "report_count", "record_count", "记录数量", "举报次数")
_HIT_KEYS = ("hit", "found", "exists", "is_scammer", "scammer", "risk", "blacklisted", "命中")


@dataclass(frozen=True)
class ProviderTemplate:
    """Compatibility wrapper for the legacy URL-only environment format."""

    key: str
    url: str


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


def _provider_env(category: str) -> str:
    return "QUERY_PEER_PROVIDERS_JSON" if category == "peer" else "QUERY_SCAMMER_PROVIDERS_JSON"


def load_provider_templates(category: str) -> List[ProviderTemplate]:
    """Load the legacy URL-only provider format for backward compatibility."""

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


def load_parser_providers(category: str) -> List[Dict[str, Any]]:
    try:
        return enabled_providers(category, operation="query")[:10]
    except ParserCenterError as exc:
        raise HTTPException(status_code=503, detail="风险查询解析中心配置无效") from exc


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
        parameter = "qq" if identifier_type == "qq" else "wechat"
        result = f"{result}{separator}{parameter}={encoded}&type={identifier_type}"
    return result


def _safe_business_text(value: Any, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()[:limit]
    if not text or _PUBLIC_SOURCE_PATTERNS.search(text):
        return ""
    return text


def _first_text(data: Any) -> str:
    if isinstance(data, str):
        return _safe_business_text(data)
    if not isinstance(data, Mapping):
        return ""
    for key in ("reason", "content", "detail", "description", "message", "msg", "result", "error"):
        value = data.get(key)
        if isinstance(value, str):
            text = _safe_business_text(value)
            if text:
                return text
    nested = data.get("data")
    return _first_text(nested) if nested is not data else ""


def _record_text(item: Any) -> str:
    if isinstance(item, str):
        return _safe_business_text(item)
    if not isinstance(item, Mapping):
        return ""
    for key in _RECORD_TEXT_KEYS:
        if key in item:
            text = _safe_business_text(item.get(key))
            if text:
                return text
    return ""


def _report_texts(data: Any) -> List[str]:
    if not isinstance(data, Mapping):
        return []
    nested = data.get("data") if isinstance(data.get("data"), Mapping) else {}
    buckets: List[Any] = []
    for container in (data, nested):
        for key in ("reports", "anonymous_reports", "records", "items", "list"):
            value = container.get(key)
            if isinstance(value, list):
                buckets.extend(value)
    texts: List[str] = []
    for item in buckets:
        normalized = _record_text(item)
        if normalized and normalized not in texts:
            texts.append(normalized)
    return texts[:20]


def _provider_count(data: Any, reports: List[str]) -> int:
    if not isinstance(data, Mapping):
        return len(reports)
    nested = data.get("data") if isinstance(data.get("data"), Mapping) else {}
    for container in (data, nested):
        for key in _COUNT_KEYS:
            try:
                count = int(container.get(key))
            except (TypeError, ValueError):
                continue
            if count >= 0:
                return count
    return len(reports)


def _provider_hit(data: Any, text: str, reports: List[str], count: int) -> Optional[bool]:
    if isinstance(data, Mapping):
        for key in _HIT_KEYS:
            value = data.get(key)
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)) and value in {0, 1}:
                return bool(value)
        success = data.get("success")
        if success is True and (count > 0 or reports):
            return True
        nested = data.get("data")
        if isinstance(nested, Mapping):
            nested_hit = _provider_hit(nested, text, reports, count)
            if nested_hit is not None:
                return nested_hit
    if reports or count > 0:
        return True
    if _NO_RECORD_PATTERNS.search(text):
        return False
    if _RISK_PATTERNS.search(text):
        return True
    return None


def _parser_parameters(identifier_type: str, identifier_value: str) -> Dict[str, str]:
    return {
        "identifier_type": identifier_type,
        "type": identifier_type,
        "identifier": identifier_value,
        "account": identifier_value,
        "qq": identifier_value if identifier_type == "qq" else "",
        "wechat": identifier_value if identifier_type == "wechat" else "",
        "wx": identifier_value if identifier_type == "wechat" else "",
    }


def _parsed_record_texts(records: Any) -> List[str]:
    if not isinstance(records, list):
        return []
    result: List[str] = []
    for item in records:
        text = _record_text(item)
        if text and text not in result:
            result.append(text)
    return result[:20]


def _parsed_count(fields: Mapping[str, Any], reports: List[str]) -> int:
    for key in _COUNT_KEYS:
        if key not in fields:
            continue
        try:
            count = int(fields.get(key))
        except (TypeError, ValueError):
            continue
        if count >= 0:
            return count
    return len(reports)


def _parsed_hit(parsed: Mapping[str, Any], fields: Mapping[str, Any], reports: List[str], count: int) -> Optional[bool]:
    outcome = str(parsed.get("outcome") or "").strip().lower()
    if outcome in _RISK_OUTCOMES:
        return True
    if outcome in _CLEAR_OUTCOMES:
        return False
    for key in _HIT_KEYS:
        value = fields.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and value in {0, 1}:
            return bool(value)
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in _RISK_OUTCOMES or lowered in {"是", "有", "命中", "风险"}:
                return True
            if lowered in _CLEAR_OUTCOMES or lowered in {"否", "无", "未命中"}:
                return False
    if reports or count > 0:
        return True
    return None


async def _query_parser_provider(
    profile: Mapping[str, Any],
    identifier_type: str,
    identifier_value: str,
) -> Dict[str, Any]:
    provider_id = str(profile.get("id") or profile.get("name") or "provider")[:64]
    try:
        prepared = prepare_request(
            profile,
            _parser_parameters(identifier_type, identifier_value),
        )
        execution = await asyncio.to_thread(execute_request, prepared)
        parsed = parse_response(
            profile,
            execution.payload,
            status_code=execution.status_code,
        )
        fields = parsed.get("fields") if isinstance(parsed.get("fields"), Mapping) else {}
        reports = _parsed_record_texts(parsed.get("records"))
        if not reports:
            for key in ("reason", "原因", "report_content", "举报内容", "description"):
                text = _safe_business_text(fields.get(key))
                if text and text not in reports:
                    reports.append(text)
        count = _parsed_count(fields, reports)
        message = ""
        for key in ("reason", "原因", "detail", "description"):
            message = _safe_business_text(fields.get(key))
            if message:
                break
        return {
            "provider": provider_id,
            "status": "ok",
            "hit": _parsed_hit(parsed, fields, reports, count),
            "count": count,
            "message": message,
            "reports": reports,
            "records": parsed.get("records") if isinstance(parsed.get("records"), list) else [],
            "fields": dict(fields),
            "parser_center": True,
        }
    except Exception as exc:
        return {
            "provider": provider_id,
            "status": "unavailable",
            "hit": None,
            "count": 0,
            "message": "",
            "reports": [],
            "records": [],
            "fields": {},
            "parser_center": True,
            "error_class": type(exc).__name__,
        }


async def _query_legacy_provider(
    ctx: Any,
    template: ProviderTemplate,
    identifier_type: str,
    identifier_value: str,
) -> Dict[str, Any]:
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
        return {
            "provider": template.key,
            "status": "unavailable",
            "hit": None,
            "count": 0,
            "message": "",
            "reports": [],
        }
    raw = str(response.text or "").strip()
    try:
        data: Any = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        data = raw
    reports = _report_texts(data)
    count = _provider_count(data, reports)
    message = _first_text(data)
    return {
        "provider": template.key,
        "status": "ok",
        "hit": _provider_hit(data, message, reports, count),
        "count": count,
        "message": message,
        "reports": reports,
        "parser_center": False,
    }


# Backward-compatible private name retained for older tests/imports.
_query_provider = _query_legacy_provider


async def query_contact_risk(
    ctx: Any,
    category: str,
    identifier_type: str,
    identifier_value: str,
) -> Dict[str, Any]:
    normalized_category = normalize_category(category)
    normalized_type = normalize_identifier_type(identifier_type)
    normalized_value = normalize_identifier(normalized_type, identifier_value)
    local = await asyncio.to_thread(
        ctx.contact_risk_store.get,
        normalized_category,
        normalized_type,
        normalized_value,
    )
    parser_profiles = load_parser_providers(normalized_category)
    legacy_templates = load_provider_templates(normalized_category)
    jobs = [
        _query_parser_provider(profile, normalized_type, normalized_value)
        for profile in parser_profiles
    ] + [
        _query_legacy_provider(ctx, template, normalized_type, normalized_value)
        for template in legacy_templates
    ]
    providers = await asyncio.gather(*jobs) if jobs else []
    successful = [item for item in providers if item.get("status") == "ok"]
    local_hit = bool(local and int(local.get("report_count") or 0) > 0)
    provider_hit = any(item.get("hit") is True for item in successful)
    provider_clear = bool(successful) and all(item.get("hit") is False for item in successful)
    if local_hit or provider_hit:
        status = "reported"
    elif providers and not successful:
        status = "provider_unavailable"
    elif provider_clear or not providers:
        status = "no_record"
    else:
        status = "unknown"
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


def _visible_risk_details(payload: Mapping[str, Any]) -> List[str]:
    details: List[str] = []
    local = payload.get("local") if isinstance(payload.get("local"), Mapping) else None
    if local:
        for value in [local.get("last_report_content"), *(local.get("recent_reports") or [])]:
            text = _safe_business_text(value, 300)
            if text and text not in details:
                details.append(text)
    providers = payload.get("providers") if isinstance(payload.get("providers"), list) else []
    for item in providers:
        if not isinstance(item, Mapping) or item.get("status") != "ok":
            continue
        reports = item.get("reports") if isinstance(item.get("reports"), list) else []
        for value in reports:
            text = _safe_business_text(value, 300)
            if text and text not in details:
                details.append(text)
        if item.get("hit") is True and not reports:
            text = _safe_business_text(item.get("message"), 300)
            if text and text not in details:
                details.append(text)
    return details[:10]


def format_contact_risk_text(payload: Mapping[str, Any]) -> str:
    title = "同行" if payload.get("category") == "peer" else "骗子"
    lines = [f"🔎 {title}查询", f"账号：{_identifier_label(payload)}"]
    status = str(payload.get("status") or "")
    if status == "reported":
        lines.append("结果：发现已收录或风险记录")
    elif status == "provider_unavailable":
        lines.append("结果：本地未收录；联网查询暂不可用")
    elif status == "unknown":
        lines.append("结果：本地未收录；查询结果状态不明确")
    else:
        lines.append("结果：暂未发现已收录风险记录")

    local = payload.get("local") if isinstance(payload.get("local"), Mapping) else None
    if local:
        lines.append(f"本地举报次数：{int(local.get('report_count') or 0)}")

    details = _visible_risk_details(payload)
    if details:
        lines.append("")
        lines.append("风险详情：")
        for detail in details:
            lines.append(f"- {detail}")

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
            "本次请求未重复计数。" if duplicate else "举报记录已安全保存。",
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
