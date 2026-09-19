from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata
from datetime import datetime
from typing import Any


_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
_DIGIT_BLOCK = r"(?<!\d)(?:\d[\s._·,，:：\-]?){4,12}\d(?!\d)"
_CONTACT_GAP = r"[\s:：=\-—_，,。·]{0,8}"
_GROUP_LABEL = (
    r"(?:q\s*q\s*群|群\s*号|反馈\s*群|售后\s*群|交流\s*群|官方\s*群|"
    r"加\s*群|进\s*群|企鹅\s*群|扣\s*扣\s*群)"
)
_QQ_LABEL = r"(?:q\s*q|扣\s*扣|企鹅)"
_WECHAT_LABEL = r"(?:微\s*信|v\s*x|v\s*信|w\s*x|wechat)"
_WECHAT_ID = r"[A-Za-z][A-Za-z0-9._-]{2,63}"
_EMAIL = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}", re.I)
_URL = re.compile(r"(?:(?:https?://|www\.)[^\s<>\"']+|\bt\.me/[A-Za-z0-9_+/-]+)", re.I)
_PHONE = re.compile(r"(?<!\d)1[3-9](?:[\s\-]?\d){9}(?!\d)")
_GROUP_FORWARD = re.compile(rf"(?P<label>{_GROUP_LABEL}){_CONTACT_GAP}(?P<value>{_DIGIT_BLOCK})", re.I)
_GROUP_REVERSE = re.compile(rf"(?P<value>{_DIGIT_BLOCK}){_CONTACT_GAP}(?P<label>{_GROUP_LABEL})", re.I)
_QQ = re.compile(rf"(?P<label>{_QQ_LABEL})(?:\s*(?:号|号码))?{_CONTACT_GAP}(?P<value>{_DIGIT_BLOCK})", re.I)
_WECHAT = re.compile(
    rf"(?P<label>{_WECHAT_LABEL})(?:\s*(?:号|号码|id))?{_CONTACT_GAP}(?P<value>{_WECHAT_ID})",
    re.I,
)
_STANDALONE_NUMBER = re.compile(rf"(?P<value>{_DIGIT_BLOCK})")
_NUMBER_SAFE_CONTEXT = re.compile(
    r"(?:版本|version|\bver\b|build|构建|更新日期|日期|时间|timestamp|sha|md5|crc|"
    r"文件大小|大小|\bkb\b|\bmb\b|\bgb\b)",
    re.I,
)
_KIND_LABELS = {
    "qq_group": "QQ群",
    "qq": "QQ",
    "wechat": "微信",
    "phone": "手机号",
    "email": "邮箱",
    "url": "外链",
    "number": "长数字",
}


def normalize_notice(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = unicodedata.normalize("NFKC", text)
    text = _ZERO_WIDTH.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\t\f\v ]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


def _digits(value: str) -> str:
    return "".join(re.findall(r"\d", value))


def _excerpt(text: str, start: int, end: int, limit: int = 96) -> str:
    left = max(0, start - 24)
    right = min(len(text), end + 24)
    excerpt = re.sub(r"\s+", " ", text[left:right]).strip()
    if len(excerpt) <= limit:
        return excerpt
    return excerpt[: limit - 1].rstrip() + "…"


def _is_calendar_date(value: str) -> bool:
    if len(value) != 8 or not value.startswith(("19", "20")):
        return False
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return False
    return True


def _finding(kind: str, level: str, value: str, evidence: str) -> dict[str, str]:
    return {
        "kind": kind,
        "label": _KIND_LABELS[kind],
        "level": level,
        "value": value,
        "evidence": evidence,
    }


def scan_share_notice(value: Any) -> dict[str, Any]:
    text = normalize_notice(value)
    findings: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    contact_numbers: set[str] = set()

    def add(kind: str, level: str, normalized_value: str, match: re.Match[str]) -> None:
        key = (kind, normalized_value.casefold())
        if not normalized_value or key in seen:
            return
        seen.add(key)
        findings.append(
            _finding(kind, level, normalized_value, _excerpt(text, match.start(), match.end()))
        )
        if normalized_value.isdigit():
            contact_numbers.add(normalized_value)

    for pattern in (_GROUP_FORWARD, _GROUP_REVERSE):
        for match in pattern.finditer(text):
            digits = _digits(match.group("value"))
            if 5 <= len(digits) <= 13:
                add("qq_group", "high", digits, match)

    for match in _QQ.finditer(text):
        digits = _digits(match.group("value"))
        if 5 <= len(digits) <= 13:
            add("qq", "high", digits, match)

    for match in _WECHAT.finditer(text):
        add("wechat", "high", match.group("value"), match)

    for match in _PHONE.finditer(text):
        digits = _digits(match.group(0))
        if len(digits) == 11:
            add("phone", "high", digits, match)

    for match in _EMAIL.finditer(text):
        add("email", "high", match.group(0), match)

    for match in _URL.finditer(text):
        add("url", "high", match.group(0).rstrip(".,，。;；)）]】"), match)

    for match in _STANDALONE_NUMBER.finditer(text):
        digits = _digits(match.group("value"))
        if not 5 <= len(digits) <= 13 or digits in contact_numbers or _is_calendar_date(digits):
            continue
        context = text[max(0, match.start() - 18) : min(len(text), match.end() + 18)]
        if _NUMBER_SAFE_CONTEXT.search(context):
            continue
        add("number", "medium", digits, match)

    findings.sort(key=lambda item: (0 if item["level"] == "high" else 1, item["kind"], item["value"]))
    status = "risk" if any(item["level"] == "high" for item in findings) else "suspected" if findings else "clear"
    severity = "critical" if status == "risk" else "warning" if status == "suspected" else "none"
    fingerprint_payload = [
        {"kind": item["kind"], "level": item["level"], "value": item["value"]}
        for item in findings
    ]
    fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    summary = "、".join(
        f"{item['label']} {item['value']}" for item in findings[:4]
    )
    if len(findings) > 4:
        summary += f" 等{len(findings)}项"

    return {
        "status": status,
        "severity": severity,
        "fingerprint": fingerprint,
        "summary": summary,
        "findings": findings,
    }
