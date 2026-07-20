from __future__ import annotations

import hmac
import ipaddress
import os
from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import JSONResponse


PUBLIC_PATHS = {
    "/",
    "/ui",
    "/legacy-ui",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon.ico",
}


@dataclass(frozen=True)
class SecurityStatus:
    token_configured: bool
    local_only_without_token: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "token_configured": self.token_configured,
            "local_only_without_token": self.local_only_without_token,
            "header_name": "x-admin-token",
        }


def configured_admin_token() -> str:
    return os.getenv("WEBUI_ADMIN_TOKEN", "").strip()


def security_status() -> SecurityStatus:
    return SecurityStatus(token_configured=bool(configured_admin_token()))


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    normalized = host.strip().strip("[]")
    if normalized.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _provided_token(request: Request) -> str:
    direct = request.headers.get("x-admin-token", "").strip()
    if direct:
        return direct
    authorization = request.headers.get("authorization", "").strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def request_is_authorized(request: Request) -> tuple[bool, str]:
    expected = configured_admin_token()
    client_host = request.client.host if request.client else ""
    if expected:
        supplied = _provided_token(request)
        if supplied and hmac.compare_digest(supplied, expected):
            return True, "token"
        return False, "admin token required"
    if _is_loopback(client_host):
        return True, "loopback"
    return False, "configure WEBUI_ADMIN_TOKEN before using the control API over the network"


async def control_api_guard(request: Request, call_next):
    path = request.url.path
    if path in PUBLIC_PATHS:
        return await call_next(request)

    allowed, reason = request_is_authorized(request)
    if allowed:
        return await call_next(request)

    status_code = 401 if configured_admin_token() else 403
    return JSONResponse(
        status_code=status_code,
        content={
            "ok": False,
            "error": reason,
            "security": security_status().to_dict(),
        },
    )
