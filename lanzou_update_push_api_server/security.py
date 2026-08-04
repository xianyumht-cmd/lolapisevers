from __future__ import annotations

import hmac
import ipaddress
import os

from fastapi import Request
from fastapi.responses import JSONResponse


PUBLIC_PATHS = {
    "/",
    "/ui",
    "/legacy-ui",
    "/health",
    "/security/status",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon.ico",
}
PUBLIC_PATH_PREFIXES = (
    "/control-assets/",
)


def configured_admin_token() -> str:
    return os.getenv("WEBUI_ADMIN_TOKEN", "").strip()


def security_status() -> dict[str, object]:
    return {
        "ok": True,
        "token_configured": bool(configured_admin_token()),
        "local_only_without_token": True,
        "header_name": "x-admin-token",
    }


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


def _is_public_path(path: str) -> bool:
    return path in PUBLIC_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_PATH_PREFIXES)


def _audit(
    request: Request,
    *,
    action: str,
    ok: bool,
    detail: dict[str, object] | None = None,
) -> None:
    try:
        from .maintenance import append_audit

        append_audit(
            action=action,
            ok=ok,
            client=request.client.host if request.client else "",
            method=request.method,
            path=request.url.path,
            detail=detail,
        )
    except Exception:
        # An audit-write failure must not take down the control plane.
        pass


async def control_api_guard(request: Request, call_next):
    path = request.url.path
    if _is_public_path(path):
        return await call_next(request)

    allowed, reason = request_is_authorized(request)
    if not allowed:
        _audit(request, action="authorization_denied", ok=False, detail={"reason": reason})
        status_code = 401 if configured_admin_token() else 403
        return JSONResponse(
            status_code=status_code,
            content={
                "ok": False,
                "error": reason,
                "security": security_status(),
            },
        )

    response = await call_next(request)
    if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
        _audit(
            request,
            action="control_api_mutation",
            ok=response.status_code < 400,
            detail={"status_code": response.status_code},
        )
    return response
