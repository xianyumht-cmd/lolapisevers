from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, Mapping

from fastapi import HTTPException

from services.api_parser_center import (
    ParserCenterError,
    enabled_providers,
    execute_request,
    parse_response,
    prepare_request,
)
from services.contact_risk_service import report_contact_risk as save_local_contact_risk_report


_ACCEPTED_OUTCOMES = {"accepted", "success", "ok", "created", "submitted"}
_PENDING_OUTCOMES = {"pending", "queued", "review", "under_review", "processing"}
_REJECTED_OUTCOMES = {"rejected", "denied", "refused", "invalid"}
_PUBLIC_SOURCE_PATTERNS = re.compile(
    r"https?://|www\.|接口来源|数据来源|provider|\bby\s*[:：]",
    re.I,
)
_CASE_ID_KEYS = ("case_id", "caseId", "ticket_id", "ticketId", "案件编号", "工单号")
_REVIEW_STATUS_KEYS = ("review_status", "reviewStatus", "status", "审核状态", "处理状态")
_RECEIPT_KEYS = ("receipt", "message", "msg", "detail", "reason", "平台回执", "回执说明")


def _safe_business_text(value: Any, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()[:limit]
    if not text or _PUBLIC_SOURCE_PATTERNS.search(text):
        return ""
    return text


def _field_text(fields: Mapping[str, Any], keys: tuple[str, ...], limit: int = 500) -> str:
    for key in keys:
        if key not in fields:
            continue
        text = _safe_business_text(fields.get(key), limit)
        if text:
            return text
    return ""


def _submission_parameters(
    *,
    request_id: str,
    category: str,
    identifier_type: str,
    identifier_value: str,
    content: str,
    source: str,
    actor_id: str,
    group_id: str,
) -> Dict[str, str]:
    return {
        "request_id": request_id,
        "category": category,
        "identifier_type": identifier_type,
        "type": identifier_type,
        "identifier": identifier_value,
        "account": identifier_value,
        "qq": identifier_value if identifier_type == "qq" else "",
        "wechat": identifier_value if identifier_type == "wechat" else "",
        "wx": identifier_value if identifier_type == "wechat" else "",
        "content": content,
        "evidence": content,
        "reason": content,
        "source": source,
        "actor_id": actor_id,
        "group_id": group_id,
    }


def _normalize_submission_outcome(value: Any) -> str:
    outcome = str(value or "unknown").strip().lower()
    if outcome in _ACCEPTED_OUTCOMES:
        return "accepted"
    if outcome in _PENDING_OUTCOMES:
        return "pending"
    if outcome in _REJECTED_OUTCOMES:
        return "rejected"
    return "unknown"


async def _submit_provider(
    profile: Mapping[str, Any],
    parameters: Mapping[str, Any],
) -> Dict[str, Any]:
    provider_id = str(profile.get("id") or profile.get("name") or "provider")[:64]
    try:
        prepared = prepare_request(profile, parameters)
        execution = await asyncio.to_thread(execute_request, prepared)
        parsed = parse_response(
            profile,
            execution.payload,
            status_code=execution.status_code,
        )
        fields = parsed.get("fields") if isinstance(parsed.get("fields"), Mapping) else {}
        return {
            "provider": provider_id,
            "status": "ok",
            "outcome": _normalize_submission_outcome(parsed.get("outcome")),
            "case_id": _field_text(fields, _CASE_ID_KEYS, 160),
            "review_status": _field_text(fields, _REVIEW_STATUS_KEYS, 160),
            "receipt": _field_text(fields, _RECEIPT_KEYS, 500),
            "fields": dict(fields),
        }
    except Exception as exc:
        return {
            "provider": provider_id,
            "status": "unavailable",
            "outcome": "unavailable",
            "case_id": "",
            "review_status": "",
            "receipt": "",
            "fields": {},
            "error_class": type(exc).__name__,
        }


def load_report_providers(category: str) -> list[Dict[str, Any]]:
    feature = "peer_report" if category == "peer" else "scammer_report"
    try:
        return enabled_providers(feature, operation="report")[:10]
    except ParserCenterError as exc:
        raise HTTPException(status_code=503, detail="举报提交解析中心配置无效") from exc


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
    """Persist locally first, then submit configured third-party reports.

    The local store remains the source of durability. A duplicate ``request_id``
    is never submitted again, preventing accidental repeated reports.
    """

    local_payload = await save_local_contact_risk_report(
        ctx,
        request_id=request_id,
        category=category,
        identifier_type=identifier_type,
        identifier_value=identifier_value,
        content=content,
        source=source,
        actor_id=actor_id,
        group_id=group_id,
    )
    profiles = load_report_providers(str(local_payload.get("category") or category))
    if bool(local_payload.get("duplicate")):
        return {
            **local_payload,
            "submissions": [],
            "submission_status": "skipped_duplicate",
            "configured_submission_count": len(profiles),
        }
    if not profiles:
        return {
            **local_payload,
            "submissions": [],
            "submission_status": "not_configured",
            "configured_submission_count": 0,
        }

    parameters = _submission_parameters(
        request_id=request_id,
        category=str(local_payload.get("category") or category),
        identifier_type=str(local_payload.get("identifier_type") or identifier_type),
        identifier_value=str(local_payload.get("identifier_value") or identifier_value),
        content=content,
        source=source,
        actor_id=actor_id,
        group_id=group_id,
    )
    submissions = await asyncio.gather(
        *[_submit_provider(profile, parameters) for profile in profiles]
    )
    outcomes = {str(item.get("outcome") or "") for item in submissions}
    if "accepted" in outcomes:
        submission_status = "accepted"
    elif "pending" in outcomes:
        submission_status = "pending"
    elif "rejected" in outcomes and all(
        item.get("outcome") == "rejected" for item in submissions
    ):
        submission_status = "rejected"
    elif all(item.get("status") == "unavailable" for item in submissions):
        submission_status = "unavailable"
    else:
        submission_status = "partial"
    return {
        **local_payload,
        "submissions": submissions,
        "submission_status": submission_status,
        "configured_submission_count": len(profiles),
    }


def _unique_submission_values(payload: Mapping[str, Any], key: str, limit: int) -> list[str]:
    submissions = payload.get("submissions") if isinstance(payload.get("submissions"), list) else []
    result: list[str] = []
    for submission in submissions:
        if not isinstance(submission, Mapping) or submission.get("status") != "ok":
            continue
        text = _safe_business_text(submission.get(key), 500)
        if text and text not in result:
            result.append(text)
    return result[:limit]


def format_contact_risk_report_text(payload: Mapping[str, Any]) -> str:
    title = "同行" if payload.get("category") == "peer" else "骗子"
    duplicate = bool(payload.get("duplicate"))
    record = payload.get("record") if isinstance(payload.get("record"), Mapping) else {}
    lines = [
        f"✅ {title}举报{'已确认' if duplicate else '已收录'}",
        f"账号：{'QQ' if payload.get('identifier_type') == 'qq' else '微信'} {payload.get('identifier_value') or '-'}",
        f"累计举报次数：{int(record.get('report_count') or 0)}",
    ]
    status = str(payload.get("submission_status") or "not_configured")
    if status == "skipped_duplicate":
        lines.append("本次请求未重复计数，也未重复提交。")
        return "\n".join(lines)
    if status == "not_configured":
        lines.append("举报记录已安全保存。")
        return "\n".join(lines)
    if status == "accepted":
        lines.append("提交状态：已受理")
    elif status == "pending":
        lines.append("提交状态：等待处理")
    elif status == "rejected":
        lines.append("提交状态：未受理；本地记录已保留")
    elif status == "unavailable":
        lines.append("联网提交暂未完成，本地记录已保留。")
    else:
        lines.append("提交状态：部分完成；本地记录已保留")

    case_ids = _unique_submission_values(payload, "case_id", 5)
    review_statuses = _unique_submission_values(payload, "review_status", 5)
    receipts = _unique_submission_values(payload, "receipt", 5)
    for case_id in case_ids:
        lines.append(f"案件编号：{case_id}")
    for review_status in review_statuses:
        lines.append(f"审核状态：{review_status}")
    for receipt in receipts:
        lines.append(f"回执说明：{receipt}")
    return "\n".join(lines).strip()


def contact_risk_report_meta(payload: Mapping[str, Any]) -> Dict[str, Any]:
    record = payload.get("record") if isinstance(payload.get("record"), Mapping) else {}
    submissions = payload.get("submissions") if isinstance(payload.get("submissions"), list) else []
    return {
        "category": str(payload.get("category") or ""),
        "identifier_type": str(payload.get("identifier_type") or ""),
        "identifier_value": str(payload.get("identifier_value") or ""),
        "duplicate": bool(payload.get("duplicate")),
        "report_count": int(record.get("report_count") or 0),
        "submission_status": str(payload.get("submission_status") or ""),
        "configured_submission_count": int(payload.get("configured_submission_count") or 0),
        "successful_submission_count": sum(
            1 for item in submissions if isinstance(item, Mapping) and item.get("status") == "ok"
        ),
    }
