from __future__ import annotations

import copy
import hashlib
import json
import logging
import random
import socket
import ssl
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Dict, Mapping, Optional
from urllib.parse import urlsplit

import requests


RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class UpstreamError:
    error_class: str
    message: str
    retryable: bool
    status_code: int = 0


@dataclass(frozen=True)
class UpstreamResponse:
    ok: bool
    source_id: str
    status: str
    status_code: int = 0
    attempts: int = 0
    text: str = ""
    data: Any = None
    etag: str = ""
    last_modified: str = ""
    error: Optional[UpstreamError] = None
    elapsed_ms: float = 0.0
    shared: bool = False
    circuit_state: str = "closed"


@dataclass
class _CircuitState:
    consecutive_failures: int = 0
    open_until: float = 0.0
    last_error_class: str = ""
    last_error_at: float = 0.0
    last_success_at: float = 0.0


def _safe_source_id(value: str) -> str:
    normalized = str(value or "").strip()
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
    if not normalized or len(normalized) > 128 or any(ch not in allowed for ch in normalized):
        raise ValueError("source_id must use 1-128 ASCII letters, digits, dot, dash, or underscore")
    return normalized


def _safe_message(exc: BaseException, limit: int = 300) -> str:
    text = str(exc or exc.__class__.__name__).replace("\r", " ").replace("\n", " ").strip()
    return (text or exc.__class__.__name__)[:limit]


def classify_request_exception(exc: BaseException) -> UpstreamError:
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return UpstreamError("connect_timeout", _safe_message(exc), True)
    if isinstance(exc, requests.exceptions.ReadTimeout):
        return UpstreamError("read_timeout", _safe_message(exc), True)
    if isinstance(exc, requests.exceptions.Timeout):
        return UpstreamError("timeout", _safe_message(exc), True)
    if isinstance(exc, (requests.exceptions.SSLError, ssl.SSLError)):
        return UpstreamError("tls_error", _safe_message(exc), True)
    if isinstance(exc, socket.gaierror):
        return UpstreamError("dns_error", _safe_message(exc), True)
    if isinstance(exc, requests.exceptions.ConnectionError):
        lowered = _safe_message(exc).lower()
        if any(marker in lowered for marker in ("getaddrinfo failed", "name or service not known", "name resolution")):
            kind = "dns_error"
        elif any(marker in lowered for marker in ("certificate", "ssl", "tls")):
            kind = "tls_error"
        elif "connection refused" in lowered:
            kind = "connection_refused"
        elif "connection reset" in lowered:
            kind = "connection_reset"
        elif any(marker in lowered for marker in ("network is unreachable", "no route to host")):
            kind = "network_unreachable"
        else:
            kind = "connection_error"
        return UpstreamError(kind, _safe_message(exc), True)
    if isinstance(exc, json.JSONDecodeError):
        return UpstreamError("json_error", _safe_message(exc), False)
    if isinstance(exc, ValueError):
        return UpstreamError("validation_error", _safe_message(exc), False)
    if isinstance(exc, requests.exceptions.RequestException):
        return UpstreamError("request_error", _safe_message(exc), True)
    return UpstreamError("unexpected_error", _safe_message(exc), False)


def _redact_error(error: UpstreamError, url: str) -> UpstreamError:
    message = error.message
    parsed = urlsplit(url)
    for secret in (url, parsed.query, parsed.username or "", parsed.password or ""):
        if secret:
            message = message.replace(secret, "[redacted]")
    return UpstreamError(error.error_class, message[:300], error.retryable, error.status_code)


class UpstreamHttpClient:
    """Bounded HTTP client for named public upstreams.

    Logs and state use only ``source_id``. This class never logs a full URL.
    """

    def __init__(
        self,
        *,
        session: Optional[requests.Session] = None,
        connect_timeout: float = 3.0,
        read_timeout: float = 7.0,
        attempts: int = 2,
        base_backoff_seconds: float = 0.25,
        max_backoff_seconds: float = 2.0,
        circuit_failure_threshold: int = 3,
        circuit_open_seconds: float = 30.0,
        sleep_fn: Callable[[float], None] = time.sleep,
        monotonic_fn: Callable[[], float] = time.monotonic,
        random_fn: Callable[[], float] = random.random,
        logger: Optional[logging.Logger] = None,
        max_response_bytes: int = 4 * 1024 * 1024,
    ) -> None:
        self.session = session or requests.Session()
        self.connect_timeout = max(0.1, float(connect_timeout))
        self.read_timeout = max(0.1, float(read_timeout))
        self.attempts = max(1, min(int(attempts), MAX_ATTEMPTS))
        self.base_backoff_seconds = max(0.0, float(base_backoff_seconds))
        self.max_backoff_seconds = max(self.base_backoff_seconds, float(max_backoff_seconds))
        self.circuit_failure_threshold = max(1, int(circuit_failure_threshold))
        self.circuit_open_seconds = max(0.1, float(circuit_open_seconds))
        self.sleep_fn = sleep_fn
        self.monotonic_fn = monotonic_fn
        self.random_fn = random_fn
        self.logger = logger or logging.getLogger("LOLDataSystem")
        self.max_response_bytes = max(1024, min(int(max_response_bytes), 64 * 1024 * 1024))
        self._lock = threading.RLock()
        self._circuits: Dict[str, _CircuitState] = {}
        self._flights: Dict[str, Future[UpstreamResponse]] = {}

    def _state(self, source: str) -> _CircuitState:
        state = self._circuits.get(source)
        if state is None:
            state = _CircuitState()
            self._circuits[source] = state
        return state

    def _gate(self, source: str) -> tuple[bool, str]:
        now = self.monotonic_fn()
        with self._lock:
            state = self._state(source)
            if state.open_until > now:
                return False, "open"
            if state.open_until:
                state.open_until = 0.0
                return True, "half_open"
            return True, "closed"

    def _success(self, source: str) -> None:
        with self._lock:
            state = self._state(source)
            state.consecutive_failures = 0
            state.open_until = 0.0
            state.last_error_class = ""
            state.last_success_at = self.monotonic_fn()

    def _failure(self, source: str, error: UpstreamError) -> str:
        with self._lock:
            state = self._state(source)
            state.consecutive_failures += 1
            state.last_error_class = error.error_class
            state.last_error_at = self.monotonic_fn()
            if state.consecutive_failures >= self.circuit_failure_threshold:
                state.open_until = self.monotonic_fn() + self.circuit_open_seconds
                return "open"
            return "closed"

    def _retry_after(self, response: requests.Response) -> Optional[float]:
        value = str(response.headers.get("Retry-After") or "").strip()
        if not value:
            return None
        try:
            return max(0.0, min(float(value), self.max_backoff_seconds))
        except ValueError:
            try:
                delay = parsedate_to_datetime(value).timestamp() - time.time()
                return max(0.0, min(delay, self.max_backoff_seconds))
            except Exception:
                return None

    def _backoff(self, attempt_index: int, response: Optional[requests.Response] = None) -> float:
        retry_after = self._retry_after(response) if response is not None else None
        if retry_after is not None:
            return retry_after
        jitter = self.base_backoff_seconds * max(0.0, min(float(self.random_fn()), 1.0))
        return min(self.max_backoff_seconds, self.base_backoff_seconds * (2 ** attempt_index) + jitter)

    @staticmethod
    def _close(response: Optional[requests.Response]) -> None:
        if response is not None:
            close = getattr(response, "close", None)
            if callable(close):
                close()

    @staticmethod
    def _headers(headers: Optional[Mapping[str, str]], etag: str, last_modified: str) -> Dict[str, str]:
        merged = {"Accept": "application/json,text/plain,*/*", "User-Agent": "LOLApiServers/1.0"}
        merged.update({str(k): str(v) for k, v in dict(headers or {}).items()})
        if etag:
            merged["If-None-Match"] = etag
        if last_modified:
            merged["If-Modified-Since"] = last_modified
        return merged

    @staticmethod
    def _flight_key(source: str, method: str, url: str, headers: Mapping[str, str]) -> str:
        canonical_headers = "\n".join(
            f"{str(key).lower()}:{str(value)}" for key, value in sorted(headers.items(), key=lambda item: str(item[0]).lower())
        )
        digest = hashlib.sha256(
            f"{method.upper()}\n{url}\n{canonical_headers}".encode("utf-8")
        ).hexdigest()
        return f"{source}:{digest}"

    def _read_bounded_text(self, response: requests.Response) -> str:
        declared = str(response.headers.get("Content-Length") or "").strip()
        if declared:
            try:
                declared_size = int(declared)
            except ValueError:
                declared_size = -1
            if declared_size > self.max_response_bytes:
                raise ValueError("upstream response exceeds byte limit")
        iterator = getattr(response, "iter_content", None)
        if callable(iterator):
            chunks = []
            total = 0
            for chunk in iterator(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > self.max_response_bytes:
                    raise ValueError("upstream response exceeds byte limit")
                chunks.append(bytes(chunk))
            raw = b"".join(chunks)
            encoding = str(getattr(response, "encoding", "") or "utf-8")
            return raw.decode(encoding, errors="replace").replace("\x00", "").strip()
        # Compatibility for lightweight response doubles used by callers/tests.
        text = str(getattr(response, "text", "") or "")
        if len(text.encode("utf-8")) > self.max_response_bytes:
            raise ValueError("upstream response exceeds byte limit")
        return text.replace("\x00", "").strip()

    def request(
        self,
        source_id: str,
        url: str,
        *,
        method: str = "GET",
        headers: Optional[Mapping[str, str]] = None,
        etag: str = "",
        last_modified: str = "",
        parse_json: bool = False,
        validate: Optional[Callable[[Any], None]] = None,
        attempts: Optional[int] = None,
        connect_timeout: Optional[float] = None,
        read_timeout: Optional[float] = None,
        singleflight: bool = True,
    ) -> UpstreamResponse:
        source = _safe_source_id(source_id)
        normalized_url = str(url or "").strip()
        parsed = urlsplit(normalized_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return UpstreamResponse(False, source, "failed", error=UpstreamError("invalid_url", "upstream URL must be http or https", False))

        allowed, gate_state = self._gate(source)
        if not allowed:
            with self._lock:
                failures = self._state(source).consecutive_failures
            return UpstreamResponse(
                False,
                source,
                "circuit_open",
                error=UpstreamError("circuit_open", f"source circuit open after {failures} failures", True),
                circuit_state="open",
            )

        request_headers = self._headers(headers, etag, last_modified)
        flight_key = self._flight_key(source, method, normalized_url, request_headers)
        flight: Optional[Future[UpstreamResponse]] = None
        owner = True
        if singleflight:
            with self._lock:
                flight = self._flights.get(flight_key)
                if flight is None:
                    flight = Future()
                    self._flights[flight_key] = flight
                else:
                    owner = False
        if not owner and flight is not None:
            result = flight.result()
            return UpstreamResponse(**{**result.__dict__, "shared": True})

        try:
            result = self._request_owned(
                source,
                normalized_url,
                method=method,
                headers=headers,
                etag=etag,
                last_modified=last_modified,
                parse_json=parse_json,
                validate=validate,
                attempts=attempts,
                connect_timeout=connect_timeout,
                read_timeout=read_timeout,
                gate_state=gate_state,
                request_headers=request_headers,
            )
            if flight is not None and not flight.done():
                flight.set_result(result)
            return result
        except Exception as exc:
            error = _redact_error(classify_request_exception(exc), normalized_url)
            circuit = self._failure(source, error) if error.retryable else gate_state
            result = UpstreamResponse(False, source, "failed", error=error, circuit_state=circuit)
            if flight is not None and not flight.done():
                flight.set_result(result)
            return result
        finally:
            if singleflight:
                with self._lock:
                    if self._flights.get(flight_key) is flight:
                        self._flights.pop(flight_key, None)

    def _request_owned(
        self,
        source: str,
        url: str,
        *,
        method: str,
        headers: Optional[Mapping[str, str]],
        etag: str,
        last_modified: str,
        parse_json: bool,
        validate: Optional[Callable[[Any], None]],
        attempts: Optional[int],
        connect_timeout: Optional[float],
        read_timeout: Optional[float],
        gate_state: str,
        request_headers: Mapping[str, str],
    ) -> UpstreamResponse:
        started = self.monotonic_fn()
        limit = max(1, min(int(attempts or self.attempts), MAX_ATTEMPTS))
        timeout = (max(0.1, float(connect_timeout or self.connect_timeout)), max(0.1, float(read_timeout or self.read_timeout)))
        last_error: Optional[UpstreamError] = None

        for index in range(limit):
            response: Optional[requests.Response] = None
            try:
                response = self.session.request(
                    method.upper(),
                    url,
                    headers=dict(request_headers),
                    timeout=timeout,
                    stream=True,
                )
                response_etag = str(response.headers.get("ETag") or "")
                response_last_modified = str(response.headers.get("Last-Modified") or "")

                if response.status_code == 304:
                    self._success(source)
                    return UpstreamResponse(True, source, "not_modified", 304, index + 1, etag=response_etag or etag, last_modified=response_last_modified or last_modified, elapsed_ms=round((self.monotonic_fn() - started) * 1000, 1))

                if response.status_code in RETRYABLE_STATUS_CODES and index + 1 < limit:
                    last_error = UpstreamError("http_retryable", f"upstream returned HTTP {response.status_code}", True, response.status_code)
                    delay = self._backoff(index, response)
                    self._close(response)
                    response = None
                    self.sleep_fn(delay)
                    continue

                if not response.ok:
                    retryable = response.status_code in RETRYABLE_STATUS_CODES
                    error = UpstreamError("http_error", f"upstream returned HTTP {response.status_code}", retryable, response.status_code)
                    circuit = self._failure(source, error) if retryable else gate_state
                    return UpstreamResponse(False, source, "failed", response.status_code, index + 1, etag=response_etag, last_modified=response_last_modified, error=error, elapsed_ms=round((self.monotonic_fn() - started) * 1000, 1), circuit_state=circuit)

                text = self._read_bounded_text(response)
                data: Any = None
                if parse_json:
                    try:
                        data = json.loads(text) if text else {}
                    except json.JSONDecodeError as exc:
                        error = classify_request_exception(exc)
                        return UpstreamResponse(False, source, "failed", response.status_code, index + 1, text=text[:1000], etag=response_etag, last_modified=response_last_modified, error=error, elapsed_ms=round((self.monotonic_fn() - started) * 1000, 1), circuit_state=gate_state)
                    if validate is not None:
                        try:
                            validate(data)
                        except Exception as exc:
                            error = UpstreamError("validation_error", _safe_message(exc), False)
                            return UpstreamResponse(False, source, "failed", response.status_code, index + 1, text=text[:1000], data=data, etag=response_etag, last_modified=response_last_modified, error=error, elapsed_ms=round((self.monotonic_fn() - started) * 1000, 1), circuit_state=gate_state)

                self._success(source)
                return UpstreamResponse(True, source, "ok", response.status_code, index + 1, text=text, data=data, etag=response_etag, last_modified=response_last_modified, elapsed_ms=round((self.monotonic_fn() - started) * 1000, 1))
            except Exception as exc:
                last_error = _redact_error(classify_request_exception(exc), url)
                if not last_error.retryable or index + 1 >= limit:
                    circuit = self._failure(source, last_error) if last_error.retryable else gate_state
                    return UpstreamResponse(False, source, "failed", attempts=index + 1, error=last_error, elapsed_ms=round((self.monotonic_fn() - started) * 1000, 1), circuit_state=circuit)
                self.sleep_fn(self._backoff(index))
            finally:
                self._close(response)

        error = last_error or UpstreamError("request_error", "upstream request failed", True)
        circuit = self._failure(source, error)
        return UpstreamResponse(False, source, "failed", attempts=limit, error=error, elapsed_ms=round((self.monotonic_fn() - started) * 1000, 1), circuit_state=circuit)

    def get_json(self, source_id: str, url: str, *, etag: str = "", last_modified: str = "", validate: Optional[Callable[[Any], None]] = None, **kwargs: Any) -> UpstreamResponse:
        return self.request(source_id, url, method="GET", etag=etag, last_modified=last_modified, parse_json=True, validate=validate, **kwargs)

    def state(self, source_id: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            now = self.monotonic_fn()
            sources = [_safe_source_id(source_id)] if source_id else sorted(self._circuits)
            result: Dict[str, Any] = {}
            for source in sources:
                state = copy.copy(self._state(source))
                result[source] = {
                    "circuit_state": "open" if state.open_until > now else "closed",
                    "consecutive_failures": state.consecutive_failures,
                    "open_remaining_seconds": max(0.0, round(state.open_until - now, 3)),
                    "last_error_class": state.last_error_class,
                    "last_error_at_monotonic": state.last_error_at,
                    "last_success_at_monotonic": state.last_success_at,
                    "in_flight": any(key.startswith(source + ":") for key in self._flights),
                }
            return result
