from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import requests

from .config import AppConfig, WatcherConfig


_MAX_HTML_BYTES = 2 * 1024 * 1024
_MAX_JSON_BYTES = 4 * 1024 * 1024


def _request_with_stream(call, *args, **kwargs):
    try:
        return call(*args, stream=True, **kwargs)
    except TypeError:
        # Compatibility for small response doubles used by offline tests.
        return call(*args, **kwargs)


def _bounded_bytes(response: Any, limit: int) -> bytes:
    headers = getattr(response, "headers", {}) or {}
    declared = str(headers.get("content-length") or headers.get("Content-Length") or "").strip()
    if declared:
        try:
            if int(declared) > limit:
                raise ProviderError("response_too_large", retryable=False)
        except ValueError:
            pass
    iterator = getattr(response, "iter_content", None)
    if callable(iterator):
        chunks: list[bytes] = []
        total = 0
        for chunk in iterator(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > limit:
                raise ProviderError("response_too_large", retryable=False)
            chunks.append(bytes(chunk))
        return b"".join(chunks)
    content = getattr(response, "content", None)
    if content is None:
        content = str(getattr(response, "text", "") or "").encode("utf-8")
    raw = bytes(content)
    if len(raw) > limit:
        raise ProviderError("response_too_large", retryable=False)
    return raw


def _bounded_json(response: Any, limit: int = _MAX_JSON_BYTES) -> Any:
    if not callable(getattr(response, "iter_content", None)) and hasattr(response, "_payload"):
        return response.json()
    raw = _bounded_bytes(response, limit)
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ProviderError("invalid_json_response", retryable=False) from exc


class ProviderError(RuntimeError):
    """Raised with a safe machine-readable code for provider failures."""

    def __init__(
        self,
        error_code: str = "provider_error",
        *,
        retryable: bool = True,
        status_code: int | None = None,
        attempts: list[dict[str, Any]] | None = None,
    ) -> None:
        candidate = str(error_code or "").strip().lower()
        safe_error_code = (
            candidate
            if re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,63}", candidate)
            else "provider_error"
        )
        super().__init__(safe_error_code)
        self.error_code = safe_error_code
        self.retryable = retryable
        self.status_code = status_code
        self.attempts = list(attempts or [])


def _safe_identifier(value: Any, fallback: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(value or "").strip()).strip("-")
    return cleaned[:64] or fallback


def _provider_failure(exc: Exception) -> dict[str, Any]:
    status_code = None
    retryable = True
    if isinstance(exc, ProviderError):
        error_code = exc.error_code
        status_code = exc.status_code
        retryable = exc.retryable
    elif isinstance(exc, requests.ConnectTimeout):
        error_code = "connect_timeout"
    elif isinstance(exc, requests.ReadTimeout):
        error_code = "read_timeout"
    elif isinstance(exc, requests.Timeout):
        error_code = "timeout"
    elif isinstance(exc, requests.ConnectionError):
        error_code = "connection_error"
    elif isinstance(exc, requests.HTTPError):
        error_code = "http_status"
        response = getattr(exc, "response", None)
        candidate = getattr(response, "status_code", None)
        status_code = int(candidate) if isinstance(candidate, int) else None
        retryable = status_code is None or status_code == 429 or status_code >= 500
    elif isinstance(exc, (ValueError, json.JSONDecodeError)):
        error_code = "invalid_response"
        retryable = False
    else:
        error_code = "provider_error"
    result: dict[str, Any] = {
        "error_code": error_code,
        "error_class": type(exc).__name__,
        "retryable": retryable,
    }
    if status_code is not None:
        result["status_code"] = status_code
    return result


def _stable_file_id(value: Any) -> str:
    """Remove temporary Lanzou query/fragment data from file IDs."""
    text = str(value or "").strip()
    return text.split("?", 1)[0].split("#", 1)[0].strip()


def _stable_file_link(value: Any) -> str:
    """Remove temporary query/fragment data from Lanzou share links."""
    text = str(value or "").strip()
    lowered = text.lower()
    if not any(token in lowered for token in ("lanzou", "lanzn.com", "lanwp.com")):
        return text
    return text.split("?", 1)[0].split("#", 1)[0].strip()


def _stable_modified_time(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?", value):
        return value
    if re.fullmatch(r"\d{1,2}[-/.]\d{1,2}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?", value):
        return value
    return ""


@dataclass(frozen=True)
class FileEntry:
    id: str
    name: str
    size: str = ""
    modified_time: str = ""
    link: str = ""
    icon: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def fingerprint_payload(self) -> dict[str, str]:
        return {
            "id": _stable_file_id(self.id),
            "name": self.name,
            "size": self.size,
            "modified_time": _stable_modified_time(self.modified_time),
            "link": _stable_file_link(self.link),
        }

    def canonical_fingerprint_payload(self) -> dict[str, str]:
        """Return provider-independent fields used for change detection."""
        return {
            "key": canonical_file_key(self),
            "size": re.sub(r"\s+", " ", self.size).strip().casefold(),
            "modified_time": _stable_modified_time(self.modified_time),
        }


def canonical_file_key(file: FileEntry) -> str:
    """Identify the same visible file even when providers expose different IDs.

    File names are the only identifier consistently exposed by both the native
    Lanzou scraper and third-party API. Provider-specific IDs and download
    links are intentionally used only as fallbacks.
    """
    normalized_name = unicodedata.normalize("NFKC", str(file.name or ""))
    normalized_name = re.sub(r"\s+", " ", normalized_name).strip().casefold()
    if normalized_name:
        return f"name:{normalized_name}"
    stable_link = _stable_file_link(file.link).rstrip("/").casefold()
    if stable_link:
        return f"link:{stable_link}"
    return f"id:{_stable_file_id(file.id).casefold()}"


@dataclass(frozen=True)
class ShareSnapshot:
    watcher_id: str
    title: str
    url: str
    provider: str
    fetched_at: str
    files: list[FileEntry]
    raw_status: dict[str, Any] = field(default_factory=dict)

    @property
    def signature(self) -> str:
        payload = sorted(
            (file.canonical_fingerprint_payload() for file in self.files),
            key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def provider_signature(self) -> str:
        payload = sorted(
            (file.fingerprint_payload() for file in self.files),
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "watcher_id": self.watcher_id,
            "title": self.title,
            "url": self.url,
            "provider": self.provider,
            "fetched_at": self.fetched_at,
            "signature": self.signature,
            "file_count": len(self.files),
            "files": [file.__dict__ for file in self.files],
            "raw_status": self.raw_status,
        }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_html_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]*>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_title(page_html: str, fallback: str) -> str:
    match = re.search(r"<title>(.*?)</title>", page_html, re.I | re.S)
    if match:
        value = _clean_html_text(match.group(1))
        if value:
            return value
    match = re.search(r'<div[^>]+class="user-title"[^>]*>(.*?)</div>', page_html, re.I | re.S)
    if match:
        value = _clean_html_text(match.group(1))
        if value:
            return value
    return fallback


def _extract_js_vars(page_html: str) -> dict[str, str]:
    return dict(re.findall(r"var\s+([A-Za-z0-9_]+)\s*=\s*'([^']*)';", page_html))


def _extract_value(page_html: str, key: str, variables: dict[str, str]) -> str:
    pattern = rf"['\"]{re.escape(key)}['\"]\s*:\s*('([^']*)'|\"([^\"]*)\"|([A-Za-z0-9_]+)|([0-9]+))"
    match = re.search(pattern, page_html)
    if not match:
        return ""
    if match.group(2) is not None:
        return match.group(2)
    if match.group(3) is not None:
        return match.group(3)
    if match.group(5) is not None:
        return match.group(5)
    token = match.group(4) or ""
    return variables.get(token, token)


class LanzouWebProvider:
    name = "lanzou_web"
    browser_profiles = [
        {
            "name": "mobile_edge",
            "headers": {
                "User-Agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36 Edg/122.0.0.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        },
        {
            "name": "desktop_hbpc",
            "headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.84 Safari/537.36 HBPC/12.1.2.300",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        },
    ]

    def __init__(self, timeout_seconds: float = 20.0):
        self.timeout_seconds = timeout_seconds

    def fetch(self, watcher: WatcherConfig, _config: AppConfig) -> ShareSnapshot:
        last_error_code = "file_list_endpoint_not_found"
        for profile in self.browser_profiles:
            session = requests.Session()
            session.headers.update(profile["headers"])
            response = _request_with_stream(session.get, watcher.url, timeout=self.timeout_seconds)
            response.raise_for_status()
            page_html = _bounded_bytes(response, _MAX_HTML_BYTES).decode("utf-8", errors="replace")
            title = _extract_title(page_html, watcher.title)
            ajax_match = re.search(r"url\s*:\s*['\"]([^'\"]*filemoreajax\.php\?file=(\d+)[^'\"]*)['\"]", page_html)
            if ajax_match:
                break
            if "arg1=" in page_html and "<title>" not in page_html.lower():
                last_error_code = "anti_bot_challenge"
                continue
        else:
            raise ProviderError(last_error_code)

        ajax_url = urljoin(response.url, ajax_match.group(1))
        variables = _extract_js_vars(page_html)
        base_payload = {
            key: _extract_value(page_html, key, variables)
            for key in ["lx", "fid", "uid", "puid", "rep", "up", "vip", "webfoldersign"]
        }
        base_payload["pg"] = "1"
        base_payload["t"] = _extract_value(page_html, "t", variables)
        base_payload["k"] = _extract_value(page_html, "k", variables)
        if watcher.password:
            base_payload["pwd"] = watcher.password

        files: list[FileEntry] = []
        seen_ids: set[str] = set()
        for page in range(1, watcher.max_pages + 1):
            payload = dict(base_payload)
            payload["pg"] = str(page)
            ajax_response = _request_with_stream(
                session.post,
                ajax_url,
                data=payload,
                timeout=self.timeout_seconds,
                headers={"Referer": watcher.url, "X-Requested-With": "XMLHttpRequest"},
            )
            ajax_response.raise_for_status()
            data = _bounded_json(ajax_response)
            if str(data.get("zt")) != "1":
                if page == 1:
                    raise ProviderError("ajax_status_rejected")
                break
            rows = data.get("text")
            if not isinstance(rows, list) or not rows:
                break
            added_this_page = 0
            for row in rows:
                if not isinstance(row, dict):
                    continue
                raw_file_id = str(
                    row.get("id") or row.get("duan") or row.get("name_all") or ""
                ).strip()
                file_id = _stable_file_id(raw_file_id)
                if not file_id or file_id in seen_ids:
                    continue
                seen_ids.add(file_id)
                added_this_page += 1
                name = _clean_html_text(row.get("name_all") or row.get("name") or file_id)
                files.append(
                    FileEntry(
                        id=file_id,
                        name=name,
                        size=str(row.get("size") or "").strip(),
                        modified_time=str(row.get("time") or "").strip(),
                        link=urljoin(response.url, f"/{file_id}"),
                        icon=str(row.get("icon") or "").strip(),
                        raw=row,
                    )
                )
            if added_this_page == 0:
                break

        return ShareSnapshot(
            watcher_id=watcher.id,
            title=title,
            url=watcher.url,
            provider=self.name,
            fetched_at=utc_now_iso(),
            files=files,
            raw_status={
                "ajax_url": ajax_url,
                "browser_profile": profile["name"],
                "pages_read": min(watcher.max_pages, max(1, page)),
            },
        )


class WerApiProvider:
    name = "wer_api"

    def fetch(self, watcher: WatcherConfig, config: AppConfig) -> ShareSnapshot:
        if not config.wer_api_key:
            raise ProviderError("provider_not_configured", retryable=False)
        payload = {
            "key": config.wer_api_key,
            config.wer_api_url_param: watcher.url,
        }
        if watcher.password:
            payload[config.wer_api_password_param] = watcher.password
        method = config.wer_api_method.upper()
        if method == "POST":
            response = requests.post(config.wer_api_endpoint, data=payload, timeout=20, stream=True)
        else:
            response = requests.get(config.wer_api_endpoint, params=payload, timeout=20, stream=True)
        response.raise_for_status()
        try:
            body = _bounded_json(response)
        finally:
            response.close()
        code = body.get("code")
        data = body.get("data")
        if data is None and code not in (0, 1, 200, "0", "1", "200"):
            raise ProviderError("provider_status_rejected")
        files = self._extract_files(data, watcher)
        return ShareSnapshot(
            watcher_id=watcher.id,
            title=watcher.title,
            url=watcher.url,
            provider=self.name,
            fetched_at=utc_now_iso(),
            files=files,
            raw_status={"code": code, "msg": body.get("msg")},
        )

    def _extract_files(self, data: Any, watcher: WatcherConfig) -> list[FileEntry]:
        rows: list[dict[str, Any]] = []

        def walk(value: Any) -> None:
            if isinstance(value, list):
                for item in value:
                    walk(item)
                return
            if not isinstance(value, dict):
                return
            keys = set(value)
            name_key = next((key for key in ["name_all", "filename", "file_name", "name", "title"] if key in keys), "")
            url_key = next((key for key in ["url", "downurl", "download", "link", "file_url"] if key in keys), "")
            if name_key or url_key or "id" in keys:
                rows.append(value)
            for child in value.values():
                if isinstance(child, (dict, list)):
                    walk(child)

        walk(data)
        files: list[FileEntry] = []
        seen_ids: set[str] = set()
        for index, row in enumerate(rows, start=1):
            name = _clean_html_text(
                row.get("name_all")
                or row.get("filename")
                or row.get("file_name")
                or row.get("name")
                or row.get("title")
                or f"{watcher.title}-{index}"
            )
            link = str(row.get("url") or row.get("downurl") or row.get("download") or row.get("link") or row.get("file_url") or "")
            file_id = str(row.get("id") or row.get("fid") or link or name or index).strip()
            if file_id in seen_ids:
                continue
            seen_ids.add(file_id)
            files.append(
                FileEntry(
                    id=file_id,
                    name=name,
                    size=str(row.get("size") or row.get("filesize") or "").strip(),
                    modified_time=str(row.get("time") or row.get("updated_at") or row.get("date") or "").strip(),
                    link=link,
                    icon=str(row.get("icon") or "").strip(),
                    raw=row,
                )
            )
        return files


class ProviderChain:
    def __init__(self, config: AppConfig):
        self.config = config
        self.providers = {
            "lanzou_web": LanzouWebProvider(),
            "wer_api": WerApiProvider(),
        }

    def fetch(self, watcher: WatcherConfig) -> ShareSnapshot:
        attempts: list[dict[str, Any]] = []
        empty_snapshot: ShareSnapshot | None = None
        empty_providers: list[str] = []
        for provider_name in self.config.provider_order:
            provider = self.providers.get(provider_name)
            if not provider:
                attempts.append(
                    {
                        "provider": _safe_identifier(provider_name, "unknown-provider"),
                        "error_code": "unknown_provider",
                        "error_class": "ProviderConfigurationError",
                        "retryable": False,
                    }
                )
                continue
            try:
                snapshot = provider.fetch(watcher, self.config)
                if not snapshot.files:
                    if empty_snapshot is None:
                        empty_snapshot = snapshot
                    empty_providers.append(
                        _safe_identifier(provider_name, "provider")
                    )
                    continue
                return snapshot
            except Exception as exc:
                attempts.append(
                    {
                        "provider": _safe_identifier(provider_name, "provider"),
                        **_provider_failure(exc),
                    }
                )
        if empty_snapshot is not None:
            raw_status = dict(empty_snapshot.raw_status)
            raw_status["empty_candidate"] = True
            raw_status["empty_providers"] = empty_providers
            return ShareSnapshot(
                watcher_id=empty_snapshot.watcher_id,
                title=empty_snapshot.title,
                url=empty_snapshot.url,
                provider=empty_snapshot.provider,
                fetched_at=empty_snapshot.fetched_at,
                files=[],
                raw_status=raw_status,
            )
        raise ProviderError(
            "providers_unavailable" if attempts else "no_provider_configured",
            retryable=any(item.get("retryable") is True for item in attempts),
            attempts=attempts,
        )


def snapshot_from_state(value: dict[str, Any]) -> ShareSnapshot:
    return ShareSnapshot(
        watcher_id=str(value.get("watcher_id") or ""),
        title=str(value.get("title") or ""),
        url=str(value.get("url") or ""),
        provider=str(value.get("provider") or ""),
        fetched_at=str(value.get("fetched_at") or ""),
        files=[
            FileEntry(
                id=_stable_file_id(item.get("id")),
                name=str(item.get("name") or ""),
                size=str(item.get("size") or ""),
                modified_time=str(item.get("modified_time") or ""),
                link=_stable_file_link(item.get("link")),
                icon=str(item.get("icon") or ""),
                raw=item.get("raw") if isinstance(item.get("raw"), dict) else {},
            )
            for item in value.get("files", [])
            if isinstance(item, dict)
        ],
        raw_status=value.get("raw_status") if isinstance(value.get("raw_status"), dict) else {},
    )
