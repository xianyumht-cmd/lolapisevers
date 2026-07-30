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


_VALID_QQ = re.compile(r"^\d{5,13}$")
_VALID_WECHAT = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{2,63}$")
_NO_RECORD_PATTERNS = re.compile(r"未发现|未查询到|无记录|暂无记录|not\s*found|no\s*record", re.I)
_RISK_PATTERNS = re.compile(r"骗子|诈骗|风险|黑名单|举报|scam|fraud|blacklist", re.I)


@dataclass(frozen=True)
class ProviderTemplate:
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
        parameter = "qq" if identifier_type == "qq" else "wechat"
        result = f"{result}{separator}{parameter}={encoded}&type={identifier_type}"
    return result


def _first_text(data: Any) -> str:
    if isinstance(data, str):
        return data.strip()[:500]
    if not isinstance(data, Mapping):
        return ""
    for key in ("message", "msg", "detail", "content", "reason", "result", "error"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:500]
    nested = data.get("data")
    return _first_text(nested) if nested is not data else ""


def _report_texts(data: Any) -> List[str]:
    if not isinstance(data, Mapping):
        return []
    nested = data.get("data") if isinstance(data.get("data"), Mapping) else {}
    buckets: List[Any] = []
    for container in (data, nested):
        for key in ("reports", "anonymous_reports"):
            value = container.get(key)
            if isinstance(value, list):
                buckets.extend(value)
    texts: List[str] = []
    for item in buckets:
        if isinstance(item, str):
            text = item
        elif isinstance(item, Mapping):
            text = str(
                item.get("report_content")
                or item.get("content")
                or item.get("message")
                or item.get("desc")
                or item.get("description")
                or ""
            )
        else:
            text = ""
        normalized = re.sub(r"\s+", " ", text).strip()[:500]
        if normalized and normalized not in texts:
            texts.append(normalized)
    return texts[:10]


def _provider_count(data: Any, reports: List[str]) -> int:
    if not isinstance(data, Mapping):
        return len(reports)
    nested = data.get("data") if isinstance(data.get("data"), Mapping) else {}
    for value in (data.get("count"), nested.get("count")):
        try:
            count = int(value)
        except (TypeError, ValueError):
            continue
        if count >= 0:
            return count
    return len(reports)


def _provider_hit(data: Any, text: str, reports: List[str], count: int) -> Optional[bool]:
    if isinstance(data, Mapping):
        for key in ("hit", "found", "exists", "is_scammer", "scammer", "risk", "blacklisted"):
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


async def _query_provider(
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
    message = _first_text(data) or raw[:500]
    return {
        "provider": template.key,
        "status": "ok",
        "hit": _provider_hit(data, message, reports, count),
        "count": count,
        "message": message,
        "reports": reports,
    }


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
    templates = load_provider_templates(normalized_category)
    providers = (
        await asyncio.gather(
            *[
                _query_provider(ctx, template, normalized_type, normalized_value)
                for template in templates
            ]
        )
        if templates
        else []
    )
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


def format_contact_risk_text(payload: Mapping[str, Any]) -> str:
    title = "同行" if payload.get("category") == "peer" else "骗子"
    lines = [f"🔎 {title}查询", f"账号：{_identifier_label(payload)}"]
    status = str(payload.get("status") or "")
    if status == "reported":
        lines.append("结果：发现已收录或外部风险记录")
    elif status == "provider_unavailable":
        lines.append("结果：本地未收录；外部查询暂不可用")
    elif status == "unknown":
        lines.append("结果：本地未收录；外部结果状态不明确")
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
            count = int(item.get("count") or 0)
            message = str(item.get("message") or "").strip()
            suffix = f"，记录 {count} 条" if count > 0 else ""
            if message:
                suffix += f"；{message[:200]}"
            lines.append(f"- {item.get('provider') or 'provider'}：{state}{suffix}")
            reports = item.get("reports") if isinstance(item.get("reports"), list) else []
            for report in reports[:3]:
                lines.append(f"  · {str(report)[:200]}")
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
