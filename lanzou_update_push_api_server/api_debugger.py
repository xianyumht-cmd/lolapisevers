from __future__ import annotations

import base64
import re
import time
from typing import Any
from urllib.parse import quote

import requests


_PATH_PARAMETER_RE = re.compile(r"\{([^{}]+)\}")


def fetch_openapi(base_url: str) -> dict[str, Any]:
    response = requests.get(f"{base_url.rstrip('/')}/openapi.json", timeout=5)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("OpenAPI response must be a JSON object")
    return data


def invoke_api(base_url: str, payload: dict[str, Any]) -> dict[str, Any]:
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
    started = time.time()
    response = requests.request(
        method,
        f"{base_url.rstrip('/')}{path}",
        params=query,
        json=body,
        timeout=timeout,
    )
    elapsed_ms = int((time.time() - started) * 1000)
    content_type = response.headers.get("content-type", "")
    result: dict[str, Any] = {
        "ok": response.ok,
        "status_code": response.status_code,
        "content_type": content_type,
        "elapsed_ms": elapsed_ms,
        "headers": {key: value for key, value in response.headers.items()},
        "request_url": response.url,
    }
    if "application/json" in content_type:
        try:
            result["json"] = response.json()
        except ValueError:
            result["text"] = response.text[:1_000_000]
    elif content_type.startswith("image/") or "image/svg+xml" in content_type:
        if len(response.content) > 5_000_000:
            raise ValueError("response image is larger than 5 MB")
        result["base64"] = base64.b64encode(response.content).decode("ascii")
    else:
        result["text"] = response.text[:1_000_000]
    return result
