from __future__ import annotations

import base64
import hashlib
import uuid
from typing import Any, Dict, Iterable, List, Mapping, Optional

from utils.formatters import pct
from services.groupguard_protocol import (
    DELIVERY_PROTOCOL,
    MAX_FORWARD_NODE_TEXT_CHARS,
    MAX_FORWARD_NODES,
    MAX_IMAGE_BYTES,
    MAX_TEXT_CHARS,
    validate_request_id,
)


DEFAULT_FORWARD_CHUNK_CHARS = 1200


def request_id() -> str:
    return uuid.uuid4().hex


def safe_client_request_id(value: Any) -> str:
    return validate_request_id(value)


def normalize_capabilities(value: Any) -> Dict[str, bool]:
    raw = value if isinstance(value, Mapping) else {}
    return {
        "text": bool(raw.get("text", True)),
        "image": bool(raw.get("image", True)),
        "forward": bool(raw.get("forward", True)),
    }


def normalize_preferred(value: Any) -> str:
    preferred = str(value or "auto").strip().lower()
    return preferred if preferred in {"auto", "text", "image", "forward"} else "auto"


def _hero_label(payload: Mapping[str, Any]) -> str:
    hero = payload.get("hero") if isinstance(payload.get("hero"), Mapping) else {}
    title = str(hero.get("title") or "").strip()
    name = str(hero.get("name") or "").strip()
    alias = str(hero.get("alias") or "").strip()
    values = [item for item in (title, name) if item]
    return " · ".join(values) or alias or "未知英雄"


def _stale_suffix(payload: Mapping[str, Any]) -> str:
    if not bool(payload.get("stale")):
        return ""
    age = int(payload.get("snapshot_age_seconds") or payload.get("stale_age_seconds") or 0)
    if age > 0:
        return f"\n数据状态：上游暂不可用，正在使用约 {age} 秒前的最近有效结果"
    return "\n数据状态：上游暂不可用，正在使用最近有效结果"


def format_shard_text(payload: Mapping[str, Any]) -> str:
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    lines = [
        f"英雄合集｜{_hero_label(payload)}",
        f"整体选择率：{pct(payload.get('pick_rate'))}",
        f"整体胜率：{pct(payload.get('win_rate'))}",
        f"合集数量：{payload.get('count') or len(rows)}",
        "",
    ]
    if not rows:
        lines.append("暂无可用合集数据")
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            continue
        name = str(row.get("name") or row.get("id") or "未知合集").strip()
        lines.append(
            f"{index}. {name}｜选择率 {pct(row.get('pick_rate'))}｜胜率 {pct(row.get('win_rate'))}"
        )
    return "\n".join(lines).strip() + _stale_suffix(payload)


def _item_names(value: Any, limit: int = 8) -> str:
    if not isinstance(value, list):
        return "-"
    names: List[str] = []
    for item in value[:limit]:
        if isinstance(item, Mapping):
            text = str(item.get("name") or item.get("key") or item.get("id") or "").strip()
        else:
            text = str(item or "").strip()
        if text:
            names.append(text)
    return "、".join(names) or "-"


def format_aram_text(payload: Mapping[str, Any]) -> str:
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    lines = [
        f"海克斯大乱斗强化榜｜{_hero_label(payload)}",
        f"收录：{payload.get('total') or len(rows)} 项，展示 TOP {len(rows)}",
        "",
    ]
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            continue
        name = str(row.get("name") or "未知强化").strip()
        rarity = str(row.get("rarity") or "-").strip()
        lines.append(
            f"{index}. {name}｜品质 {rarity}｜强度 {pct(row.get('performance'))}｜热度 {pct(row.get('popular'))}"
        )
        desc = str(row.get("desc") or "").strip()
        if desc:
            lines.append(f"   {desc}")

    starter = payload.get("starter_items") if isinstance(payload.get("starter_items"), list) else []
    boots = payload.get("boots") if isinstance(payload.get("boots"), list) else []
    starter_items = starter[0].get("items") if starter and isinstance(starter[0], Mapping) else []
    boot_items = boots[0].get("items") if boots and isinstance(boots[0], Mapping) else []
    item_builds = payload.get("item_builds") if isinstance(payload.get("item_builds"), list) else []
    first_build = item_builds[0].get("items") if item_builds and isinstance(item_builds[0], Mapping) else []
    lines.extend(
        [
            "",
            f"推荐出门装：{_item_names(starter_items)}",
            f"核心出装：{_item_names(first_build)}",
            f"鞋子：{_item_names(boot_items)}",
            f"召唤师技能：{_item_names(payload.get('summoner_spells'), 4)}",
            f"技能优先级：{_item_names(payload.get('skill_order'), 6)}",
        ]
    )
    return "\n".join(lines).strip() + _stale_suffix(payload)


def split_forward_text(text: str, *, max_chars: int = DEFAULT_FORWARD_CHUNK_CHARS) -> List[str]:
    limit = max(200, min(int(max_chars), MAX_FORWARD_NODE_TEXT_CHARS))
    lines = str(text or "").splitlines() or [""]
    chunks: List[str] = []
    current = ""
    for line in lines:
        candidate = line if not current else f"{current}\n{line}"
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        remainder = line
        while len(remainder) > limit:
            chunks.append(remainder[:limit])
            remainder = remainder[limit:]
        current = remainder
    if current or not chunks:
        chunks.append(current)
    if len(chunks) > MAX_FORWARD_NODES:
        raise ValueError(f"内容超过合并转发上限（最多 {MAX_FORWARD_NODES} 段），请缩短结果或改用文件交付")
    return chunks


def text_delivery(text: str) -> Dict[str, Any]:
    normalized = str(text or "")
    if len(normalized) > MAX_TEXT_CHARS:
        raise ValueError(f"文本超过交付上限（最多 {MAX_TEXT_CHARS} 个字符）")
    return {
        "kind": "segments",
        "segments": [{"type": "text", "text": normalized}],
    }


def forward_delivery(text: str) -> Dict[str, Any]:
    nodes = [
        {"segments": [{"type": "text", "text": chunk}]}
        for chunk in split_forward_text(text)
    ]
    return {
        "kind": "forward",
        "segments": [{"type": "forward", "nodes": nodes}],
    }


def image_delivery(body: bytes, *, mime_type: str = "image/png", filename: str = "query.png") -> Dict[str, Any]:
    raw = bytes(body)
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError(f"图片超过交付上限（最多 {MAX_IMAGE_BYTES} 字节）")
    digest = hashlib.sha256(raw).hexdigest()
    return {
        "kind": "segments",
        "segments": [
            {
                "type": "image",
                "mime_type": str(mime_type or "image/png"),
                "encoding": "base64",
                "data": base64.b64encode(raw).decode("ascii"),
                "filename": str(filename or "query.png")[:128],
                "bytes": len(raw),
                "sha256": digest,
            }
        ],
    }


def choose_text_delivery(text: str, capabilities: Mapping[str, bool], preferred: str) -> Optional[Dict[str, Any]]:
    if preferred == "forward":
        if capabilities.get("forward"):
            return forward_delivery(text)
        if capabilities.get("text") and len(str(text or "")) <= MAX_TEXT_CHARS:
            return text_delivery(text)
        return None
    if preferred == "text":
        if capabilities.get("text") and len(str(text or "")) <= MAX_TEXT_CHARS:
            return text_delivery(text)
        if capabilities.get("forward"):
            return forward_delivery(text)
        return None
    if len(text) > 3500 and capabilities.get("forward"):
        return forward_delivery(text)
    if capabilities.get("text") and len(str(text or "")) <= MAX_TEXT_CHARS:
        return text_delivery(text)
    if capabilities.get("forward"):
        return forward_delivery(text)
    return None


def safe_meta(payload: Mapping[str, Any], *, delivery_fallback: str = "") -> Dict[str, Any]:
    hero = payload.get("hero") if isinstance(payload.get("hero"), Mapping) else {}
    data = payload.get("data") if isinstance(payload.get("data"), Mapping) else {}
    meta: Dict[str, Any] = {
        "source": str(payload.get("source") or ""),
        "provider": str(payload.get("provider") or payload.get("by") or ""),
        "stale": bool(payload.get("stale") or str(payload.get("source") or "") in {"stale", "snapshot"}),
        "snapshot_age_seconds": int(payload.get("snapshot_age_seconds") or payload.get("stale_age_seconds") or 0),
        "updated_at": str(payload.get("updated_at") or ""),
        "count": int(payload.get("count") or payload.get("total") or 0),
        "delivery_fallback": str(delivery_fallback or ""),
    }
    if hero:
        meta["hero"] = {
            "alias": str(hero.get("alias") or ""),
            "name": str(hero.get("name") or ""),
            "title": str(hero.get("title") or ""),
        }
    if data:
        meta["account_status"] = str(data.get("status") or "")
        meta["stale_origin"] = str(payload.get("stale_origin") or "")
    return meta


def success_envelope(
    *,
    feature: str,
    delivery: Mapping[str, Any],
    meta: Optional[Mapping[str, Any]] = None,
    client_request_id: str = "",
    server_request_id: str = "",
) -> Dict[str, Any]:
    return {
        "protocol": DELIVERY_PROTOCOL,
        "ok": True,
        "feature": str(feature),
        "request_id": server_request_id or request_id(),
        "client_request_id": safe_client_request_id(client_request_id),
        "delivery": dict(delivery),
        "error": None,
        "retry": {"allowed": False, "after_seconds": 0},
        "meta": dict(meta or {}),
    }


def error_envelope(
    *,
    feature: str,
    code: str,
    user_message: str,
    retryable: bool,
    retry_after_seconds: int = 0,
    client_request_id: str = "",
    server_request_id: str = "",
) -> Dict[str, Any]:
    message = str(user_message or "请求失败，请稍后再试").strip()[:500]
    return {
        "protocol": DELIVERY_PROTOCOL,
        "ok": False,
        "feature": str(feature or "unknown"),
        "request_id": server_request_id or request_id(),
        "client_request_id": safe_client_request_id(client_request_id),
        "delivery": text_delivery(message),
        "error": {
            "code": str(code or "request_failed")[:96],
            "user_message": message,
            "retryable": bool(retryable),
        },
        "retry": {
            "allowed": bool(retryable),
            "after_seconds": max(0, min(int(retry_after_seconds or 0), 3600)),
        },
        "meta": {},
    }
