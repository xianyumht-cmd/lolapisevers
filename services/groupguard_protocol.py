from __future__ import annotations

import re
import uuid
from typing import Any

DELIVERY_PROTOCOL = "groupguard-query-delivery.v1"
MAX_CLIENT_REQUEST_ID_CHARS = 128
MAX_TEXT_CHARS = 20_000
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_IMAGE_BASE64_CHARS = 16 * 1024 * 1024
MAX_FORWARD_NODES = 32
MAX_FORWARD_NODE_TEXT_CHARS = 4_000
MAX_RESPONSE_BYTES = 20 * 1024 * 1024

_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")

FEATURE_ALIASES = {
    "shard": "shard",
    "shard_query": "shard",
    "collection": "shard",
    "合集": "shard",
    "查合集": "shard",
    "aram": "aram",
    "aram_augments": "aram",
    "海符榜": "aram",
    "海克斯": "aram",
    "lolban": "lolban",
    "ban": "lolban",
    "查封号": "lolban",
    "battle": "battle",
    "cross": "battle",
    "cross_query": "battle",
    "查战绩": "battle",
    "scammer": "scammer",
    "scammer_query": "scammer",
    "查骗子": "scammer",
    "peer": "peer",
    "peer_query": "peer",
    "查同行": "peer",
    "dynamic": "dynamic",
    "dynamic_query": "dynamic",
}

REPORT_FEATURE_ALIASES = {
    "scammer_report": "scammer_report",
    "举报骗子": "scammer_report",
    "peer_report": "peer_report",
    "举报同行": "peer_report",
}


def canonical_feature(value: Any) -> str:
    return FEATURE_ALIASES.get(str(value or "").strip().lower(), "")


def canonical_report_feature(value: Any) -> str:
    return REPORT_FEATURE_ALIASES.get(str(value or "").strip().lower(), "")


def validate_request_id(
    value: Any,
    *,
    required: bool = False,
    generate_if_blank: bool = False,
) -> str:
    text = str(value or "").strip()
    if not text:
        if required:
            raise ValueError("request_id 不能为空")
        return uuid.uuid4().hex if generate_if_blank else ""
    if not _REQUEST_ID_RE.fullmatch(text):
        raise ValueError("request_id 只能包含字母、数字、点、横线、下划线和冒号，长度为 1-128")
    return text
