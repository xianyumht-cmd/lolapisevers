from __future__ import annotations

import ipaddress
import os
import secrets
from typing import Optional

from fastapi import HTTPException, Request


def configured_write_token() -> str:
    return str(
        os.getenv("GROUPGUARD_WRITE_TOKEN")
        or os.getenv("WEBUI_ADMIN_TOKEN")
        or ""
    ).strip()


def _presented_token(request: Request) -> str:
    header = str(request.headers.get("x-groupguard-token") or request.headers.get("x-admin-token") or "").strip()
    if header:
        return header
    authorization = str(request.headers.get("authorization") or "").strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def _peer_host(request: Request) -> str:
    client: Optional[object] = getattr(request, "client", None)
    return str(getattr(client, "host", "") or "").strip()


def is_loopback_request(request: Request) -> bool:
    host = _peer_host(request)
    if host == "testclient":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def require_control_access(request: Request) -> None:
    expected = configured_write_token()
    presented = _presented_token(request)
    if expected:
        if not presented or not secrets.compare_digest(presented, expected):
            raise HTTPException(status_code=401, detail="管理员凭据无效")
        return
    if not is_loopback_request(request):
        raise HTTPException(status_code=403, detail="未配置写入 token 时仅允许本机访问")
