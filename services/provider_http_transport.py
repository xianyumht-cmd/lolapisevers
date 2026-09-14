from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Mapping

import requests


class ProviderResponseTooLargeError(ValueError, RuntimeError):
    """Provider response exceeded the configured hard byte limit."""


@dataclass(frozen=True)
class ProviderHttpResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes
    elapsed_ms: int = 0

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400


class ProviderHttpTransport:
    """Bounded standard HTTP transport for configurable provider requests.

    The default transport delegates to ``requests.request`` so it does not keep
    mutable cross-request session state. Callers that intentionally own a
    Session can inject it explicitly.
    """

    def __init__(
        self,
        *,
        session: Any = None,
        max_response_bytes: int = 2 * 1024 * 1024,
        connect_timeout: float = 3.0,
    ) -> None:
        self.session = session or requests
        self.max_response_bytes = max(1024, int(max_response_bytes))
        self.connect_timeout = max(0.1, float(connect_timeout))

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        json_body: Any = None,
        files: Any = None,
        timeout_seconds: float = 10.0,
        allow_redirects: bool = False,
    ) -> ProviderHttpResponse:
        timeout = max(0.1, float(timeout_seconds))
        response: requests.Response | None = None
        started = time.monotonic()
        try:
            response = self.session.request(
                str(method or "GET").upper(),
                str(url),
                headers=dict(headers or {}) or None,
                params=dict(params or {}) or None,
                data=dict(data or {}) or None,
                json=json_body,
                files=files,
                timeout=(min(self.connect_timeout, timeout), timeout),
                allow_redirects=allow_redirects,
                stream=True,
            )
            body = self._read_bounded(response)
            return ProviderHttpResponse(
                status_code=int(response.status_code),
                headers=dict(response.headers),
                body=body,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
        finally:
            if response is not None:
                response.close()

    def _read_bounded(self, response: requests.Response) -> bytes:
        declared = str(response.headers.get("Content-Length") or "").strip()
        if declared:
            try:
                declared_size = int(declared)
            except ValueError:
                declared_size = 0
            if declared_size > self.max_response_bytes:
                raise ProviderResponseTooLargeError("provider_response_too_large")

        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > self.max_response_bytes:
                raise ProviderResponseTooLargeError("provider_response_too_large")
            chunks.append(bytes(chunk))
        return b"".join(chunks)
