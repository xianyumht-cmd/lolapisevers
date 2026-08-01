from __future__ import annotations

import base64
import json
import re
import time
from typing import Any
from urllib.parse import quote

import requests


_PATH_PARAMETER_RE = re.compile(r"\{([^{}]+)\}")
_MAX_DEBUG_RESPONSE_BYTES = 5_000_000


def _read_bounded(response: requests.Response, limit: int = _MAX_DEBUG_RESPONSE_BYTES) -> bytes:
    declared = str(getattr(response, "headers", {}).get("content-length") or "").strip()
    if declared:
        try:
            if int(declared) > limit:
                raise ValueError("response is larger than the debugger limit")
        except ValueError as exc:
            if "larger" in str(exc):
                raise
    iterator = getattr(response, "iter_content", None)
    if callable(iterator):
        chunks: list[bytes] = []
        total = 0
        for chunk in iterator(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > limit:
                raise ValueError("response is larger than the debugger limit")
            chunks.append(bytes(chunk))
        return b"".join(chunks)
    body = bytes(getattr(response, "content", b""))
    if len(body) > limit:
        raise ValueError("response is larger than the debugger limit")
    return body


def fetch_openapi(base_url: str, admin_token: str = "") -> dict[str, Any]:
    headers = {"x-admin-token": admin_token} if admin_token else {}
    response = requests.get(
        f"{base_url.rstrip('/')}/openapi.json",
        timeout=5,
        headers=headers,
        stream=True,
    )
    try:
        response.raise_for_status()
        data = json.loads(_read_bounded(response, 2_000_000).decode("utf-8"))
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()
    if not isinstance(data, dict):
        raise ValueError("OpenAPI response must be a JSON object")
    return data


def invoke_api(
    base_url: str,
    payload: dict[str, Any],
    *,
    admin_token: str = "",
) -> dict[str, Any]:
    method = str(payload.get("method") or "GET").upper()
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        raise ValueError("unsupported HTTP method")

    path = str(payload.get("path") or "").strip()
    if not path.startswith("/") or "://" in path or ".." in path:
        raise ValueError("path must be a safe relative API path")
    if path == "/admin/invoke":
        raise ValueError("recursive invocation is not allowed")

    raw_query = payload.get("query") or {}
    if not isinstance(raw_query, dict):
        raise ValueError("query must be an object")
    query = dict(raw_query)

    for parameter_name in _PATH_PARAMETER_RE.findall(path):
        if parameter_name not in query:
            raise ValueError(f"missing path parameter: {parameter_name}")
        value = query.pop(parameter_name)
        text = str(value).strip()
        if not text or (text.startswith("<") and text.endswith(">")):
            raise ValueError(f"path parameter is not filled: {parameter_name}")
        path = path.replace(f"{{{parameter_name}}}", quote(text, safe=""))

    timeout = max(1.0, min(120.0, float(payload.get("timeout") or 30.0)))
    body = payload.get("json")
    headers = {"x-admin-token": admin_token} if admin_token else {}
    started = time.time()
    response = requests.request(
        method,
        f"{base_url.rstrip('/')}{path}",
        params=query,
        json=body,
        headers=headers,
        timeout=timeout,
        stream=True,
    )
    try:
        raw = _read_bounded(response)
        elapsed_ms = int((time.time() - started) * 1000)
        content_type = response.headers.get("content-type", "")
        result: dict[str, Any] = {
            "ok": response.ok,
            "status_code": response.status_code,
            "content_type": content_type,
            "elapsed_ms": elapsed_ms,
            "headers": {key: value for key, value in response.headers.items()},
            "request_url": str(getattr(response, "url", f"{base_url.rstrip('/')}{path}")),
        }
        if "application/json" in content_type:
            try:
                result["json"] = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                result["text"] = raw.decode("utf-8", errors="replace")[:1_000_000]
        elif content_type.startswith("image/") or "image/svg+xml" in content_type:
            result["base64"] = base64.b64encode(raw).decode("ascii")
        else:
            result["text"] = raw.decode("utf-8", errors="replace")[:1_000_000]
        return result
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()
